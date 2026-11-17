"""Support-assisted mobile-number recovery workflow.

Public callers can prove control of a replacement number but cannot mutate an
account.  A platform Admin maker records an approved proof category and a
different platform Admin checker completes the atomic identity update.  Every
database mutation in this module runs on a bypass session only after the route
has applied the platform-Admin gate; the service repeats actor/target and
credential checks because RLS is intentionally not the authorization boundary
for cross-account recovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from jwt import PyJWTError as JWTError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import (
    TTL_MOBILE_CHANGE_OTP_DAILY,
    TTL_MOBILE_CHANGE_RATE,
    RedisCache,
    mobile_change_otp_daily_key,
    mobile_change_rate_account_key,
    mobile_change_rate_ip_key,
)
from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditAction
from app.models.auth import AuthEvent, RefreshToken
from app.models.contact_change import ContactChangeMethod, ContactField
from app.models.loan_document import LoanDocument
from app.models.mobile_change import (
    MobileChangeProof,
    MobileChangeRequest,
    MobileChangeSource,
    MobileChangeStatus,
)
from app.models.notification import Notification, NotificationType
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.push_subscription import PushSubscription
from app.models.support_ticket import SupportCategory, SupportStatus, SupportTicket
from app.models.user import User, UserStatus
from app.schemas.mobile_change import MobileChangeAdminRead, MobileChangeChallengeResponse
from app.services.audit_log import record as record_audit
from app.services.contact_change import write_history
from app.services.contact_identity import (
    clear_identity_caches,
    mobile_conflicts,
    propagate_mobile,
)
from app.services.email import send_notification_email
from app.services.notifications import emit_notification
from app.services.otp import check_otp_rate_ip, generate_and_store_otp, resend_otp, verify_otp
from app.services.otp_delivery import deliver_otp

logger = logging.getLogger(__name__)

_PURPOSE = "mobile_change"
_ACTIVE_STATUSES = (
    MobileChangeStatus.PENDING_REVIEW,
    MobileChangeStatus.PENDING_APPROVAL,
)


class InvalidChallenge(Exception):
    """The challenge is expired, malformed, or for another purpose."""


class MobileChangeRateLimited(Exception):
    """A purpose-specific initiation budget was exhausted."""


class RequestNotFound(Exception):
    """The request does not exist."""


class RequestStateConflict(Exception):
    """The request is expired/terminal or not at the required workflow step."""


class IdentityConflict(Exception):
    """Current account data makes the replacement unsafe to complete."""

    def __init__(self, conflicts: list[str]) -> None:
        super().__init__(", ".join(conflicts))
        self.conflicts = conflicts


class MakerCheckerViolation(Exception):
    """Target, maker, and checker are not three distinct identities."""


class AdminReauthenticationFailed(Exception):
    """The acting Admin did not re-enter their current password correctly."""


@dataclass(frozen=True)
class Challenge:
    current_mobile: str
    requested_mobile: str
    source: MobileChangeSource
    target_uuid: UUID | None


def _is_mock_env() -> bool:
    return settings.OTP_EXPOSE_HINT or settings.ENV == "development"


async def _check_purpose_limits(
    cache: RedisCache, *, current_mobile: str, requested_mobile: str, ip: str | None
) -> None:
    if ip:
        count = await cache.incr_with_expire(mobile_change_rate_ip_key(ip), TTL_MOBILE_CHANGE_RATE)
        if count > settings.MOBILE_CHANGE_RATE_LIMIT_PER_IP:
            raise MobileChangeRateLimited
    account_count = await cache.incr_with_expire(
        mobile_change_rate_account_key(current_mobile), TTL_MOBILE_CHANGE_RATE
    )
    if account_count > settings.MOBILE_CHANGE_RATE_LIMIT_PER_ACCOUNT:
        raise MobileChangeRateLimited
    otp_count = await cache.incr_with_expire(
        mobile_change_otp_daily_key(requested_mobile), TTL_MOBILE_CHANGE_OTP_DAILY
    )
    if otp_count > settings.MOBILE_CHANGE_OTP_DAILY_LIMIT:
        raise MobileChangeRateLimited


async def initiate(
    cache: RedisCache,
    *,
    current_mobile: str,
    requested_mobile: str,
    source: MobileChangeSource,
    target_uuid: UUID | None,
    ip: str | None,
) -> MobileChangeChallengeResponse:
    if current_mobile == requested_mobile:
        raise ValueError("replacement must differ")
    await check_otp_rate_ip(cache, ip)
    await _check_purpose_limits(
        cache,
        current_mobile=current_mobile,
        requested_mobile=requested_mobile,
        ip=ip,
    )
    otp = await generate_and_store_otp(cache, requested_mobile, _PURPOSE)
    channel = await deliver_otp(requested_mobile, "", otp, allow_email_fallback=False)
    # Deliberately no `sub` claim: this ticket must never authenticate as the
    # target account through get_current_user.
    challenge = create_access_token(
        {
            "purpose": _PURPOSE,
            "current_number": current_mobile,
            "requested_number": requested_mobile,
            "source": source.value,
            "target_uuid": str(target_uuid) if target_uuid else None,
        }
    )
    return MobileChangeChallengeResponse(
        message="Verification code sent to the replacement number.",
        challenge_token=challenge,
        delivery_channel=channel,
        otp_hint=otp if channel == "none" and _is_mock_env() else None,
    )


async def initiate_authenticated(
    cache: RedisCache,
    *,
    target_uuid: UUID,
    requested_mobile: str,
    current_password: str,
    ip: str | None,
) -> MobileChangeChallengeResponse:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, target_uuid)
        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or user.password_hash is None
            or not await verify_password(current_password, user.password_hash)
        ):
            raise AdminReauthenticationFailed
        if await _is_admin_target(db, target_uuid):
            raise IdentityConflict(["administrator_account"])
        current_mobile = user.mobile
    return await initiate(
        cache,
        current_mobile=current_mobile,
        requested_mobile=requested_mobile,
        source=MobileChangeSource.AUTHENTICATED,
        target_uuid=target_uuid,
        ip=ip,
    )


def _decode_challenge(token: str) -> Challenge:
    try:
        claims = decode_access_token(token)
        source = MobileChangeSource(claims.get("source"))
        current_mobile = claims["current_number"]
        requested_mobile = claims["requested_number"]
        target_raw = claims.get("target_uuid")
        target_uuid = UUID(target_raw) if target_raw else None
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidChallenge from exc
    if claims.get("purpose") != _PURPOSE:
        raise InvalidChallenge
    if source == MobileChangeSource.AUTHENTICATED and target_uuid is None:
        raise InvalidChallenge
    return Challenge(current_mobile, requested_mobile, source, target_uuid)


async def resend_challenge(
    cache: RedisCache, *, challenge_token: str, ip: str | None
) -> MobileChangeChallengeResponse:
    challenge = _decode_challenge(challenge_token)
    await check_otp_rate_ip(cache, ip)
    await _check_purpose_limits(
        cache,
        current_mobile=challenge.current_mobile,
        requested_mobile=challenge.requested_mobile,
        ip=ip,
    )
    otp = await resend_otp(cache, challenge.requested_mobile, _PURPOSE)
    channel = await deliver_otp(challenge.requested_mobile, "", otp, allow_email_fallback=False)
    return MobileChangeChallengeResponse(
        message="Verification code resent to the replacement number.",
        challenge_token=challenge_token,
        delivery_channel=channel,
        otp_hint=otp if channel == "none" and _is_mock_env() else None,
    )


async def verify_challenge(cache: RedisCache, *, challenge_token: str, otp: str) -> None:
    challenge = _decode_challenge(challenge_token)
    await verify_otp(cache, challenge.requested_mobile, _PURPOSE, otp)
    created_for: UUID | None = None
    try:
        async with AsyncSessionLocal() as db:
            user = await db.scalar(
                select(User).where(
                    User.mobile == challenge.current_mobile,
                    User.status == UserStatus.ACTIVE,
                )
            )
            if user is None:
                return
            if challenge.target_uuid is not None and user.id != challenge.target_uuid:
                return
            if await _is_admin_target(db, user.id):
                return
            await _expire_stale(db, target_uuid=user.id)
            active = await db.scalar(
                select(MobileChangeRequest).where(
                    MobileChangeRequest.auth_user_uuid == user.id,
                    MobileChangeRequest.status.in_(_ACTIVE_STATUSES),
                )
            )
            if active is not None:
                await db.commit()
                return

            now = datetime.now(UTC)
            ticket = SupportTicket(
                auth_user_uuid=user.id,
                category=SupportCategory.LOST_MOBILE,
                subject="Mobile number change request",
                body=(
                    "The replacement number was verified. Identity proof and "
                    "maker/checker approval are required before completion."
                ),
            )
            db.add(ticket)
            await db.flush()
            request = MobileChangeRequest(
                auth_user_uuid=user.id,
                support_ticket_uuid=ticket.id,
                source=challenge.source,
                current_mobile=challenge.current_mobile,
                requested_mobile=challenge.requested_mobile,
                requested_mobile_verified_at=now,
                expires_at=now + timedelta(days=settings.MOBILE_CHANGE_REQUEST_EXPIRE_DAYS),
            )
            db.add(request)
            db.add(
                AuthEvent(
                    auth_user_uuid=user.id,
                    event_type="mobile_change_requested",
                    mobile=None,
                    success=True,
                    detail={"source": challenge.source.value},
                )
            )
            await db.commit()
            created_for = user.id
    except IntegrityError:
        # A concurrent verify can win either active partial unique index.  The
        # public response remains indistinguishable from a created request.
        logger.info("mobile_change.concurrent_request_suppressed")
    if created_for is not None:
        await emit_notification(
            user_uuid=created_for,
            notification_type=NotificationType.MOBILE_CHANGE_REQUESTED,
            title="Mobile number change requested",
            body=(
                "A request to change your login number was created. Contact support "
                "immediately if you did not request this."
            ),
            href="/dashboard/support",
        )


async def _is_admin_target(db: AsyncSession, user_uuid: UUID) -> bool:
    return (
        await db.scalar(
            select(StaffProfile.id).where(
                StaffProfile.auth_user_uuid == user_uuid,
                StaffProfile.role == StaffRole.ADMIN,
                StaffProfile.status == ProfileStatus.ACTIVE,
            )
        )
        is not None
    )


async def _expire_stale(db: AsyncSession, *, target_uuid: UUID | None = None) -> None:
    stmt = select(MobileChangeRequest).where(
        MobileChangeRequest.status.in_(_ACTIVE_STATUSES),
        MobileChangeRequest.expires_at <= datetime.now(UTC),
    )
    if target_uuid is not None:
        stmt = stmt.where(MobileChangeRequest.auth_user_uuid == target_uuid)
    rows = (await db.scalars(stmt.with_for_update())).all()
    for request in rows:
        request.status = MobileChangeStatus.EXPIRED
        request.current_mobile = None
        request.requested_mobile = None
        ticket = await db.get(SupportTicket, request.support_ticket_uuid)
        if ticket is not None and ticket.status not in (
            SupportStatus.RESOLVED,
            SupportStatus.CLOSED,
        ):
            ticket.status = SupportStatus.CLOSED
            ticket.resolution_note = "Mobile-number change request expired."


async def _role_for_user(db: AsyncSession, user_uuid: UUID) -> str:
    staff = await db.scalar(
        select(StaffProfile.role).where(
            StaffProfile.auth_user_uuid == user_uuid,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if staff is not None:
        return staff.value
    agent = await db.scalar(
        select(AgentProfile.id).where(
            AgentProfile.auth_user_uuid == user_uuid,
            AgentProfile.status == ProfileStatus.ACTIVE,
        )
    )
    return "agent" if agent is not None else "client"


async def _conflicts(db: AsyncSession, request: MobileChangeRequest) -> list[str]:
    current_mobile = request.current_mobile
    requested_mobile = request.requested_mobile
    if current_mobile is None or requested_mobile is None:
        return ["request_data_unavailable"]
    conflicts: list[str] = []
    user = await db.get(User, request.auth_user_uuid)
    if user is None or user.status != UserStatus.ACTIVE:
        conflicts.append("account_inactive")
        return conflicts
    if await _is_admin_target(db, user.id):
        conflicts.append("administrator_account")
    if user.mobile != current_mobile:
        conflicts.append("current_number_changed")
    conflicts.extend(
        await mobile_conflicts(db, user_uuid=user.id, requested_mobile=requested_mobile)
    )
    if request.status == MobileChangeStatus.PENDING_APPROVAL and (
        request.proof_method is None
        or not await _proof_is_available(db, user.id, request.proof_method)
    ):
        conflicts.append("selected_proof_not_available")
    return conflicts


async def _assert_active_platform_admin(db: AsyncSession, actor_uuid: UUID) -> None:
    admin_profile = await db.scalar(
        select(StaffProfile.id).where(
            StaffProfile.auth_user_uuid == actor_uuid,
            StaffProfile.role == StaffRole.ADMIN,
            StaffProfile.scope == ProfileScope.PLATFORM,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if admin_profile is None:
        raise AdminReauthenticationFailed


async def _reauth_admin(db: AsyncSession, actor_uuid: UUID, password: str) -> None:
    await _assert_active_platform_admin(db, actor_uuid)
    actor = await db.get(User, actor_uuid)
    if (
        actor is None
        or actor.status != UserStatus.ACTIVE
        or actor.password_hash is None
        or not await verify_password(password, actor.password_hash)
    ):
        raise AdminReauthenticationFailed


async def list_for_admin(*, actor_uuid: UUID) -> list[MobileChangeAdminRead]:
    async with AsyncSessionLocal() as db:
        # Re-check the live profile because JWT role/scope claims may remain
        # valid briefly after an Admin is deactivated.
        await _assert_active_platform_admin(db, actor_uuid)
        await _expire_stale(db)
        await db.commit()
        rows = (
            await db.scalars(
                select(MobileChangeRequest)
                .where(MobileChangeRequest.status.in_(_ACTIVE_STATUSES))
                .order_by(MobileChangeRequest.created_at.desc(), MobileChangeRequest.id.desc())
            )
        ).all()
        result: list[MobileChangeAdminRead] = []
        for request in rows:
            target = await db.get(User, request.auth_user_uuid)
            verifier = (
                await db.get(User, request.verified_by_user_uuid)
                if request.verified_by_user_uuid
                else None
            )
            result.append(
                MobileChangeAdminRead(
                    id=request.id,
                    auth_user_uuid=request.auth_user_uuid,
                    support_ticket_uuid=request.support_ticket_uuid,
                    source=request.source,
                    status=request.status,
                    current_mobile=request.current_mobile,
                    requested_mobile=request.requested_mobile,
                    requester_name=(
                        f"{target.first_name} {target.last_name}".strip()
                        if target is not None
                        else "Deleted account"
                    ),
                    requester_role=(
                        await _role_for_user(db, target.id) if target is not None else "deleted"
                    ),
                    proof_method=request.proof_method,
                    proof_attestation=request.proof_attestation,
                    verified_by_name=(
                        f"{verifier.first_name} {verifier.last_name}".strip()
                        if verifier is not None
                        else None
                    ),
                    conflicts=(
                        await _conflicts(db, request) if request.status in _ACTIVE_STATUSES else []
                    ),
                    expires_at=request.expires_at,
                    created_at=request.created_at,
                    updated_at=request.updated_at,
                )
            )
        return result


async def verify_identity(
    request_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
    proof_method: MobileChangeProof,
    proof_attestation: str,
    current_password: str,
) -> None:
    async with AsyncSessionLocal() as db:
        await _reauth_admin(db, actor_uuid, current_password)
        request = await db.scalar(
            select(MobileChangeRequest)
            .where(MobileChangeRequest.id == request_id)
            .with_for_update()
        )
        if request is None:
            raise RequestNotFound
        await _expire_stale(db, target_uuid=request.auth_user_uuid)
        if request.status == MobileChangeStatus.EXPIRED:
            await db.commit()
            raise RequestStateConflict
        if request.status != MobileChangeStatus.PENDING_REVIEW:
            raise RequestStateConflict
        if actor_uuid == request.auth_user_uuid:
            raise MakerCheckerViolation
        conflicts = await _conflicts(db, request)
        if conflicts:
            raise IdentityConflict(conflicts)
        if not await _proof_is_available(db, request.auth_user_uuid, proof_method):
            raise IdentityConflict(["selected_proof_not_available"])
        now = datetime.now(UTC)
        request.status = MobileChangeStatus.PENDING_APPROVAL
        request.proof_method = proof_method
        request.proof_attestation = proof_attestation
        request.verified_by_user_uuid = actor_uuid
        request.verified_at = now
        ticket = await db.get(SupportTicket, request.support_ticket_uuid)
        if ticket is not None:
            ticket.status = SupportStatus.IN_PROGRESS
        await record_audit(
            db,
            action=AuditAction.MOBILE_CHANGE_VERIFIED,
            entity_type="mobile_change_request",
            entity_uuid=request.id,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            detail={
                "proof_method": proof_method.value,
                "from_status": MobileChangeStatus.PENDING_REVIEW.value,
                "to_status": MobileChangeStatus.PENDING_APPROVAL.value,
            },
        )
        await db.commit()


async def _proof_is_available(
    db: AsyncSession, target_uuid: UUID, proof_method: MobileChangeProof
) -> bool:
    if proof_method in (
        MobileChangeProof.STAFF_CONFIRMATION,
        MobileChangeProof.IN_PERSON,
    ):
        return True
    user = await db.get(User, target_uuid)
    if user is None:
        return False
    if proof_method == MobileChangeProof.VERIFIED_EMAIL:
        return user.email_verified_at is not None
    verified_agent = await db.scalar(
        select(AgentProfile.id).where(
            AgentProfile.auth_user_uuid == target_uuid,
            func.lower(AgentProfile.kyc_status) == "verified",
        )
    )
    if verified_agent is not None:
        return True
    client_profiles = select(ClientProfile.id).where(ClientProfile.auth_user_uuid == target_uuid)
    verified_document = await db.scalar(
        select(LoanDocument.id).where(
            LoanDocument.client_profile_uuid.in_(client_profiles),
            LoanDocument.verified.is_(True),
        )
    )
    return verified_document is not None


async def complete(
    request_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
    current_password: str,
    cache: RedisCache,
) -> None:
    try:
        await _complete_transaction(
            request_id,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            current_password=current_password,
            cache=cache,
        )
    except IntegrityError as exc:
        # A registration or another identity update can claim the replacement
        # after our preflight query. PostgreSQL's auth_users.mobile uniqueness
        # constraint is the final arbiter; translate that atomic rollback into
        # the same safe conflict response instead of leaking a database 500.
        raise IdentityConflict(["replacement_number_in_use"]) from exc


async def _complete_transaction(
    request_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
    current_password: str,
    cache: RedisCache,
) -> None:
    old_mobile: str | None = None
    new_mobile: str | None = None
    target_uuid: UUID | None = None
    notification_email: str | None = None
    async with AsyncSessionLocal() as db:
        await _reauth_admin(db, actor_uuid, current_password)
        request = await db.scalar(
            select(MobileChangeRequest)
            .where(MobileChangeRequest.id == request_id)
            .with_for_update()
        )
        if request is None:
            raise RequestNotFound
        await _expire_stale(db, target_uuid=request.auth_user_uuid)
        if request.status == MobileChangeStatus.EXPIRED:
            await db.commit()
            raise RequestStateConflict
        if request.status != MobileChangeStatus.PENDING_APPROVAL:
            raise RequestStateConflict
        if (
            actor_uuid == request.auth_user_uuid
            or request.verified_by_user_uuid is None
            or actor_uuid == request.verified_by_user_uuid
        ):
            raise MakerCheckerViolation
        conflicts = await _conflicts(db, request)
        if conflicts:
            raise IdentityConflict(conflicts)
        user = await db.scalar(
            select(User).where(User.id == request.auth_user_uuid).with_for_update()
        )
        if user is None or request.current_mobile is None or request.requested_mobile is None:
            raise RequestStateConflict

        now = datetime.now(UTC)
        old_mobile = request.current_mobile
        new_mobile = request.requested_mobile
        target_uuid = user.id

        user.mobile = new_mobile
        user.phone_verified_at = now
        user.session_version += 1
        await propagate_mobile(db, user_uuid=user.id, new_mobile=new_mobile)
        # CS-025: the request row still forgets both numbers below; the
        # permanent copy lives only in the platform-Admin-only history.
        write_history(
            db,
            user_uuid=user.id,
            field=ContactField.MOBILE,
            old_value=old_mobile,
            new_value=new_mobile,
            method=ContactChangeMethod.LOST_NUMBER_RECOVERY,
            request_uuid=request.id,
            approved_by=actor_uuid,
            proof_category=request.proof_method.value if request.proof_method else None,
            proof_reference=request.proof_attestation,
        )
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.auth_user_uuid == user.id,
                RefreshToken.revoked.is_(False),
            )
            .values(revoked=True)
        )
        await db.execute(delete(PushSubscription).where(PushSubscription.user_uuid == user.id))

        request.status = MobileChangeStatus.COMPLETED
        request.completed_by_user_uuid = actor_uuid
        request.completed_at = now
        request.current_mobile = None
        request.requested_mobile = None
        ticket = await db.get(SupportTicket, request.support_ticket_uuid)
        if ticket is not None:
            ticket.status = SupportStatus.RESOLVED
            ticket.resolution_note = "Mobile-number change completed after maker/checker review."
        db.add(
            Notification(
                user_uuid=user.id,
                type=NotificationType.MOBILE_CHANGED,
                title="Mobile number changed",
                body="Your login number was changed. Please sign in again on your devices.",
                href="/login",
            )
        )
        db.add(
            AuthEvent(
                auth_user_uuid=user.id,
                event_type="mobile_changed",
                mobile=None,
                success=True,
                detail={"request_id": str(request.id)},
            )
        )
        await record_audit(
            db,
            action=AuditAction.MOBILE_CHANGED,
            entity_type="mobile_change_request",
            entity_uuid=request.id,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            detail={
                "from_status": MobileChangeStatus.PENDING_APPROVAL.value,
                "to_status": MobileChangeStatus.COMPLETED.value,
            },
        )
        if user.status == UserStatus.ACTIVE and user.email and user.email_verified_at:
            notification_email = user.email
        await db.commit()

    if old_mobile and new_mobile and target_uuid:
        await clear_identity_caches(cache, old_mobile, new_mobile)
    if notification_email:
        await send_notification_email(
            notification_email,
            "Mobile number changed",
            "Your login number was changed. Please sign in again on your devices.",
            "/login",
        )


async def reject(
    request_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
    reason: str,
    current_password: str,
) -> None:
    target_uuid: UUID | None = None
    notification_email: str | None = None
    async with AsyncSessionLocal() as db:
        await _reauth_admin(db, actor_uuid, current_password)
        request = await db.scalar(
            select(MobileChangeRequest)
            .where(MobileChangeRequest.id == request_id)
            .with_for_update()
        )
        if request is None:
            raise RequestNotFound
        await _expire_stale(db, target_uuid=request.auth_user_uuid)
        if request.status == MobileChangeStatus.EXPIRED:
            await db.commit()
            raise RequestStateConflict
        if request.status not in _ACTIVE_STATUSES:
            raise RequestStateConflict
        if actor_uuid == request.auth_user_uuid:
            raise MakerCheckerViolation
        target_uuid = request.auth_user_uuid
        previous = request.status
        request.status = MobileChangeStatus.REJECTED
        request.rejected_by_user_uuid = actor_uuid
        request.rejection_reason = reason
        request.current_mobile = None
        request.requested_mobile = None
        ticket = await db.get(SupportTicket, request.support_ticket_uuid)
        if ticket is not None:
            ticket.status = SupportStatus.CLOSED
            ticket.resolution_note = "Mobile-number change request rejected."
        db.add(
            Notification(
                user_uuid=request.auth_user_uuid,
                type=NotificationType.MOBILE_CHANGE_REJECTED,
                title="Mobile number change not completed",
                body="Support could not complete your request. Contact support for next steps.",
                href="/dashboard/support",
            )
        )
        await record_audit(
            db,
            action=AuditAction.MOBILE_CHANGE_REJECTED,
            entity_type="mobile_change_request",
            entity_uuid=request.id,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            detail={
                "from_status": previous.value,
                "to_status": MobileChangeStatus.REJECTED.value,
            },
        )
        user = await db.get(User, request.auth_user_uuid)
        if user and user.status == UserStatus.ACTIVE and user.email and user.email_verified_at:
            notification_email = user.email
        await db.commit()
    if notification_email:
        await send_notification_email(
            notification_email,
            "Mobile number change not completed",
            "Support could not complete your request. Contact support for next steps.",
            "/dashboard/support",
        )
    if target_uuid is not None:
        # A terminal in-app row was inserted transactionally.  No separate push
        # is emitted here because the rejection reason is intentionally staff-only.
        logger.info("mobile_change.rejected request_id=%s", request_id)
