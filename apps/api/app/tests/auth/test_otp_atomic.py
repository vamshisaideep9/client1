"""OTP limits and consumption must hold across concurrent requests and resends."""

import asyncio

import pytest
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException

from app.cache.redis_keys import RedisCache, otp_register_key
from app.services import otp
from conftest import unique_mobile


@pytest.fixture
async def challenge(live_app):
    cache = RedisCache(live_app.state.redis)
    mobile = unique_mobile()
    key = otp_register_key(mobile)
    await cache.set(key, "original-hash", 60)
    await cache.set(f"{key}:attempts", 5, 60)
    yield cache, mobile, key
    await cache.delete(key, f"{key}:attempts")


def delayed_verification(monkeypatch, *, valid=True):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def verify(_function, stored, code, **_kwargs):
        calls.append((stored, code))
        if len(calls) == 1:
            entered.set()
            await release.wait()
        if not valid:
            raise VerifyMismatchError("Wrong code")
        return True

    monkeypatch.setattr(otp.anyio.to_thread, "run_sync", verify)
    return entered, release, calls


async def test_last_attempt_is_reserved_before_hash_work(challenge, monkeypatch):
    cache, mobile, key = challenge
    await cache.set(f"{key}:attempts", 1, 60)
    entered, release, calls = delayed_verification(monkeypatch, valid=False)
    first = asyncio.create_task(otp.verify_otp(cache, mobile, "register", "000000"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        others = await asyncio.gather(
            *(otp.verify_otp(cache, mobile, "register", "000000") for _ in range(12)),
            return_exceptions=True,
        )
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
    assert all(isinstance(result, HTTPException) for result in others)
    assert len(calls) == 1, "Concurrent guesses must not bypass the final attempt"
    assert await cache.get(f"{key}:attempts") == "0"
    assert await cache.ttl(f"{key}:attempts") > 0


async def test_concurrent_correct_code_is_accepted_only_once(challenge, monkeypatch):
    cache, mobile, _key = challenge
    entered, release, _calls = delayed_verification(monkeypatch)
    first = asyncio.create_task(otp.verify_otp(cache, mobile, "register", "123456"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await otp.verify_otp(cache, mobile, "register", "123456")
    finally:
        release.set()
    result = (await asyncio.gather(first, return_exceptions=True))[0]
    assert isinstance(result, HTTPException), "A code must not produce two verified sessions"


@pytest.mark.parametrize("valid", [True, False])
async def test_inflight_verification_cannot_consume_or_charge_replacement(
    challenge, monkeypatch, valid
):
    cache, mobile, key = challenge
    entered, release, _calls = delayed_verification(monkeypatch, valid=valid)
    first = asyncio.create_task(otp.verify_otp(cache, mobile, "register", "123456"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await cache.set(key, "replacement-hash", 60)
        await cache.set(f"{key}:attempts", 5, 60)
    finally:
        release.set()
    result = (await asyncio.gather(first, return_exceptions=True))[0]
    assert isinstance(result, HTTPException)
    assert await cache.get(key) == "replacement-hash"
    assert await cache.get(f"{key}:attempts") == "5"
