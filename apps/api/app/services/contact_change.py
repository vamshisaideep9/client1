"""Phone and email changes, added emails and their permanent history (CS-025).

One state machine (``contact_change_requests``) serves three journeys; this
module is its only writer. Every journey runs on a bypass session, the same
shape as ``services/mobile_change.py``: uniqueness across accounts cannot be
checked under the caller's RLS context, and completion touches several tables
with deliberately narrow grants. The route has already authenticated the
caller; every function here re-checks the actor against the row it touches.

Invariants:

- one active row per account (partial unique index), so a phone change and an
  email change are never in flight together (409);
- every code is keyed to one row and one stage and bound to the keyed
  fingerprint of the value it was sent to (``otp:contact_change_target:*``);
  a code for the current value cannot verify the new value, a code from one
  change cannot verify another, and login or registration codes never apply;
- a row moves only along its journey's steps, checked under a row lock, and
  expires (raw value cleared) when its window closes;
- the raw new value is cleared on every terminal status (database CHECK); the
  permanent copy is written only to ``contact_change_history`` (platform
  Admin only) in the same transaction as the identity update;
- audit and auth events carry ids, field and method only, never values.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.cache.redis_keys import (
    TTL_CONTACT_CHANGE_RATE_ACCOUNT,
    TTL_CONTACT_CHANGE_TARGET_DAILY,
    TTL_OTP,
    RedisCache,
    contact_change_rate_account_key,
    contact_change_target_daily_key,
    otp_contact_change_key,
    otp_contact_change_target_key,
)
from app.core.config import settings
from app.core.masking import mask_email, mask_mobile
from app.core.security import verify_password
from app.models.audit_log import AuditAction
from app.models.auth import AuthEvent
from app.models.contact_change import (
    ACTIVE_CONTACT_CHANGE_STATUSES,
    ContactChangeHistory,
    ContactChangeKind,
    ContactChangeMethod,
    ContactChangeRequest,
    ContactChangeStatus,
    ContactField,
)
from app.models.user import User, UserStatus
from app.schemas.contact_change import ContactChangeChallengeResponse
from app.services.audit_log import record as record_audit
from app.services.otp import (
    check_login_lock,
    check_otp_rate_ip,
    generate_and_store_otp,
    record_login_failure,
    resend_otp,
    verify_otp,
)
from app.services.otp_delivery import DeliveryChannel, deliver_otp

logger = logging.getLogger(__name__)

# Telecaller, Employee and Sub Admin (team managers included) never change
# their own contact details (CS-021); they request a change instead (CS-025).
STAFF_REQUEST_ROLES = frozenset({"telecaller", "employee", "sub_admin"})


class ContactChangeError(Exception):
    """Base for the journey's typed refusals; routes map each to one status."""


class ChangeNotFound(ContactChangeError):
    """No such change for this account (404)."""


class ChangeInProgress(ContactChangeError):
    """Another phone or email change is already active for the account (409)."""


class StepConflict(ContactChangeError):
    """The change is not at the step this call needs (409)."""


class ChangeExpired(ContactChangeError):
    """The change's window closed; start again (409)."""


class WrongPassword(ContactChangeError):
    """Current password re-entry failed (403)."""


class NotPermitted(ContactChangeError):
    """This role or account cannot take this journey (403)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ValueUnavailable(ContactChangeError):
    """The new value cannot be used (same as now, or held elsewhere) (409)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class CodeTargetMismatch(ContactChangeError):
    """The code was sent to a value the row no longer holds; resend (400)."""


class ContactRateLimited(ContactChangeError):
    """A purpose-specific budget is exhausted (429)."""


@dataclass(frozen=True)
class Actor:
    user_uuid: UUID
    role: str


def contact_fingerprint(field: str, value: str) -> str:
    """Keyed, domain-separated fingerprint; never stored as the value itself."""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"contact-change:v1:{field}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def mask_value(field: str, value: str | None) -> str:
    return mask_mobile(value) if field == ContactField.MOBILE else mask_email(value)


def _now() -> datetime:
    return datetime.now(UTC)


def _is_mock_env() -> bool:
    return settings.OTP_EXPOSE_HINT or settings.ENV == "development"


def _bypass_session() -> AsyncSession:
    # Resolved at call time so the test suite's NullPool rebind applies.
    return db_session.AsyncSessionLocal()


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


async def check_account_budget(cache: RedisCache, user_uuid: UUID) -> None:
    """Every start, resend and password attempt counts per account per hour."""
    count = await cache.incr_with_expire(
        contact_change_rate_account_key(str(user_uuid)), TTL_CONTACT_CHANGE_RATE_ACCOUNT
    )
    if count > settings.CONTACT_CHANGE_START_LIMIT_PER_ACCOUNT:
        raise ContactRateLimited


async def check_target_budget(cache: RedisCache, field: str, value: str) -> None:
    """Codes sent to one new number or address per day, whoever asks."""
    count = await cache.incr_with_expire(
        contact_change_target_daily_key(contact_fingerprint(field, value)),
        TTL_CONTACT_CHANGE_TARGET_DAILY,
    )
    if count > settings.CONTACT_CHANGE_TARGET_DAILY_LIMIT:
        raise ContactRateLimited


def _rate_subject(field: str, value: str) -> str:
    # Mobiles share the per-number daily OTP budget with login, registration
    # and reset; addresses get the same budget under a fingerprinted subject.
    if field == ContactField.MOBILE:
        return value
    return f"email:{contact_fingerprint(field, value)}"


async def reauthenticate(cache: RedisCache, user: User, password: str) -> None:
    """Password re-entry sharing the login lock, so guesses here count there."""
    await check_login_lock(cache, user.mobile)
    if user.password_hash is None or not await verify_password(password, user.password_hash):
        await record_login_failure(cache, user.mobile)
        raise WrongPassword


# ---------------------------------------------------------------------------
# Codes bound to one change and one stage
# ---------------------------------------------------------------------------


async def issue_code(
    cache: RedisCache,
    *,
    change_id: UUID,
    stage: str,
    field: str,
    destination: str,
    resend: bool = False,
) -> tuple[DeliveryChannel, str]:
    """Generate (or resend) the stage's code and send it to ``destination``."""
    purpose = f"contact_change_{stage}"
    subject = str(change_id)
    rate_subject = _rate_subject(field, destination)
    if resend:
        otp = await resend_otp(cache, subject, purpose, rate_subject=rate_subject)
    else:
        otp = await generate_and_store_otp(cache, subject, purpose, rate_subject=rate_subject)
    await cache.set(
        otp_contact_change_target_key(stage, subject),
        contact_fingerprint(field, destination),
        TTL_OTP,
    )
    if field == ContactField.MOBILE:
        # A number is proven only by a call to that number; never by email.
        channel = await deliver_otp(destination, "", otp, allow_email_fallback=False)
    else:
        channel = await deliver_otp("", destination, otp, via_email=True)
    return channel, otp


async def _discard_code(cache: RedisCache, change_id: UUID, stage: str) -> None:
    key = otp_contact_change_key(stage, str(change_id))
    await cache.delete(key, f"{key}:attempts", otp_contact_change_target_key(stage, str(change_id)))


async def verify_code(
    cache: RedisCache,
    *,
    change_id: UUID,
    stage: str,
    field: str,
    expected_value: str,
    otp: str,
) -> None:
    """Verify a stage code only if it was sent to ``expected_value``."""
    target_key = otp_contact_change_target_key(stage, str(change_id))
    stored = await cache.get(target_key)
    expected = contact_fingerprint(field, expected_value)
    if stored is None or not hmac.compare_digest(stored, expected):
        await _discard_code(cache, change_id, stage)
        raise CodeTargetMismatch
    # Raises 400 for a wrong, expired, exhausted or replayed code.
    await verify_otp(cache, str(change_id), f"contact_change_{stage}", otp)
    await cache.delete(target_key)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _terminate(row: ContactChangeRequest, new_status: ContactChangeStatus) -> None:
    row.status = new_status
    row.new_value = None


async def expire_stale(db: AsyncSession, *, user_uuid: UUID | None = None) -> int:
    """Close every active row past its window and clear its raw value."""
    stmt = select(ContactChangeRequest).where(
        ContactChangeRequest.status.in_(tuple(ACTIVE_CONTACT_CHANGE_STATUSES)),
        ContactChangeRequest.expires_at <= _now(),
    )
    if user_uuid is not None:
        stmt = stmt.where(ContactChangeRequest.auth_user_uuid == user_uuid)
    rows = (await db.scalars(stmt.with_for_update(skip_locked=True))).all()
    for row in rows:
        _terminate(row, ContactChangeStatus.EXPIRED)
    return len(rows)


async def expire_stale_changes() -> int:
    """Scheduler sweep so an abandoned row never keeps its raw value for long."""
    async with _bypass_session() as db:
        count = await expire_stale(db)
        await db.commit()
    if count:
        logger.info("contact_change.expired count=%d", count)
    return count


async def active_change(db: AsyncSession, user_uuid: UUID) -> ContactChangeRequest | None:
    return await db.scalar(
        select(ContactChangeRequest)
        .where(
            ContactChangeRequest.auth_user_uuid == user_uuid,
            ContactChangeRequest.status.in_(tuple(ACTIVE_CONTACT_CHANGE_STATUSES)),
        )
        .with_for_update()
    )


async def lock_own_change(
    db: AsyncSession, *, change_id: UUID, user_uuid: UUID
) -> ContactChangeRequest:
    """Lock the caller's own row; expire it first if its window closed."""
    row = await db.scalar(
        select(ContactChangeRequest)
        .where(
            ContactChangeRequest.id == change_id,
            ContactChangeRequest.auth_user_uuid == user_uuid,
        )
        .with_for_update()
    )
    if row is None:
        raise ChangeNotFound
    if row.status in ACTIVE_CONTACT_CHANGE_STATUSES and row.expires_at <= _now():
        _terminate(row, ContactChangeStatus.EXPIRED)
        await db.commit()
        raise ChangeExpired
    if row.status == ContactChangeStatus.EXPIRED:
        raise ChangeExpired
    return row


async def lock_user(db: AsyncSession, user_uuid: UUID) -> User:
    user = await db.scalar(
        select(User)
        .where(User.id == user_uuid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotPermitted("This account cannot change its contact details.")
    return user


def challenge_response(
    row: ContactChangeRequest,
    *,
    message: str,
    destination: str | None = None,
    channel: DeliveryChannel | None = None,
    otp: str | None = None,
) -> ContactChangeChallengeResponse:
    return ContactChangeChallengeResponse(
        change_id=row.id,
        kind=row.kind,
        field=row.field,
        status=row.status,
        expires_at=row.expires_at,
        message=message,
        destination_hint=mask_value(row.field, destination) if destination else None,
        delivery_channel=channel,
        otp_hint=otp if channel == "none" and otp and _is_mock_env() else None,
    )


def write_history(
    db: AsyncSession,
    *,
    user_uuid: UUID,
    field: str,
    old_value: str | None,
    new_value: str,
    method: ContactChangeMethod,
    request_uuid: UUID | None,
    approved_by: UUID | None = None,
    proof_category: str | None = None,
    proof_reference: str | None = None,
) -> None:
    db.add(
        ContactChangeHistory(
            auth_user_uuid=user_uuid,
            field=field,
            old_value=old_value,
            new_value=new_value,
            method=method.value,
            proof_category=proof_category,
            proof_reference=proof_reference,
            approved_by_user_uuid=approved_by,
            request_uuid=request_uuid,
        )
    )


async def claim_email(db: AsyncSession, *, user: User, email: str) -> None:
    """Make ``email`` assignable to ``user`` after its owner proved control.

    A *verified* address on another account is a hard conflict. An unverified
    copy on another account was never proven by anyone, so the proven owner
    wins and that copy is released (the other account will be asked to add
    an email again). Without this, typing someone else's address without
    verifying it would block them from ever using it.
    """
    holders = (
        await db.scalars(
            select(User)
            .where(func.lower(User.email) == email, User.id != user.id)
            .with_for_update()
        )
    ).all()
    for holder in holders:
        if holder.email_verified_at is not None:
            raise ValueUnavailable("This email is already used by another account.")
    if holders:
        await db.execute(
            update(User)
            .where(User.id.in_([holder.id for holder in holders]))
            .values(email=None, email_verified_at=None)
        )


# ---------------------------------------------------------------------------
# Add an email (accounts without a verified one)
# ---------------------------------------------------------------------------


async def start_email_add(
    cache: RedisCache,
    *,
    actor: Actor,
    email: str,
    current_password: str,
    ip: str | None,
) -> ContactChangeChallengeResponse:
    """Password, then a code to the new address. Replaces an unfinished add."""
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        if user.email_verified_at is not None:
            raise ValueUnavailable("Your email is already verified.")
        if (
            actor.role in STAFF_REQUEST_ROLES
            and user.email is not None
            and user.email.lower() != email
        ):
            # An Admin set this address; a different one needs Admin approval.
            raise NotPermitted(
                "Your Admin manages your email. Verify the email on file or request a change."
            )
        await reauthenticate(cache, user, current_password)
        await expire_stale(db, user_uuid=user.id)
        row = await active_change(db, user.id)
        if row is not None and row.kind != ContactChangeKind.EMAIL_ADD:
            raise ChangeInProgress
        await check_target_budget(cache, ContactField.EMAIL, email)
        expires_at = _now() + timedelta(minutes=settings.CONTACT_CHANGE_FLOW_EXPIRE_MINUTES)
        if row is None:
            row = ContactChangeRequest(
                auth_user_uuid=user.id,
                kind=ContactChangeKind.EMAIL_ADD.value,
                field=ContactField.EMAIL.value,
                status=ContactChangeStatus.AWAITING_NEW_OTP.value,
                expires_at=expires_at,
            )
            db.add(row)
        row.new_value = email
        row.expires_at = expires_at
        try:
            await db.commit()
        except IntegrityError as exc:
            raise ChangeInProgress from exc
        change_id = row.id
    channel, otp = await issue_code(
        cache,
        change_id=change_id,
        stage="new",
        field=ContactField.EMAIL,
        destination=email,
    )
    await _log_auth_event(actor.user_uuid, "otp_sent", {"purpose": "email_add", "channel": channel})
    return challenge_response(
        row,
        message="We sent a code to your email.",
        destination=email,
        channel=channel,
        otp=otp,
    )


async def resend_email_add(
    cache: RedisCache, *, actor: Actor, change_id: UUID, ip: str | None
) -> ContactChangeChallengeResponse:
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.EMAIL_ADD
            or row.status != ContactChangeStatus.AWAITING_NEW_OTP
            or row.new_value is None
        ):
            raise StepConflict
        email = row.new_value
        await db.commit()
    await check_target_budget(cache, ContactField.EMAIL, email)
    channel, otp = await issue_code(
        cache,
        change_id=change_id,
        stage="new",
        field=ContactField.EMAIL,
        destination=email,
        resend=True,
    )
    return challenge_response(
        row,
        message="We sent a new code to your email.",
        destination=email,
        channel=channel,
        otp=otp,
    )


async def verify_email_add(cache: RedisCache, *, actor: Actor, change_id: UUID, otp: str) -> None:
    """Verify the code and store the address as verified, atomically."""
    async with _bypass_session() as db:
        # Lock order everywhere: the account row, then the change row.
        user = await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.EMAIL_ADD
            or row.status != ContactChangeStatus.AWAITING_NEW_OTP
            or row.new_value is None
        ):
            raise StepConflict
        email = row.new_value
        await verify_code(
            cache,
            change_id=row.id,
            stage="new",
            field=ContactField.EMAIL,
            expected_value=email,
            otp=otp,
        )
        now = _now()
        if user.email_verified_at is not None:
            # Verified by another path meanwhile; nothing left to add.
            _terminate(row, ContactChangeStatus.CANCELLED)
            await db.commit()
            raise ValueUnavailable("Your email is already verified.")
        try:
            await claim_email(db, user=user, email=email)
        except ValueUnavailable:
            _terminate(row, ContactChangeStatus.CANCELLED)
            await db.commit()
            raise
        user.email = email
        user.email_verified_at = now
        row.new_verified_at = now
        row.completed_at = now
        _terminate(row, ContactChangeStatus.COMPLETED)
        write_history(
            db,
            user_uuid=user.id,
            field=ContactField.EMAIL,
            old_value=None,
            new_value=email,
            method=ContactChangeMethod.EMAIL_ADDED,
            request_uuid=row.id,
        )
        db.add(
            AuthEvent(
                auth_user_uuid=user.id,
                event_type="email_added",
                mobile=None,
                success=True,
                detail={"change_id": str(row.id)},
            )
        )
        await record_audit(
            db,
            action=AuditAction.CONTACT_CHANGED,
            entity_type="contact_change_request",
            entity_uuid=row.id,
            actor_uuid=actor.user_uuid,
            actor_role=actor.role,
            detail={"field": ContactField.EMAIL.value, "method": ContactChangeMethod.EMAIL_ADDED},
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            # A concurrent registration or change claimed the address.
            raise ValueUnavailable("This email is already used by another account.") from exc


async def _log_auth_event(user_uuid: UUID, event_type: str, detail: dict) -> None:
    try:
        async with _bypass_session() as db:
            db.add(
                AuthEvent(
                    auth_user_uuid=user_uuid,
                    event_type=event_type,
                    mobile=None,
                    success=True,
                    detail=detail,
                )
            )
            await db.commit()
    except Exception:  # an event-log failure must not fail a sent code
        logger.warning("contact_change.auth_event_failed type=%s", event_type, exc_info=True)


def http_error(exc: ContactChangeError) -> HTTPException:
    """One place mapping the journey's refusals to responses."""
    if isinstance(exc, ChangeNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "This change was not found.")
    if isinstance(exc, ChangeInProgress):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            "Another phone or email change is already in progress. Finish or cancel it first.",
        )
    if isinstance(exc, ChangeExpired):
        return HTTPException(status.HTTP_409_CONFLICT, "This change expired. Start again.")
    if isinstance(exc, StepConflict):
        return HTTPException(
            status.HTTP_409_CONFLICT, "This change is not at that step. Refresh and try again."
        )
    if isinstance(exc, WrongPassword):
        return HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect.")
    if isinstance(exc, NotPermitted):
        return HTTPException(status.HTTP_403_FORBIDDEN, exc.detail)
    if isinstance(exc, ValueUnavailable):
        return HTTPException(status.HTTP_409_CONFLICT, exc.detail)
    if isinstance(exc, CodeTargetMismatch):
        return HTTPException(
            status.HTTP_400_BAD_REQUEST, "That code is no longer valid. Request a new code."
        )
    if isinstance(exc, ContactRateLimited):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again later."
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, "This change could not be completed.")
