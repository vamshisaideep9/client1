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
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
from app.models.auth import AuthEvent, RefreshToken
from app.models.contact_change import (
    ACTIVE_CONTACT_CHANGE_STATUSES,
    ContactChangeHistory,
    ContactChangeKind,
    ContactChangeMethod,
    ContactChangeRequest,
    ContactChangeStatus,
    ContactField,
)
from app.models.mobile_change import MobileChangeRequest, MobileChangeStatus
from app.models.notification import Notification, NotificationType
from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
from app.models.push_subscription import PushSubscription
from app.models.user import User, UserStatus
from app.schemas.contact_change import (
    ContactChangeAdminRead,
    ContactChangeChallengeResponse,
    ContactChangeRead,
    ContactHistoryEntry,
)
from app.services.admin_notify import notify_admins
from app.services.audit_log import record as record_audit
from app.services.contact_identity import (
    clear_identity_caches,
    mobile_conflicts,
    propagate_mobile,
)
from app.services.email import send_email
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


class MakerCheckerViolation(ContactChangeError):
    """An Admin may never decide a request on their own account (409)."""


class InvalidValue(ContactChangeError):
    """The submitted value is not a valid number or address (422)."""

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
    if isinstance(exc, InvalidValue):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.detail)
    if isinstance(exc, MakerCheckerViolation):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            "The requester cannot approve or reject their own request.",
        )
    if isinstance(exc, CodeTargetMismatch):
        return HTTPException(
            status.HTTP_400_BAD_REQUEST, "That code is no longer valid. Request a new code."
        )
    if isinstance(exc, ContactRateLimited):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again later."
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, "This change could not be completed.")


# ---------------------------------------------------------------------------
# Self-service change (Client, Agent, Admin)
# ---------------------------------------------------------------------------

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_EMAIL_ADAPTER: TypeAdapter[str] = TypeAdapter(EmailStr)
_FIELD_NOUN = {ContactField.MOBILE: "number", ContactField.EMAIL: "email"}


def normalize_new_value(field: str, value: str) -> str:
    """Validate and normalize a submitted value for its field."""
    value = value.strip()
    if field == ContactField.MOBILE:
        if not _E164.match(value):
            raise InvalidValue("Enter the number with its country code, like +919876543210.")
        return value
    try:
        return str(_EMAIL_ADAPTER.validate_python(value)).strip().lower()
    except ValidationError as exc:
        raise InvalidValue("Enter a valid email address.") from exc


def current_value(user: User, field: str) -> str | None:
    return user.mobile if field == ContactField.MOBILE else user.email


def _noun(field: str) -> str:
    return _FIELD_NOUN[ContactField(field)]


def _current_matches(row: ContactChangeRequest, user: User) -> bool:
    """The value being replaced is still the one the change started from."""
    value = current_value(user, row.field)
    return (
        value is not None
        and row.current_fingerprint is not None
        and hmac.compare_digest(row.current_fingerprint, contact_fingerprint(row.field, value))
    )


async def _open_lost_number_request(db: AsyncSession, user_uuid: UUID) -> bool:
    return (
        await db.scalar(
            select(MobileChangeRequest.id).where(
                MobileChangeRequest.auth_user_uuid == user_uuid,
                MobileChangeRequest.status.in_(
                    (MobileChangeStatus.PENDING_REVIEW, MobileChangeStatus.PENDING_APPROVAL)
                ),
            )
        )
        is not None
    )


async def ensure_no_change_in_flight(db: AsyncSession, user_uuid: UUID) -> None:
    """One change per account: any active change or open lost-number request."""
    await expire_stale(db, user_uuid=user_uuid)
    if await active_change(db, user_uuid) is not None:
        raise ChangeInProgress
    if await _open_lost_number_request(db, user_uuid):
        raise ChangeInProgress


async def _cancel(db: AsyncSession, cache: RedisCache, row: ContactChangeRequest) -> None:
    _terminate(row, ContactChangeStatus.CANCELLED)
    await db.commit()
    for stage in ("current", "new"):
        await _discard_code(cache, row.id, stage)


async def precheck_new_value(db: AsyncSession, *, user: User, field: str, value: str) -> None:
    """Refuse an unusable value before any code is sent.

    Only what an existing public flow already reveals is checked here: a number
    registered to another account (registration answers the same). Whether an
    email or an enquiry belongs to someone is checked only after the code
    proves control of the new value.
    """
    current = current_value(user, field)
    if current is not None and current.lower() == value.lower():
        raise ValueUnavailable(f"That is already your {_noun(field)}.")
    if field == ContactField.MOBILE:
        holder = await db.scalar(select(User.id).where(User.mobile == value, User.id != user.id))
        if holder is not None:
            raise ValueUnavailable("This number is already registered to another account.")


async def start_self_service(
    cache: RedisCache,
    *,
    actor: Actor,
    field: str,
    current_password: str,
    ip: str | None,
) -> ContactChangeChallengeResponse:
    """Password, then a code to the CURRENT number or email."""
    if actor.role in STAFF_REQUEST_ROLES:
        raise NotPermitted(
            "Your Admin manages your contact details. Send a contact change request instead."
        )
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        await reauthenticate(cache, user, current_password)
        await ensure_no_change_in_flight(db, user.id)
        if field == ContactField.EMAIL and (user.email is None or user.email_verified_at is None):
            raise ValueUnavailable("Add and verify an email before changing it.")
        current = current_value(user, field)
        if current is None:
            raise ValueUnavailable("Add and verify an email before changing it.")
        row = ContactChangeRequest(
            auth_user_uuid=user.id,
            kind=ContactChangeKind.SELF_SERVICE.value,
            field=field,
            status=ContactChangeStatus.AWAITING_CURRENT_OTP.value,
            current_fingerprint=contact_fingerprint(field, current),
            expires_at=_now() + timedelta(minutes=settings.CONTACT_CHANGE_FLOW_EXPIRE_MINUTES),
        )
        db.add(row)
        db.add(
            AuthEvent(
                auth_user_uuid=user.id,
                event_type="contact_change_started",
                mobile=None,
                success=True,
                detail={"field": field, "kind": ContactChangeKind.SELF_SERVICE.value},
            )
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            raise ChangeInProgress from exc
    channel, otp = await issue_code(
        cache, change_id=row.id, stage="current", field=field, destination=current
    )
    return challenge_response(
        row,
        message=f"We sent a code to your current {_noun(field)}.",
        destination=current,
        channel=channel,
        otp=otp,
    )


async def resend_self_service(
    cache: RedisCache, *, actor: Actor, change_id: UUID, ip: str | None
) -> ContactChangeChallengeResponse:
    """Resend the code for whichever stage the change is waiting on."""
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if row.kind != ContactChangeKind.SELF_SERVICE:
            raise StepConflict
        if not _current_matches(row, user):
            await _cancel(db, cache, row)
            raise StepConflict
        if row.status == ContactChangeStatus.AWAITING_CURRENT_OTP:
            stage, destination = "current", current_value(user, row.field)
        elif row.status == ContactChangeStatus.AWAITING_NEW_OTP and row.new_value:
            stage, destination = "new", row.new_value
        else:
            raise StepConflict
        await db.commit()
    if destination is None:
        raise StepConflict
    if stage == "new":
        await check_target_budget(cache, row.field, destination)
    channel, otp = await issue_code(
        cache, change_id=row.id, stage=stage, field=row.field, destination=destination, resend=True
    )
    return challenge_response(
        row, message="We sent a new code.", destination=destination, channel=channel, otp=otp
    )


async def verify_current(
    cache: RedisCache, *, actor: Actor, change_id: UUID, otp: str
) -> ContactChangeChallengeResponse:
    """The current value is proven; the change now waits for the new value."""
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.SELF_SERVICE
            or row.status != ContactChangeStatus.AWAITING_CURRENT_OTP
        ):
            raise StepConflict
        current = current_value(user, row.field)
        if current is None or not _current_matches(row, user):
            await _cancel(db, cache, row)
            raise StepConflict
        await verify_code(
            cache,
            change_id=row.id,
            stage="current",
            field=row.field,
            expected_value=current,
            otp=otp,
        )
        row.status = ContactChangeStatus.AWAITING_NEW_VALUE.value
        row.current_verified_at = _now()
        await db.commit()
    return challenge_response(row, message=f"Code accepted. Enter your new {_noun(row.field)}.")


async def submit_new_value(
    cache: RedisCache, *, actor: Actor, change_id: UUID, value: str, ip: str | None
) -> ContactChangeChallengeResponse:
    """The new value, then a code to it. May be resubmitted until verified."""
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if row.kind != ContactChangeKind.SELF_SERVICE or row.status not in (
            ContactChangeStatus.AWAITING_NEW_VALUE,
            ContactChangeStatus.AWAITING_NEW_OTP,
        ):
            raise StepConflict
        if not _current_matches(row, user):
            await _cancel(db, cache, row)
            raise StepConflict
        value = normalize_new_value(row.field, value)
        await precheck_new_value(db, user=user, field=row.field, value=value)
        await check_target_budget(cache, row.field, value)
        row.new_value = value
        row.status = ContactChangeStatus.AWAITING_NEW_OTP.value
        await db.commit()
    channel, otp = await issue_code(
        cache, change_id=row.id, stage="new", field=row.field, destination=value
    )
    return challenge_response(
        row,
        message=f"We sent a code to your new {_noun(row.field)}.",
        destination=value,
        channel=channel,
        otp=otp,
    )


async def verify_new_and_apply(
    cache: RedisCache, *, actor: Actor, change_id: UUID, otp: str
) -> None:
    """Verify the new-value code and apply the change atomically."""
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.SELF_SERVICE
            or row.status != ContactChangeStatus.AWAITING_NEW_OTP
            or row.new_value is None
        ):
            raise StepConflict
        if not _current_matches(row, user):
            await _cancel(db, cache, row)
            raise StepConflict
        await verify_code(
            cache,
            change_id=row.id,
            stage="new",
            field=row.field,
            expected_value=row.new_value,
            otp=otp,
        )
        applied = await apply_change(
            db, row=row, user=user, actor=actor, method=ContactChangeMethod.SELF_SERVICE
        )
    await after_apply(cache, applied)


async def cancel_change(cache: RedisCache, *, actor: Actor, change_id: UUID) -> None:
    """Withdraw the caller's own change of any kind while it is active."""
    async with _bypass_session() as db:
        await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if row.status not in ACTIVE_CONTACT_CHANGE_STATUSES:
            raise StepConflict
        await _cancel(db, cache, row)


async def active_for(actor: Actor) -> ContactChangeRead | None:
    """The caller's own change in flight, if any, with its value masked."""
    async with _bypass_session() as db:
        await expire_stale(db, user_uuid=actor.user_uuid)
        await db.commit()
        row = await db.scalar(
            select(ContactChangeRequest).where(
                ContactChangeRequest.auth_user_uuid == actor.user_uuid,
                ContactChangeRequest.status.in_(tuple(ACTIVE_CONTACT_CHANGE_STATUSES)),
            )
        )
        if row is None:
            return None
        return ContactChangeRead(
            change_id=row.id,
            kind=row.kind,
            field=row.field,
            status=row.status,
            new_value_hint=mask_value(row.field, row.new_value) if row.new_value else None,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )


async def history_for_admin(
    db: AsyncSession, *, target_uuid: UUID, actor: Actor
) -> list[ContactHistoryEntry]:
    """A platform Admin's read of one account's permanent history (audited).

    Runs on the caller's RLS session: the history policy admits a platform
    Admin only, so a role-gate slip still returns nothing to anyone else.
    """
    approver = aliased(User)
    rows = (
        await db.execute(
            select(ContactChangeHistory, approver.first_name, approver.last_name)
            .outerjoin(approver, approver.id == ContactChangeHistory.approved_by_user_uuid)
            .where(ContactChangeHistory.auth_user_uuid == target_uuid)
            .order_by(ContactChangeHistory.changed_at.desc(), ContactChangeHistory.id)
        )
    ).all()
    await record_audit(
        db,
        action=AuditAction.CONTACT_HISTORY_VIEWED,
        entity_type="auth_user",
        entity_uuid=target_uuid,
        actor_uuid=actor.user_uuid,
        actor_role=actor.role,
        detail={"entries": len(rows)},
    )
    await db.commit()
    return [
        ContactHistoryEntry(
            id=entry.id,
            field=entry.field,
            old_value=entry.old_value,
            new_value=entry.new_value,
            method=entry.method,
            proof_category=entry.proof_category,
            proof_reference=entry.proof_reference,
            approved_by_name=(
                f"{first or ''} {last or ''}".strip() or None
                if entry.approved_by_user_uuid
                else None
            ),
            changed_at=entry.changed_at,
        )
        for entry, first, last in rows
    ]


# ---------------------------------------------------------------------------
# Applying a change (one transaction) and what follows the commit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Applied:
    field: str
    old_value: str | None
    new_value: str
    # Verified addresses that receive the security notice after the commit.
    notice_emails: tuple[str, ...]


async def apply_change(
    db: AsyncSession,
    *,
    row: ContactChangeRequest,
    user: User,
    actor: Actor,
    method: ContactChangeMethod,
    approved_by: UUID | None = None,
) -> Applied:
    """Replace the value, end every session and record history; commits.

    The caller holds the account and change row locks and has verified the
    last code (and, for a staff request, the approving Admin). A conflict found
    here cancels the change (its value is cleared) and raises.
    """
    field = row.field
    new_value = row.new_value
    if new_value is None:
        raise StepConflict
    old_value = current_value(user, field)
    old_email_verified = user.email_verified_at is not None
    try:
        if field == ContactField.MOBILE:
            if await mobile_conflicts(db, user_uuid=user.id, requested_mobile=new_value):
                raise ValueUnavailable(
                    "This number is linked to another account or enquiry. Contact support."
                )
        else:
            await claim_email(db, user=user, email=new_value)
    except ValueUnavailable:
        _terminate(row, ContactChangeStatus.CANCELLED)
        await db.commit()
        raise

    now = _now()
    if field == ContactField.MOBILE:
        user.mobile = new_value
        user.phone_verified_at = now
        await propagate_mobile(db, user_uuid=user.id, new_mobile=new_value)
        history_old = old_value
        notices = (user.email,) if user.email and old_email_verified else ()
    else:
        user.email = new_value
        user.email_verified_at = now
        # An address that was never verified is not a previous email.
        history_old = old_value if old_email_verified else None
        notices = tuple(v for v in (history_old, new_value) if v)
    user.session_version += 1
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.auth_user_uuid == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    await db.execute(delete(PushSubscription).where(PushSubscription.user_uuid == user.id))

    write_history(
        db,
        user_uuid=user.id,
        field=field,
        old_value=history_old,
        new_value=new_value,
        method=method,
        request_uuid=row.id,
        approved_by=approved_by,
    )
    row.new_verified_at = row.new_verified_at or now
    row.completed_at = now
    if approved_by is not None:
        row.decided_by_user_uuid = approved_by
        row.decided_at = now
    _terminate(row, ContactChangeStatus.COMPLETED)
    label = "phone number" if field == ContactField.MOBILE else "email"
    db.add(
        Notification(
            user_uuid=user.id,
            type=NotificationType.CONTACT_CHANGED,
            title=f"Your {label} was changed",
            body=(
                f"The {label} on your account was changed and every device was signed "
                "out. Contact support immediately if this was not you."
            ),
            href="/dashboard/settings",
        )
    )
    db.add(
        AuthEvent(
            auth_user_uuid=user.id,
            event_type="contact_changed",
            mobile=None,
            success=True,
            detail={"change_id": str(row.id), "field": field, "method": method.value},
        )
    )
    await record_audit(
        db,
        action=AuditAction.CONTACT_CHANGED,
        entity_type="contact_change_request",
        entity_uuid=row.id,
        actor_uuid=actor.user_uuid,
        actor_role=actor.role,
        detail={"field": field, "method": method.value},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        # The database's uniqueness is the final arbiter for a racing claim.
        raise ValueUnavailable("This number or email is already used by another account.") from exc
    return Applied(field=field, old_value=old_value, new_value=new_value, notice_emails=notices)


async def after_apply(cache: RedisCache, applied: Applied) -> None:
    """Best-effort work after the identity change committed.

    Notices go to the old and the new address for an email change, and to the
    verified email for a phone change: there is no SMS channel (DLT
    registration is out of scope), so neither number can be messaged.
    """
    if applied.field == ContactField.MOBILE and applied.old_value:
        await clear_identity_caches(cache, applied.old_value, applied.new_value)
    when = datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    if applied.field == ContactField.MOBILE:
        subject = "Your Dhanadhara login number was changed"
        body = (
            f"On {when} the login number on your Dhanadhara account changed from "
            f"{mask_mobile(applied.old_value)} to {mask_mobile(applied.new_value)}. "
            "Every device was signed out.\n\n"
            "If you did not make this change, contact support immediately."
        )
        for address in applied.notice_emails:
            await send_email(address, subject, body)
        return
    for address in applied.notice_emails:
        if address == applied.new_value:
            await send_email(
                address,
                "This is now your Dhanadhara email",
                (
                    f"On {when} this address became the email on your Dhanadhara account. "
                    "If you did not make this change, contact support immediately."
                ),
            )
        else:
            await send_email(
                address,
                "The email on your Dhanadhara account was changed",
                (
                    f"On {when} the email on your Dhanadhara account was changed to "
                    f"{mask_email(applied.new_value)}. Every device was signed out.\n\n"
                    "If you did not make this change, contact support immediately."
                ),
            )


# ---------------------------------------------------------------------------
# Staff requests (Telecaller, Employee, Sub Admin) and one-Admin decisions
# ---------------------------------------------------------------------------


async def start_staff_request(
    cache: RedisCache,
    *,
    actor: Actor,
    field: str,
    value: str,
    current_password: str,
    ip: str | None,
) -> ContactChangeChallengeResponse:
    """Password and the new value, then a code to it; an Admin decides after."""
    if actor.role not in STAFF_REQUEST_ROLES:
        raise NotPermitted("Change your phone number or email yourself in Settings.")
    value = normalize_new_value(field, value)
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        user = await lock_user(db, actor.user_uuid)
        await reauthenticate(cache, user, current_password)
        await ensure_no_change_in_flight(db, user.id)
        await precheck_new_value(db, user=user, field=field, value=value)
        await check_target_budget(cache, field, value)
        current = current_value(user, field)
        row = ContactChangeRequest(
            auth_user_uuid=user.id,
            kind=ContactChangeKind.STAFF_REQUEST.value,
            field=field,
            status=ContactChangeStatus.AWAITING_NEW_OTP.value,
            current_fingerprint=contact_fingerprint(field, current) if current else None,
            new_value=value,
            expires_at=_now() + timedelta(minutes=settings.CONTACT_CHANGE_FLOW_EXPIRE_MINUTES),
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError as exc:
            raise ChangeInProgress from exc
    channel, otp = await issue_code(
        cache, change_id=row.id, stage="new", field=field, destination=value
    )
    return challenge_response(
        row,
        message=f"We sent a code to the new {_noun(field)}.",
        destination=value,
        channel=channel,
        otp=otp,
    )


async def resend_staff_request(
    cache: RedisCache, *, actor: Actor, change_id: UUID, ip: str | None
) -> ContactChangeChallengeResponse:
    await check_otp_rate_ip(cache, ip)
    await check_account_budget(cache, actor.user_uuid)
    async with _bypass_session() as db:
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.STAFF_REQUEST
            or row.status != ContactChangeStatus.AWAITING_NEW_OTP
            or row.new_value is None
        ):
            raise StepConflict
        value = row.new_value
        await db.commit()
    await check_target_budget(cache, row.field, value)
    channel, otp = await issue_code(
        cache, change_id=row.id, stage="new", field=row.field, destination=value, resend=True
    )
    return challenge_response(
        row, message="We sent a new code.", destination=value, channel=channel, otp=otp
    )


async def verify_staff_request(
    cache: RedisCache, *, actor: Actor, change_id: UUID, otp: str
) -> ContactChangeChallengeResponse:
    """The new value is proven; the request now waits for one platform Admin."""
    async with _bypass_session() as db:
        await lock_user(db, actor.user_uuid)
        row = await lock_own_change(db, change_id=change_id, user_uuid=actor.user_uuid)
        if (
            row.kind != ContactChangeKind.STAFF_REQUEST
            or row.status != ContactChangeStatus.AWAITING_NEW_OTP
            or row.new_value is None
        ):
            raise StepConflict
        await verify_code(
            cache,
            change_id=row.id,
            stage="new",
            field=row.field,
            expected_value=row.new_value,
            otp=otp,
        )
        now = _now()
        row.status = ContactChangeStatus.PENDING_APPROVAL.value
        row.new_verified_at = now
        row.expires_at = now + timedelta(days=settings.CONTACT_CHANGE_REQUEST_EXPIRE_DAYS)
        await record_audit(
            db,
            action=AuditAction.CONTACT_CHANGE_REQUESTED,
            entity_type="contact_change_request",
            entity_uuid=row.id,
            actor_uuid=actor.user_uuid,
            actor_role=actor.role,
            detail={"field": row.field},
        )
        await db.commit()
    await notify_admins(
        notification_type=NotificationType.CONTACT_CHANGE_REQUESTED,
        title="Contact change request",
        body="A staff member asked to change their phone number or email.",
        href="/dashboard/support-tickets",
        exclude_user_uuid=actor.user_uuid,
    )
    return challenge_response(row, message="Request sent. An Admin will review it.")


async def _assert_platform_admin(db: AsyncSession, actor_uuid: UUID) -> None:
    """Re-check the live profile: JWT claims can outlive a deactivation."""
    admin_profile = await db.scalar(
        select(StaffProfile.id).where(
            StaffProfile.auth_user_uuid == actor_uuid,
            StaffProfile.role == StaffRole.ADMIN,
            StaffProfile.scope == ProfileScope.PLATFORM,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if admin_profile is None:
        raise NotPermitted("Only an active platform Admin may review contact changes.")


async def _reauth_admin(
    cache: RedisCache, db: AsyncSession, actor_uuid: UUID, password: str
) -> None:
    await _assert_platform_admin(db, actor_uuid)
    admin = await db.get(User, actor_uuid)
    if admin is None or admin.status != UserStatus.ACTIVE:
        raise NotPermitted("Only an active platform Admin may review contact changes.")
    await reauthenticate(cache, admin, password)


async def _staff_role(db: AsyncSession, user_uuid: UUID) -> str:
    role = await db.scalar(
        select(StaffProfile.role).where(
            StaffProfile.auth_user_uuid == user_uuid,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    return role.value if role is not None else "staff"


async def list_staff_requests(*, actor_uuid: UUID) -> list[ContactChangeAdminRead]:
    """Pending staff requests, oldest first, with the live current value."""
    async with _bypass_session() as db:
        await _assert_platform_admin(db, actor_uuid)
        await expire_stale(db)
        await db.commit()
        rows = (
            await db.scalars(
                select(ContactChangeRequest)
                .where(
                    ContactChangeRequest.kind == ContactChangeKind.STAFF_REQUEST,
                    ContactChangeRequest.status == ContactChangeStatus.PENDING_APPROVAL,
                )
                .order_by(ContactChangeRequest.created_at, ContactChangeRequest.id)
            )
        ).all()
        result: list[ContactChangeAdminRead] = []
        for row in rows:
            requester = await db.get(User, row.auth_user_uuid)
            if requester is None or row.new_value is None:
                continue
            result.append(
                ContactChangeAdminRead(
                    id=row.id,
                    auth_user_uuid=row.auth_user_uuid,
                    requester_name=f"{requester.first_name} {requester.last_name}".strip(),
                    requester_role=await _staff_role(db, requester.id),
                    field=row.field,
                    current_value=current_value(requester, row.field),
                    requested_value=row.new_value,
                    current_changed=(
                        row.current_fingerprint is not None and not _current_matches(row, requester)
                    ),
                    new_verified_at=row.new_verified_at,
                    expires_at=row.expires_at,
                    created_at=row.created_at,
                )
            )
        return result


async def _lock_pending_request(
    db: AsyncSession, request_id: UUID, actor: Actor
) -> tuple[User, ContactChangeRequest]:
    """Lock the requester's account, then the request (the one lock order)."""
    target = await db.scalar(
        select(ContactChangeRequest.auth_user_uuid).where(
            ContactChangeRequest.id == request_id,
            ContactChangeRequest.kind == ContactChangeKind.STAFF_REQUEST,
        )
    )
    if target is None:
        raise ChangeNotFound
    if target == actor.user_uuid:
        raise MakerCheckerViolation
    user = await db.scalar(
        select(User)
        .where(User.id == target)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = await db.scalar(
        select(ContactChangeRequest).where(ContactChangeRequest.id == request_id).with_for_update()
    )
    if user is None or row is None:
        raise ChangeNotFound
    if row.status in ACTIVE_CONTACT_CHANGE_STATUSES and row.expires_at <= _now():
        _terminate(row, ContactChangeStatus.EXPIRED)
        await db.commit()
        raise ChangeExpired
    if row.status != ContactChangeStatus.PENDING_APPROVAL:
        raise StepConflict
    return user, row


async def approve_staff_request(
    cache: RedisCache, *, request_id: UUID, actor: Actor, current_password: str
) -> None:
    """One platform Admin (never the requester) applies the requested change."""
    async with _bypass_session() as db:
        await _reauth_admin(cache, db, actor.user_uuid, current_password)
        user, row = await _lock_pending_request(db, request_id, actor)
        if user.status != UserStatus.ACTIVE:
            _terminate(row, ContactChangeStatus.CANCELLED)
            await db.commit()
            raise ValueUnavailable("This account is no longer active.")
        if row.current_fingerprint is not None and not _current_matches(row, user):
            _terminate(row, ContactChangeStatus.CANCELLED)
            await db.commit()
            raise ValueUnavailable(
                "Their details changed after the request. Ask them to send a new request."
            )
        applied = await apply_change(
            db,
            row=row,
            user=user,
            actor=actor,
            method=ContactChangeMethod.ADMIN_APPROVED,
            approved_by=actor.user_uuid,
        )
    await after_apply(cache, applied)


async def reject_staff_request(
    cache: RedisCache,
    *,
    request_id: UUID,
    actor: Actor,
    current_password: str,
    reason: str,
) -> None:
    """One platform Admin (never the requester) refuses with a PII-free reason."""
    async with _bypass_session() as db:
        await _reauth_admin(cache, db, actor.user_uuid, current_password)
        _, row = await _lock_pending_request(db, request_id, actor)
        _terminate(row, ContactChangeStatus.REJECTED)
        row.rejection_reason = reason
        row.decided_by_user_uuid = actor.user_uuid
        row.decided_at = _now()
        label = "phone number" if row.field == ContactField.MOBILE else "email"
        db.add(
            Notification(
                user_uuid=row.auth_user_uuid,
                type=NotificationType.CONTACT_CHANGE_REJECTED,
                title=f"Your {label} change was not approved",
                body="An Admin did not approve your contact change request. Ask your Admin why.",
                href="/dashboard/settings",
            )
        )
        await record_audit(
            db,
            action=AuditAction.CONTACT_CHANGE_REJECTED,
            entity_type="contact_change_request",
            entity_uuid=row.id,
            actor_uuid=actor.user_uuid,
            actor_role=actor.role,
            detail={"field": row.field},
        )
        await db.commit()
