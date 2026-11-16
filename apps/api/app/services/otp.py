"""OTP generation, storage, verification, and rate-limiting (Auth Design §8)."""

from __future__ import annotations

import logging
import secrets

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, status

from app.cache.redis_keys import (
    TTL_LOGIN_LOCK,
    TTL_LOGIN_RATE_IP,
    TTL_OTP,
    TTL_OTP_RATE,
    TTL_OTP_RATE_IP,
    TTL_OTP_RESEND,
    RedisCache,
    login_fail_key,
    login_lock_key,
    login_rate_ip_key,
    otp_agent_apply_key,
    otp_contact_change_key,
    otp_email_verify_key,
    otp_lock_key,
    otp_mobile_change_key,
    otp_rate_ip_key,
    otp_rate_key,
    otp_register_email_key,
    otp_register_key,
    otp_resend_key,
    otp_reset_key,
)
from app.core.config import settings
from app.core.masking import mask_mobile
from app.core.security import ARGON2_LIMITER

logger = logging.getLogger(__name__)

_ph = PasswordHasher()

_OTP_RATE_DAILY_MAX = 5
_RESEND_LIMIT = 3
_LOGIN_FAIL_MAX = 5


def _otp_key(mobile: str, purpose: str) -> str:
    if purpose == "register":
        return otp_register_key(mobile)
    if purpose == "reset":
        return otp_reset_key(mobile)
    if purpose == "email_verify":
        return otp_email_verify_key(mobile)
    if purpose == "agent_apply":
        return otp_agent_apply_key(mobile)
    if purpose == "mobile_change":
        return otp_mobile_change_key(mobile)
    if purpose == "register_email":
        return otp_register_email_key(mobile)
    # CS-025: the subject is the change row id, not a number, so a code is
    # bound to one change and one stage.
    if purpose == "contact_change_current":
        return otp_contact_change_key("current", mobile)
    if purpose == "contact_change_new":
        return otp_contact_change_key("new", mobile)
    raise ValueError(f"Unknown OTP purpose: {purpose}")


async def generate_and_store_otp(
    cache: RedisCache,
    mobile: str,
    purpose: str,
    *,
    rate_subject: str | None = None,
) -> str:
    """Generate 6-digit OTP, hash+store in Redis, return plaintext.

    ``mobile`` is the key subject. ``rate_subject`` (default: the subject)
    selects the daily budget: contact-change codes are keyed by change id but
    still draw from the destination number's (or address's) shared budget.
    """
    await check_otp_rate(cache, rate_subject or mobile)
    otp = f"{secrets.randbelow(10**6):06d}"
    # argon2 is CPU-heavy even for a 6-digit OTP — hash off the event loop.
    otp_hash = await anyio.to_thread.run_sync(_ph.hash, otp, limiter=ARGON2_LIMITER)
    key = _otp_key(mobile, purpose)
    await cache.store_otp(key, otp_hash, settings.OTP_MAX_ATTEMPTS, TTL_OTP)
    logger.debug("otp.generated mobile=%s purpose=%s", mask_mobile(mobile), purpose)
    return otp


async def verify_otp(cache: RedisCache, mobile: str, purpose: str, code: str) -> None:
    """Verify OTP. Raises 400 on wrong/expired/exceeded. Burns OTP on success."""
    key = _otp_key(mobile, purpose)
    # Reserve before the expensive hash comparison. Checking then decrementing
    # after hashing lets concurrent requests all use the same final attempt.
    claim = await cache.claim_otp_attempt(key)
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP expired or not found. Request a new one.",
        )

    stored_hash, remaining = claim
    if remaining < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP attempts exhausted. Request a new one.",
        )

    try:
        await anyio.to_thread.run_sync(_ph.verify, stored_hash, code, limiter=ARGON2_LIMITER)
    except VerifyMismatchError as exc:
        # Keep the exhausted challenge alive for the existing resend flow.
        # Never mutate here: a resend may have replaced it while hashing.
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect OTP. No attempts remaining. Request a new one.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incorrect OTP. {remaining} attempt(s) remaining.",
        ) from exc

    # Compare-and-delete prevents replay and never burns a concurrent resend.
    if not await cache.consume_otp(key, stored_hash, otp_resend_key(mobile), otp_lock_key(mobile)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP expired, replaced or already used. Request a new one.",
        )
    logger.debug("otp.verified mobile=%s purpose=%s", mask_mobile(mobile), purpose)


async def ensure_active_otp_session(cache: RedisCache, mobile: str, purpose: str) -> None:
    """Require an initiated OTP without rotating or consuming it."""
    otp_key = _otp_key(mobile, purpose)
    if not await cache.exists(otp_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active OTP session. Please initiate first.",
        )


async def resend_otp(
    cache: RedisCache, mobile: str, purpose: str, *, rate_subject: str | None = None
) -> str:
    """Resend OTP. Max 3 resends per window, then 1-hour lock (Auth Design §8)."""
    await ensure_active_otp_session(cache, mobile, purpose)

    lock_key = otp_lock_key(mobile)
    if await cache.exists(lock_key):
        ttl = await cache.ttl(lock_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many OTP requests. Try again in {max(ttl // 60, 1)} min.",
        )

    count = await cache.incr_with_expire(otp_resend_key(mobile), TTL_OTP_RESEND)
    if count > _RESEND_LIMIT:
        await cache.set(lock_key, 1, TTL_OTP_RESEND)
        await cache.delete(otp_resend_key(mobile))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many resends. Try again in 1 hour.",
        )

    return await generate_and_store_otp(cache, mobile, purpose, rate_subject=rate_subject)


async def check_otp_rate(cache: RedisCache, mobile: str) -> None:
    """Daily OTP cap (5/day). Raises 429 if exceeded."""
    count = await cache.incr_with_expire(otp_rate_key(mobile), TTL_OTP_RATE)
    if count > _OTP_RATE_DAILY_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily OTP limit reached. Try again tomorrow.",
        )


async def check_otp_rate_ip(cache: RedisCache, ip: str | None) -> None:
    """Per-IP OTP initiation cap (OTP_RATE_LIMIT_PER_IP / hour).

    Complements the per-mobile daily cap: without it one host can iterate mobile
    numbers and burn real 2Factor voice-call / email spend (and enumerate which
    numbers are registered via the delivery_channel response). No-op when the
    client IP is unknown — the caller must supply a proxy-trusted IP, never a
    spoofable header value.
    """
    if not ip:
        return
    count = await cache.incr_with_expire(otp_rate_ip_key(ip), TTL_OTP_RATE_IP)
    if count > settings.OTP_RATE_LIMIT_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests from this network. Try again later.",
        )


async def check_login_rate_ip(cache: RedisCache, ip: str | None) -> None:
    """Per-IP failed-login cap (LOGIN_RATE_LIMIT_PER_IP / hour).

    Backstops the per-mobile lock: without it one host can spray a credential
    list across many mobiles (4 tries each) and never trip any limit. Counts
    only failures (record_login_failure_ip), so shared NAT IPs with normal
    successful traffic are unaffected. No-op when the client IP is unknown —
    the caller must supply a proxy-trusted IP, never a spoofable header value.
    """
    if not ip:
        return
    count_str = await cache.get(login_rate_ip_key(ip))
    if count_str and int(count_str) >= settings.LOGIN_RATE_LIMIT_PER_IP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts from this network. Try again later.",
        )


async def record_login_failure_ip(cache: RedisCache, ip: str | None) -> None:
    """Count a failed login against the source IP (1 h rolling window)."""
    if not ip:
        return
    await cache.incr_with_expire(login_rate_ip_key(ip), TTL_LOGIN_RATE_IP)


async def record_login_failure(cache: RedisCache, mobile: str) -> None:
    """Increment login failure counter. Lock account on 5th failure (Auth Design §6.6)."""
    fail_key = login_fail_key(mobile)
    lock_key = login_lock_key(mobile)
    count = await cache.incr_with_expire(fail_key, TTL_LOGIN_LOCK)
    if count >= _LOGIN_FAIL_MAX:
        await cache.set(lock_key, 1, TTL_LOGIN_LOCK)
        await cache.delete(fail_key)
        logger.warning("login.locked mobile=%s", mask_mobile(mobile))


async def check_login_lock(cache: RedisCache, mobile: str) -> None:
    """Raises 429 if login is locked."""
    lock_key = login_lock_key(mobile)
    if await cache.exists(lock_key):
        ttl = await cache.ttl(lock_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked. Try again in {max(ttl // 60, 1)} min.",
        )


async def clear_login_failures(cache: RedisCache, mobile: str) -> None:
    """Clear login failure counter on successful login."""
    await cache.delete(login_fail_key(mobile), login_lock_key(mobile))
