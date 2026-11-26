"""Lead capture — durable, best-effort persistence of every enquiring mobile.

Called only after a visitor expresses Loans or Real Estate intent. Login and
password-recovery attempts remain authentication events, not sales leads.

Design notes:
  * Runs on its OWN session (not the request session). login/forgot raise
    HTTPException on the unknown-mobile path, and get_db rolls the request session
    back — a lead written there would be discarded. An independent session commits
    regardless of the request outcome.
  * That session connects as the 'app' superuser (DATABASE_URL), which bypasses RLS,
    so the unauthenticated INSERT always succeeds — same mechanism as the existing
    unauthenticated AuthEvent insert.
  * Idempotent through a mobile advisory lock plus per-line live indexes. One
    mobile can have independent Loans and Real Estate journeys.
  * Best-effort: all errors are swallowed so capture can never break or slow-fail
    the auth response (which would also leak timing — see enumeration-safety).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.masking import mask_mobile
from app.db.session import AsyncSessionLocal
from app.models.audit_log import AuditAction
from app.models.lead import Lead, LeadAssignmentCursor, LeadOrigin, LeadStatus
from app.models.lead_intake_attempt import IntakeActorType
from app.models.loan import LoanApplication, LoanType
from app.models.notification import NotificationType
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.user import User
from app.services.audit_log import record as record_audit
from app.services.eligibility import EligibilityReason
from app.services.lead_details import initial_ownership, owner, transfer_unclaimed_to_client
from app.services.lead_intake_attempts import record_attempt as record_intake_attempt
from app.services.notifications import emit_notification

logger = logging.getLogger(__name__)

_ASSIGNABLE_STATUSES = (LeadStatus.NEW, LeadStatus.RELEASED)
_VALID_LINES = frozenset({"loans", "real_estate"})


@dataclass(frozen=True)
class LeadAssignmentNotice:
    lead_id: UUID
    telecaller_user_uuid: UUID
    business_line: str


class AgentLeadConflict(Exception):
    """The mobile is registered, cross-line, expired, assigned, or owned elsewhere.

    ``reason`` is the eligibility reason recorded for the Agent's "Not
    accepted" list (CS-024). Every reason maps to the same 409 response, so
    recording it reveals nothing the Agent is not already told.
    """

    def __init__(self, reason: EligibilityReason | None = None) -> None:
        super().__init__(reason)
        self.reason = reason


class LeadNotFound(Exception):
    """Raised when the target lead id doesn't exist."""


class LeadAlreadyAssigned(Exception):
    """Raised when the lead already has a telecaller."""


class LeadHasNoBusinessLine(Exception):
    """Raised when the lead's line has not been resolved."""


class LeadNotAssignable(Exception):
    """Raised when the lead isn't in an assignable status (new/released). Guards
    against the orphaned-FK edge case: a lead whose assigned_telecaller_profile_uuid
    went NULL via ondelete="SET NULL" (e.g. the telecaller's staff profile was
    removed) while status stayed assigned/working/converted/closed must NOT be
    re-assignable via this path — that would silently rewind a forward-only
    lifecycle back to 'assigned'."""


class LeadNotReleasable(Exception):
    """Raised when the lead isn't in a releasable status (assigned/working).

    Deliberately does NOT require assigned_telecaller_profile_uuid to be set —
    unlike LeadNotAssignable's guard (which stops a forward-only lifecycle from
    rewinding through an orphaned FK), an assigned/working lead whose FK already
    went NULL (ondelete="SET NULL", the telecaller's staff profile was removed)
    is exactly the case release_lead_from_telecaller exists to repair: releasing
    it (no target) flips it to RELEASED and re-surfaces it in
    list_unassigned_leads for a normal assign.
    """


class InvalidTelecaller(Exception):
    """Raised when the target staff profile isn't an active telecaller on the lead's line."""


async def lock_lead_mobile(db: AsyncSession, mobile: str) -> None:
    """Serialize identity/lead decisions for one mobile across registration and Agents."""
    await db.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(mobile, 0))))


async def _has_active_operational_identity(db: AsyncSession, mobile: str) -> bool:
    """Active staff and Agents are identities, never customer sales leads."""
    user_id = await db.scalar(select(User.id).where(User.mobile == mobile).limit(1))
    if user_id is None:
        return False
    staff_id = await db.scalar(
        select(StaffProfile.id)
        .where(
            StaffProfile.auth_user_uuid == user_id,
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
        .limit(1)
    )
    if staff_id is not None:
        return True
    return (
        await db.scalar(
            select(AgentProfile.id)
            .where(
                AgentProfile.auth_user_uuid == user_id,
                AgentProfile.status == ProfileStatus.ACTIVE,
            )
            .limit(1)
        )
        is not None
    )


def customer_lead_predicates():  # noqa: ANN201
    """Defense-in-depth filters for historical operational-identity rows."""
    staff_user = aliased(User)
    staff_profile = aliased(StaffProfile)
    agent_user = aliased(User)
    agent_profile = aliased(AgentProfile)
    active_staff = (
        select(staff_profile.id)
        .join(staff_user, staff_user.id == staff_profile.auth_user_uuid)
        .where(
            staff_user.mobile == Lead.mobile,
            staff_profile.status == ProfileStatus.ACTIVE,
        )
        .correlate(Lead)
        .exists()
    )
    active_agent = (
        select(agent_profile.id)
        .join(agent_user, agent_user.id == agent_profile.auth_user_uuid)
        .where(
            agent_user.mobile == Lead.mobile,
            agent_profile.status == ProfileStatus.ACTIVE,
        )
        .correlate(Lead)
        .exists()
    )
    return (~active_staff, ~active_agent)


def lead_number_predicates(lead_number: int | None) -> tuple[Any, ...]:
    """An exact lead-reference match added to an already-scoped query.

    It only ever narrows: the caller's role filters and RLS still apply, so
    a reference outside the caller's reach matches nothing.
    """
    return () if lead_number is None else (Lead.lead_number == lead_number,)


async def _lock_assignment_line(db: AsyncSession, business_line: str) -> None:
    await db.scalar(
        select(
            func.pg_advisory_xact_lock(func.hashtextextended(f"lead-assignment:{business_line}", 0))
        )
    )


async def lock_assignment_lines(db: AsyncSession, business_lines: set[str]) -> None:
    """Acquire automatic-assignment locks in one canonical order."""
    for business_line in sorted(business_lines & _VALID_LINES):
        await _lock_assignment_line(db, business_line)


async def _select_round_robin_telecaller(
    db: AsyncSession, business_line: str, product_id: UUID | None = None
) -> StaffProfile | None:
    """Select and advance one durable same-line rotation turn.

    The caller holds the per-line advisory lock. The cursor and lead mutation
    therefore commit or roll back together, so concurrent capture and retry
    paths cannot consume the same turn or advance without an assignment.
    """
    telecallers = list(
        (
            await db.scalars(
                select(StaffProfile)
                .join(User, User.id == StaffProfile.auth_user_uuid)
                .where(
                    StaffProfile.role == StaffRole.TELECALLER,
                    StaffProfile.status == ProfileStatus.ACTIVE,
                    StaffProfile.business_line.in_((business_line, "both")),
                    User.status.not_in(("soft_deleted", "suspended")),
                )
                .order_by(StaffProfile.created_at, StaffProfile.id)
                .with_for_update(of=StaffProfile)
            )
        ).all()
    )
    if not telecallers:
        return None

    pool = "all"
    if business_line == "loans" and product_id is not None:
        specialists = [tc for tc in telecallers if tc.loan_specialty_id == product_id]
        unspecialised = [tc for tc in telecallers if tc.loan_specialty_id is None]
        if specialists:
            telecallers, pool = specialists, f"product:{product_id}"
        elif unspecialised:
            telecallers, pool = unspecialised, "unspecialised"

    cursor = await db.scalar(
        select(LeadAssignmentCursor)
        .where(
            LeadAssignmentCursor.business_line == business_line, LeadAssignmentCursor.pool == pool
        )
        .with_for_update()
    )
    if cursor is None:
        cursor = LeadAssignmentCursor(business_line=business_line, pool=pool)
        db.add(cursor)

    selected = telecallers[0]
    if cursor.last_telecaller_profile_uuid is not None:
        last_profile = await db.get(StaffProfile, cursor.last_telecaller_profile_uuid)
        if last_profile is not None:
            last_key = (last_profile.created_at, last_profile.id)
            selected = next(
                (
                    telecaller
                    for telecaller in telecallers
                    if (telecaller.created_at, telecaller.id) > last_key
                ),
                telecallers[0],
            )

    cursor.last_telecaller_profile_uuid = selected.id
    cursor.updated_at = datetime.now(UTC)
    return selected


async def _routing_product_id(db: AsyncSession, lead: Lead, product_id: UUID | None) -> UUID | None:
    """Resolve active lending products only; ambiguous or unknown hints use all staff."""
    if lead.business_line != "loans":
        return None
    stmt = select(LoanType.id).where(LoanType.active.is_(True), LoanType.category == "loan")
    requirement = lead.requirement or {}
    if product_id is not None:
        stmt = stmt.where(LoanType.id == product_id)
    elif isinstance(requirement.get("product_slug"), str):
        stmt = stmt.where(LoanType.name == requirement["product_slug"])
    elif isinstance(requirement.get("product"), str):
        stmt = stmt.where(func.lower(LoanType.label) == requirement["product"].strip().lower())
    else:
        stmt = (
            stmt.join(LoanApplication, LoanApplication.loan_type_id == LoanType.id)
            .where(LoanApplication.lead_uuid == lead.id)
            .distinct()
        )
    matches = list(await db.scalars(stmt.limit(2)))
    return matches[0] if len(matches) == 1 else None


async def auto_assign_locked_lead(
    db: AsyncSession, lead: Lead, *, product_id: UUID | None = None
) -> LeadAssignmentNotice | None:
    """Assign one caller-owned locked lead without committing or notifying."""
    if (
        lead.assigned_telecaller_profile_uuid is not None
        or lead.business_line not in _VALID_LINES
        or lead.status not in _ASSIGNABLE_STATUSES
    ):
        return None

    await _lock_assignment_line(db, lead.business_line)
    product_id = await _routing_product_id(db, lead, product_id)
    telecaller = await _select_round_robin_telecaller(db, lead.business_line, product_id)
    if telecaller is None:
        return None

    lead.assigned_telecaller_profile_uuid = telecaller.id
    lead.status = LeadStatus.ASSIGNED
    lead.updated_at = datetime.now(UTC)
    await record_audit(
        db,
        action=AuditAction.LEAD_ASSIGNED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=None,
        actor_role=None,
        business_line=lead.business_line,
        detail={
            "mode": "automatic",
            "telecaller_staff_profile_uuid": str(telecaller.id),
        },
    )
    await db.flush()
    return LeadAssignmentNotice(
        lead_id=lead.id,
        telecaller_user_uuid=telecaller.auth_user_uuid,
        business_line=lead.business_line,
    )


async def sticky_assign_locked_lead(db: AsyncSession, lead: Lead) -> LeadAssignmentNotice | None:
    """Give a caller-owned locked lead back to its last Telecaller (CS-028).

    Applies only to an unassigned, assignable lead whose
    ``last_telecaller_profile_uuid`` is still an ACTIVE Telecaller on the
    lead's line (or both lines). The round-robin cursor is neither read nor
    advanced, so the per-line assignment lock is not needed; the Telecaller
    row is share-locked so a concurrent deactivation waits for this
    transaction (the assignment-scope trigger re-checks it anyway). Returns
    None when the lead does not qualify, so the caller can fall back to
    ``auto_assign_locked_lead``. Never commits or notifies.
    """
    if (
        lead.assigned_telecaller_profile_uuid is not None
        or lead.last_telecaller_profile_uuid is None
        or lead.business_line not in _VALID_LINES
        or lead.status not in _ASSIGNABLE_STATUSES
    ):
        return None
    telecaller = await db.scalar(
        select(StaffProfile)
        .where(
            StaffProfile.id == lead.last_telecaller_profile_uuid,
            StaffProfile.role == StaffRole.TELECALLER,
            StaffProfile.status == ProfileStatus.ACTIVE,
            StaffProfile.business_line.in_((lead.business_line, "both")),
        )
        .with_for_update(read=True)
    )
    if telecaller is None:
        return None

    lead.assigned_telecaller_profile_uuid = telecaller.id
    lead.status = LeadStatus.ASSIGNED
    lead.updated_at = datetime.now(UTC)
    await record_audit(
        db,
        action=AuditAction.LEAD_ASSIGNED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=None,
        actor_role=None,
        business_line=lead.business_line,
        detail={
            "mode": "sticky_resubmit",
            "telecaller_staff_profile_uuid": str(telecaller.id),
        },
    )
    await db.flush()
    return LeadAssignmentNotice(
        lead_id=lead.id,
        telecaller_user_uuid=telecaller.auth_user_uuid,
        business_line=lead.business_line,
    )


async def notify_lead_assignments(notices: list[LeadAssignmentNotice]) -> None:
    for notice in notices:
        await emit_notification(
            user_uuid=notice.telecaller_user_uuid,
            notification_type=NotificationType.LEAD_ASSIGNED,
            title="New lead assigned",
            body=f"A new {notice.business_line} lead has been assigned to you.",
            href="/dashboard/leads",
        )


async def has_expired_agent_lead(mobile: str) -> bool:
    """Return whether this mobile has ended Agent ownership history.

    Agent RLS exposes only the current Agent's rows, while the no-clock-reset
    rule applies across Agents and business lines. A reached deadline counts
    even before the scheduler stamps the transition marker. The database
    trigger is the race-safe guard; this bypass-session read lets the Agent API
    surface the normal conflict as 409.
    """
    async with AsyncSessionLocal() as session:
        return (
            await session.scalar(
                select(Lead.id)
                .where(
                    Lead.mobile == mobile,
                    or_(
                        Lead.agent_expired_at.is_not(None),
                        and_(Lead.expires_at.is_not(None), Lead.expires_at <= func.now()),
                    ),
                )
                .limit(1)
            )
        ) is not None


async def capture_lead(
    mobile: str,
    *,
    name: str | None = None,
    business_line: str,
    origin: str = "direct",
    origin_agent_profile_uuid: str | None = None,
    requirement: dict[str, Any] | None = None,
) -> bool:
    """Insert-or-enrich a direct lead for this mobile. Never raises.

    Returns True when the write committed, False when it was swallowed — auth
    callers ignore this (capture must never break the auth flow); the public
    leads endpoint logs on False but still answers 202 (the visitor can do
    nothing useful with a storage error, and the failure is already logged
    with a traceback here for ops).
    """
    notice: LeadAssignmentNotice | None = None
    try:
        async with AsyncSessionLocal() as session:
            if business_line not in _VALID_LINES:
                raise ValueError("Operational leads require a supported business line.")
            if origin_agent_profile_uuid is not None or origin != LeadOrigin.DIRECT.value:
                raise ValueError("Agent lead capture must use capture_agent_lead().")

            _, notice = await stage_direct_lead(
                session, mobile, name=name, business_line=business_line, requirement=requirement
            )
            await session.commit()
        if notice is not None:
            await notify_lead_assignments([notice])
        return True
    except Exception:  # capture is best-effort; never break the auth flow
        logger.warning("lead.capture_failed mobile=%s", mask_mobile(mobile), exc_info=True)
        return False


async def stage_direct_lead(
    session: AsyncSession,
    mobile: str,
    *,
    name: str | None,
    business_line: str,
    requirement: dict[str, Any] | None,
) -> tuple[Lead | None, LeadAssignmentNotice | None]:
    """Stage lead assignment in the caller's transaction."""
    await lock_lead_mobile(session, mobile)
    if await _has_active_operational_identity(session, mobile):
        return None, None
    await _lock_assignment_line(session, business_line)
    live = Lead.status != LeadStatus.CLOSED
    candidate = await session.scalar(
        select(Lead)
        .where(
            Lead.mobile == mobile,
            live,
            Lead.business_line == business_line,
        )
        .order_by(Lead.updated_at.desc(), Lead.id)
        .limit(1)
        .with_for_update()
    )

    if candidate is None:
        candidate = Lead(
            mobile=mobile,
            name=name,
            business_line=business_line,
            origin=LeadOrigin.DIRECT,
            status=LeadStatus.NEW,
            requirement=requirement,
            detail_ownership=initial_ownership(
                name=name,
                requirement=requirement,
                creator_role="unclaimed",
            ),
        )
        session.add(candidate)
    else:
        # Public/auth capture must never rewrite an assigned workflow.
        # It may enrich only an open, unassigned enquiry.
        if (
            candidate.assigned_telecaller_profile_uuid is None
            and candidate.status in _ASSIGNABLE_STATUSES
        ):
            additions = initial_ownership(
                name=name,
                requirement=requirement,
                creator_role="unclaimed",
            )
            ownership = dict(candidate.detail_ownership or {})
            name_owner = ownership.get("name")
            if name is not None and (
                name_owner is None
                or (isinstance(name_owner, dict) and name_owner.get("role") == "unclaimed")
            ):
                candidate.name = name
                ownership.setdefault("name", additions["name"])

            merged_requirement = dict(candidate.requirement or {})
            for key, value in (requirement or {}).items():
                path = f"requirement.{key}"
                descriptor = ownership.get(path)
                if descriptor is not None and not (
                    isinstance(descriptor, dict) and descriptor.get("role") == "unclaimed"
                ):
                    continue
                merged_requirement[key] = value
                ownership.setdefault(path, additions[path])
            if requirement is not None:
                candidate.requirement = merged_requirement
            candidate.detail_ownership = ownership
        candidate.updated_at = datetime.now(UTC)
    await session.flush()
    notice = await auto_assign_locked_lead(session, candidate)
    return candidate, notice


async def _record_agent_attempt(
    mobile: str, business_line: str, agent_profile_uuid: UUID, reason: EligibilityReason
) -> None:
    await record_intake_attempt(
        actor_type=IntakeActorType.AGENT,
        actor_uuid=agent_profile_uuid,
        mobile=mobile,
        business_line=business_line,
        reason=reason,
    )


async def capture_agent_lead(
    *,
    mobile: str,
    name: str,
    business_line: str,
    agent_profile_uuid: UUID,
    requirement: dict[str, Any] | None,
) -> Lead:
    """Create/claim and automatically assign an Agent lead in one transaction."""
    lead, _outcome = await capture_agent_lead_with_outcome(
        mobile=mobile,
        name=name,
        business_line=business_line,
        agent_profile_uuid=agent_profile_uuid,
        requirement=requirement,
    )
    return lead


# ``created``: a new lead row; ``claimed``: an open unclaimed enquiry for the
# number became this Agent's; ``existing``: the number was already this
# Agent's live lead (an idempotent retry).
AgentCaptureOutcome = Literal["created", "claimed", "existing"]


async def capture_agent_lead_with_outcome(
    *,
    mobile: str,
    name: str,
    business_line: str,
    agent_profile_uuid: UUID,
    requirement: dict[str, Any] | None,
) -> tuple[Lead, AgentCaptureOutcome]:
    """``capture_agent_lead`` plus which of the three branches it took."""
    if business_line not in _VALID_LINES:
        raise AgentLeadConflict

    notice: LeadAssignmentNotice | None = None
    outcome: AgentCaptureOutcome = "created"
    try:
        async with AsyncSessionLocal() as session:
            await lock_lead_mobile(session, mobile)
            await _lock_assignment_line(session, business_line)
            if await session.scalar(select(User.id).where(User.mobile == mobile).limit(1)):
                raise AgentLeadConflict(EligibilityReason.ALREADY_LINKED)
            expired_owners = set(
                (
                    await session.scalars(
                        select(Lead.origin_agent_profile_uuid).where(
                            Lead.mobile == mobile,
                            or_(
                                Lead.agent_expired_at.is_not(None),
                                and_(Lead.expires_at.is_not(None), Lead.expires_at <= func.now()),
                            ),
                        )
                    )
                ).all()
            )
            if expired_owners:
                # Only a number this Agent introduced themselves reads as
                # "your window ended"; anyone else's history stays a duplicate.
                raise AgentLeadConflict(
                    EligibilityReason.OWN_LEAD_WINDOW_ENDED
                    if expired_owners == {agent_profile_uuid}
                    else EligibilityReason.ALREADY_LINKED
                )

            existing = list(
                (
                    await session.scalars(
                        select(Lead)
                        .where(Lead.mobile == mobile, Lead.status != LeadStatus.CLOSED)
                        .order_by(Lead.updated_at.desc(), Lead.id)
                        .with_for_update()
                    )
                ).all()
            )
            if any(
                row.business_line != business_line
                or (
                    row.origin_agent_profile_uuid is not None
                    and row.origin_agent_profile_uuid != agent_profile_uuid
                )
                for row in existing
            ):
                raise AgentLeadConflict(EligibilityReason.ALREADY_LINKED)

            lead = next(
                (row for row in existing if row.business_line == business_line),
                None,
            )
            if lead is None:
                lead = Lead(
                    mobile=mobile,
                    business_line=business_line,
                    origin=LeadOrigin.AGENT,
                    origin_agent_profile_uuid=agent_profile_uuid,
                    name=name,
                    requirement=requirement,
                    status=LeadStatus.NEW,
                    expires_at=datetime.now(UTC) + timedelta(days=settings.AGENT_LEAD_EXPIRY_DAYS),
                    detail_ownership=initial_ownership(
                        name=name,
                        requirement=requirement,
                        creator_role="agent",
                        creator_subject_uuid=agent_profile_uuid,
                    ),
                )
                session.add(lead)
                await session.flush()
            elif lead.origin_agent_profile_uuid == agent_profile_uuid:
                outcome = "existing"
                # An Agent retry is idempotent. Once assignment locks the lead,
                # do not allow the retry body to rewrite it.
                if (
                    lead.assigned_telecaller_profile_uuid is None
                    and lead.status in _ASSIGNABLE_STATUSES
                ):
                    ownership = dict(lead.detail_ownership or {})
                    name_owner = ownership.get("name")
                    agent_subject = str(agent_profile_uuid)
                    if name is not None and (
                        name_owner is None
                        or (
                            isinstance(name_owner, dict)
                            and name_owner.get("role") == "agent"
                            and name_owner.get("subject_uuid") == agent_subject
                        )
                    ):
                        lead.name = name
                        ownership.setdefault("name", owner("agent", agent_profile_uuid))
                    additions = initial_ownership(
                        name=name,
                        requirement=requirement,
                        creator_role="agent",
                        creator_subject_uuid=agent_profile_uuid,
                    )
                    merged_requirement = dict(lead.requirement or {})
                    for key, value in (requirement or {}).items():
                        path = f"requirement.{key}"
                        descriptor = ownership.get(path)
                        if descriptor is not None and not (
                            isinstance(descriptor, dict)
                            and descriptor.get("role") == "agent"
                            and descriptor.get("subject_uuid") == agent_subject
                        ):
                            continue
                        merged_requirement[key] = value
                        ownership.setdefault(path, additions[path])
                    if requirement is not None:
                        lead.requirement = merged_requirement
                    lead.detail_ownership = ownership
            else:
                if (
                    lead.assigned_telecaller_profile_uuid is not None
                    or lead.status not in _ASSIGNABLE_STATUSES
                ):
                    raise AgentLeadConflict(EligibilityReason.ALREADY_LINKED)
                outcome = "claimed"
                lead.business_line = business_line
                lead.origin = LeadOrigin.AGENT
                lead.origin_agent_profile_uuid = agent_profile_uuid
                lead.expires_at = datetime.now(UTC) + timedelta(
                    days=settings.AGENT_LEAD_EXPIRY_DAYS
                )
                additions = initial_ownership(
                    name=name,
                    requirement=requirement,
                    creator_role="agent",
                    creator_subject_uuid=agent_profile_uuid,
                )
                ownership = dict(lead.detail_ownership or {})
                name_owner = ownership.get("name")
                if name is not None and (
                    name_owner is None
                    or (isinstance(name_owner, dict) and name_owner.get("role") == "unclaimed")
                ):
                    lead.name = name
                    ownership["name"] = additions["name"]

                merged_requirement = dict(lead.requirement or {})
                for key, value in (requirement or {}).items():
                    path = f"requirement.{key}"
                    descriptor = ownership.get(path)
                    if descriptor is not None and not (
                        isinstance(descriptor, dict) and descriptor.get("role") == "unclaimed"
                    ):
                        continue
                    merged_requirement[key] = value
                    ownership[path] = additions[path]
                if requirement is not None:
                    lead.requirement = merged_requirement
                lead.detail_ownership = ownership

            notice = await auto_assign_locked_lead(session, lead)
            await session.commit()
    except AgentLeadConflict as exc:
        # The capture session has already rolled back; the attempt is
        # committed on its own session so it outlives the rejection.
        if exc.reason is not None:
            await _record_agent_attempt(mobile, business_line, agent_profile_uuid, exc.reason)
        raise
    except IntegrityError as exc:
        await _record_agent_attempt(
            mobile, business_line, agent_profile_uuid, EligibilityReason.ALREADY_LINKED
        )
        raise AgentLeadConflict(EligibilityReason.ALREADY_LINKED) from exc

    if notice is not None:
        await notify_lead_assignments([notice])
    return lead, outcome


class AgentLeadNotResubmittable(Exception):
    """The lead is not this Agent's expired, unregistered, open lead."""


# Transaction-local opt-in read by enforce_agent_lead_expiry_immutable. The
# trigger still re-checks every resubmission condition itself.
_RESUBMIT_FLAG_SQL = text("SELECT set_config('app.agent_lead_resubmit', 'on', true)")


def is_agent_lead_resubmittable(lead: Lead) -> bool:
    """Whether the originating Agent may restart this lead's window.

    2026-11-14 amendment to FR-4.6: after expiry, only the Agent who
    introduced the lead may resubmit it, and only while the client has not
    registered and the lead is neither converted nor closed. The service also
    rejects a mobile that now belongs to any account or has another live
    Agent-attributed lead.
    """
    return (
        lead.origin_agent_profile_uuid is not None
        and lead.agent_expired_at is not None
        and lead.client_profile_uuid is None
        and lead.status not in (LeadStatus.CONVERTED, LeadStatus.CLOSED)
    )


async def resubmit_agent_lead(
    *,
    lead_id: UUID,
    agent_profile_uuid: UUID,
    actor_auth_user_uuid: UUID,
) -> None:
    """Give the originating Agent a fresh window on their expired lead.

    Runs on the owner session like capture_agent_lead: the post-update row may
    be assigned to a Telecaller, which the Agent's RLS WITH CHECK forbids. All
    ownership and state checks happen here under the mobile advisory lock and
    a row lock, and the database trigger enforces them again.

    The operational status and any current Telecaller assignment are kept, so
    a Telecaller already working the lead is not interrupted. An unassigned
    lead goes back to the Telecaller who last held it when they are still
    eligible (CS-028, ``sticky_assign_locked_lead``, cursor untouched) and is
    otherwise offered to round-robin automatic assignment again.
    """
    notice: LeadAssignmentNotice | None = None
    try:
        async with AsyncSessionLocal() as session:
            mobile = await session.scalar(
                select(Lead.mobile).where(
                    Lead.id == lead_id,
                    Lead.origin_agent_profile_uuid == agent_profile_uuid,
                )
            )
            if mobile is None:
                raise AgentLeadNotResubmittable
            await lock_lead_mobile(session, mobile)
            lead = await session.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
            if (
                lead is None
                or lead.origin_agent_profile_uuid != agent_profile_uuid
                or lead.mobile != mobile
                or not is_agent_lead_resubmittable(lead)
            ):
                raise AgentLeadNotResubmittable
            if await session.scalar(select(User.id).where(User.mobile == mobile).limit(1)):
                raise AgentLeadNotResubmittable
            if await session.scalar(
                select(Lead.id)
                .where(
                    Lead.mobile == mobile,
                    Lead.id != lead.id,
                    Lead.origin_agent_profile_uuid.is_not(None),
                    Lead.agent_expired_at.is_(None),
                    Lead.status != LeadStatus.CLOSED,
                )
                .limit(1)
            ):
                raise AgentLeadNotResubmittable

            previous_expired_at = lead.agent_expired_at
            now = datetime.now(UTC)
            await session.execute(_RESUBMIT_FLAG_SQL)
            lead.expires_at = now + timedelta(days=settings.AGENT_LEAD_EXPIRY_DAYS)
            lead.agent_expired_at = None
            lead.expiry_reminder_sent_at = None
            lead.resubmit_count = lead.resubmit_count + 1
            lead.last_resubmitted_at = now
            lead.updated_at = now
            await session.flush()
            await record_audit(
                session,
                action=AuditAction.AGENT_LEAD_RESUBMITTED,
                entity_type="lead",
                entity_uuid=lead.id,
                actor_uuid=actor_auth_user_uuid,
                actor_role="agent",
                business_line=lead.business_line,
                detail={
                    "resubmit_count": lead.resubmit_count,
                    "previous_expired_at": (
                        previous_expired_at.isoformat() if previous_expired_at else None
                    ),
                },
            )
            notice = await sticky_assign_locked_lead(session, lead)
            if notice is None:
                notice = await auto_assign_locked_lead(session, lead)
            await session.commit()
    except AgentLeadNotResubmittable:
        raise
    except (IntegrityError, DBAPIError) as exc:
        raise AgentLeadNotResubmittable from exc

    if notice is not None:
        await notify_lead_assignments([notice])


async def _ensure_client_line_lead(
    db: AsyncSession,
    *,
    mobile: str,
    business_line: str,
    client_profile_uuid: UUID,
    name: str | None = None,
    product_id: UUID | None = None,
) -> tuple[Lead, LeadAssignmentNotice | None]:
    if business_line not in _VALID_LINES:
        raise ValueError("Unsupported Client journey line.")

    await _lock_assignment_line(db, business_line)
    lead = await db.scalar(
        select(Lead)
        .where(
            Lead.mobile == mobile,
            Lead.business_line == business_line,
            Lead.status != LeadStatus.CLOSED,
        )
        .order_by(Lead.updated_at.desc(), Lead.id)
        .limit(1)
        .with_for_update()
    )
    if lead is None:
        lead = Lead(
            mobile=mobile,
            business_line=business_line,
            client_profile_uuid=client_profile_uuid,
            origin=LeadOrigin.DIRECT,
            status=LeadStatus.NEW,
            name=name,
            detail_ownership=initial_ownership(
                name=name,
                requirement=None,
                creator_role="client",
                creator_subject_uuid=client_profile_uuid,
            ),
        )
        db.add(lead)
        await db.flush()
    else:
        if lead.client_profile_uuid not in (None, client_profile_uuid):
            raise ValueError("Lead is already claimed by a different Client profile.")
        lead.client_profile_uuid = client_profile_uuid
        transfer_unclaimed_to_client(lead, client_profile_uuid)
        if lead.name is None and name is not None:
            lead.name = name
            ownership = dict(lead.detail_ownership or {})
            ownership.setdefault("name", owner("client", client_profile_uuid))
            lead.detail_ownership = ownership
        lead.updated_at = datetime.now(UTC)

    return lead, await auto_assign_locked_lead(db, lead, product_id=product_id)


async def bind_registered_client_leads(
    db: AsyncSession,
    *,
    mobile: str,
    profiles_by_line: dict[str, UUID],
    requested_lines: set[str],
    name: str,
) -> list[LeadAssignmentNotice]:
    """Bind OTP-proven ownership and assign requested plus Agent-attributed lines."""
    await lock_lead_mobile(db, mobile)
    agent_lines = set(
        (
            await db.scalars(
                select(Lead.business_line).where(
                    Lead.mobile == mobile,
                    Lead.origin_agent_profile_uuid.is_not(None),
                    Lead.agent_expired_at.is_(None),
                    Lead.status != LeadStatus.CLOSED,
                    Lead.business_line.in_(_VALID_LINES),
                )
            )
        ).all()
    )
    lines = (requested_lines & _VALID_LINES) | agent_lines
    notices: list[LeadAssignmentNotice] = []
    for line in sorted(lines):
        profile_uuid = profiles_by_line.get(line)
        if profile_uuid is None:
            raise ValueError("The verified account has no profile for the requested line.")
        _lead, notice = await _ensure_client_line_lead(
            db,
            mobile=mobile,
            business_line=line,
            client_profile_uuid=profile_uuid,
            name=name,
        )
        if notice is not None:
            notices.append(notice)
    return notices


async def ensure_client_line_lead(
    *, mobile: str, client_profile_uuid: UUID, business_line: str, product_id: UUID | None = None
) -> UUID:
    """Hard-require one claimed Client journey and retry automatic assignment."""
    notice: LeadAssignmentNotice | None
    async with AsyncSessionLocal() as session:
        await lock_lead_mobile(session, mobile)
        profile = await session.get(ClientProfile, client_profile_uuid)
        if (
            profile is None
            or profile.business_line != business_line
            or profile.status != ProfileStatus.ACTIVE
        ):
            raise ValueError("Client profile does not match the requested journey line.")
        lead, notice = await _ensure_client_line_lead(
            session,
            mobile=mobile,
            business_line=business_line,
            client_profile_uuid=client_profile_uuid,
            product_id=product_id,
        )
        await session.commit()
    if notice is not None:
        await notify_lead_assignments([notice])
    return lead.id


async def ensure_client_line_lead_for_user(
    *, auth_user_uuid: UUID, mobile: str, business_line: str
) -> UUID:
    """Resolve the user's same-line profile, then create/assign that journey."""
    async with AsyncSessionLocal() as session:
        profile_uuid = await session.scalar(
            select(ClientProfile.id).where(
                ClientProfile.auth_user_uuid == auth_user_uuid,
                ClientProfile.business_line == business_line,
                ClientProfile.status == ProfileStatus.ACTIVE,
            )
        )
    if profile_uuid is None:
        raise ValueError("Client profile does not match the requested journey line.")
    return await ensure_client_line_lead(
        mobile=mobile,
        client_profile_uuid=profile_uuid,
        business_line=business_line,
    )


async def resolve_loans_lead(
    mobile: str, client_profile_uuid: UUID, *, product_id: UUID | None = None
) -> UUID:
    return await ensure_client_line_lead(
        mobile=mobile,
        client_profile_uuid=client_profile_uuid,
        business_line="loans",
        product_id=product_id,
    )


async def resolve_realestate_client_profile(mobile: str) -> UUID | None:
    """Find the mobile's real-estate ClientProfile and backfill it onto any
    unclaimed lead for that mobile. Returns None if the mobile isn't a
    registered active real-estate client.

    Unlike resolve_loans_lead (called by the client's OWN request, which
    already knows its client_profile_uuid from the JWT), a telecaller opening
    a property deal only has a Lead row in hand — Lead.client_profile_uuid is
    nullable and, for real-estate leads, never populated by capture_lead. This
    looks the client up by mobile instead, then idempotently claims the lead
    (COALESCE-style: only fills a NULL client_profile_uuid, never overwrites
    one someone else already claimed).

    Runs on the bypass superuser session: the telecaller's own request-scoped
    session cannot see auth_users/client_profiles across RLS, and the
    not-yet-claimed lead itself may be invisible under leads_rls's client
    branch until client_profile_uuid is set.
    """
    async with AsyncSessionLocal() as session:
        client_profile_id = await session.scalar(
            select(ClientProfile.id)
            .join(User, User.id == ClientProfile.auth_user_uuid)
            .where(
                User.mobile == mobile,
                ClientProfile.business_line == "real_estate",
                ClientProfile.status == ProfileStatus.ACTIVE,
            )
        )
        if client_profile_id is None:
            return None
        await session.execute(
            update(Lead)
            .where(
                Lead.mobile == mobile,
                Lead.business_line == "real_estate",
                Lead.client_profile_uuid.is_(None),
            )
            .values(client_profile_uuid=client_profile_id)
        )
        await session.commit()
        return client_profile_id


async def assign_lead_to_telecaller(
    db: AsyncSession,
    lead_id: UUID,
    telecaller_staff_profile_uuid: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> Lead:
    """Assign an unassigned lead to a telecaller. Admin-only (core.deps.require_admin).

    Runs on the admin's own request session: their JWT carries platform_scope="true",
    which leads_rls's platform bypass branch accepts, so no bypass superuser session
    is needed (same reasoning services.admin.create_staff already documents). Sends
    a best-effort notification to the telecaller (emit_notification swallows its own
    errors, so a failed notification never blocks the assignment).
    """
    lead = await db.get(Lead, lead_id, with_for_update=True)
    if lead is None:
        raise LeadNotFound
    if lead.assigned_telecaller_profile_uuid is not None:
        raise LeadAlreadyAssigned
    if lead.business_line is None:
        raise LeadHasNoBusinessLine
    if lead.status not in (LeadStatus.NEW, LeadStatus.RELEASED):
        raise LeadNotAssignable

    telecaller = await db.get(StaffProfile, telecaller_staff_profile_uuid)
    if (
        telecaller is None
        or telecaller.role != StaffRole.TELECALLER
        or telecaller.status != ProfileStatus.ACTIVE
        or telecaller.business_line not in (lead.business_line, "both")
    ):
        raise InvalidTelecaller

    lead.assigned_telecaller_profile_uuid = telecaller.id
    lead.status = LeadStatus.ASSIGNED
    await record_audit(
        db,
        action=AuditAction.LEAD_ASSIGNED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=lead.business_line,
        detail={
            "mode": "manual",
            "telecaller_staff_profile_uuid": str(telecaller.id),
        },
    )
    await db.commit()
    await db.refresh(lead)

    await emit_notification(
        user_uuid=telecaller.auth_user_uuid,
        notification_type=NotificationType.LEAD_ASSIGNED,
        title="New lead assigned",
        body=f"A new {lead.business_line} lead has been assigned to you.",
        href="/dashboard/leads",
    )
    return lead


async def release_lead_from_telecaller(
    db: AsyncSession,
    lead_id: UUID,
    *,
    telecaller_staff_profile_uuid: UUID | None,
    release_reason: str | None,
    actor_uuid: UUID,
    actor_role: str,
) -> tuple[Lead, UUID | None]:
    """Release an assigned/working lead, optionally reassigning it to a new
    telecaller in the SAME transaction (no intermediate unassigned window).
    Admin-only (core.deps.require_admin).

    Validation order mirrors assign_lead_to_telecaller: lock row, validate lead
    state (LeadNotReleasable), validate the target telecaller only if one was
    given (InvalidTelecaller — same exists/role/status/business_line checks),
    mutate, commit, refresh, then best-effort notify. Runs on the admin's own
    request session for the same reason assign_lead_to_telecaller does (JWT
    platform_scope bypasses leads_rls, no superuser session needed).

    Returns (lead, previous_telecaller_staff_profile_uuid) — the previous id is
    captured before mutation since a reassign overwrites
    assigned_telecaller_profile_uuid with the new target.
    """
    lead = await db.get(Lead, lead_id, with_for_update=True)
    if lead is None:
        raise LeadNotFound
    if lead.status not in (LeadStatus.ASSIGNED, LeadStatus.WORKING):
        raise LeadNotReleasable

    previous_telecaller_uuid = lead.assigned_telecaller_profile_uuid
    previous_telecaller = (
        await db.get(StaffProfile, previous_telecaller_uuid)
        if previous_telecaller_uuid is not None
        else None
    )

    new_telecaller = None
    if telecaller_staff_profile_uuid is not None:
        new_telecaller = await db.get(StaffProfile, telecaller_staff_profile_uuid)
        if (
            new_telecaller is None
            or new_telecaller.role != StaffRole.TELECALLER
            or new_telecaller.status != ProfileStatus.ACTIVE
            or new_telecaller.business_line not in (lead.business_line, "both")
        ):
            raise InvalidTelecaller

    lead.released_at = datetime.now(UTC)
    lead.release_reason = release_reason
    if new_telecaller is not None:
        lead.assigned_telecaller_profile_uuid = new_telecaller.id
        lead.status = LeadStatus.ASSIGNED
        await record_audit(
            db,
            action=AuditAction.LEAD_ASSIGNED,
            entity_type="lead",
            entity_uuid=lead.id,
            actor_uuid=actor_uuid,
            actor_role=actor_role,
            business_line=lead.business_line,
            detail={
                "mode": "manual_reassignment",
                "telecaller_staff_profile_uuid": str(new_telecaller.id),
                "previous_telecaller_staff_profile_uuid": (
                    str(previous_telecaller_uuid) if previous_telecaller_uuid else None
                ),
            },
        )
    else:
        # CS-028: remember the cleared assignee for a later resubmission.
        if previous_telecaller_uuid is not None:
            lead.last_telecaller_profile_uuid = previous_telecaller_uuid
        lead.assigned_telecaller_profile_uuid = None
        lead.status = LeadStatus.RELEASED

    await db.commit()
    await db.refresh(lead)

    if previous_telecaller is not None:
        await emit_notification(
            user_uuid=previous_telecaller.auth_user_uuid,
            notification_type=NotificationType.LEAD_RELEASED,
            title="Lead reassigned" if new_telecaller is not None else "Lead released",
            body=(
                f"A {lead.business_line} lead has been reassigned to another telecaller."
                if new_telecaller is not None
                else f"A {lead.business_line} lead has been released back to the queue."
            ),
            href="/dashboard/leads",
        )
    if new_telecaller is not None:
        await emit_notification(
            user_uuid=new_telecaller.auth_user_uuid,
            notification_type=NotificationType.LEAD_ASSIGNED,
            title="New lead assigned",
            body=f"A {lead.business_line} lead has been assigned to you.",
            href="/dashboard/leads",
        )
    return lead, previous_telecaller_uuid


async def list_unassigned_leads(
    db: AsyncSession, limit: int = 100, offset: int = 0, *, lead_number: int | None = None
) -> list[Lead]:
    """Customer leads currently awaiting automatic Telecaller capacity.

    Assigned/working orphan rows stay in the relationship view until the
    scheduled repair releases and reassigns them.
    """
    stmt = (
        select(Lead)
        .where(
            Lead.assigned_telecaller_profile_uuid.is_(None),
            Lead.business_line.is_not(None),
            Lead.status.in_((LeadStatus.NEW, LeadStatus.RELEASED)),
            *customer_lead_predicates(),
            *lead_number_predicates(lead_number),
        )
        .order_by(Lead.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await db.scalars(stmt)).all())


async def list_assigned_leads(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    *,
    lead_number: int | None = None,
) -> list[tuple[Lead, StaffProfile | None, User | None]]:
    """Read-only assigned/working customer relationships for Admin oversight.

    The outer joins keep stale assignee relationships visible while the
    scheduled automatic repair moves them to an eligible Telecaller.
    """
    stmt = (
        select(Lead, StaffProfile, User)
        .outerjoin(StaffProfile, StaffProfile.id == Lead.assigned_telecaller_profile_uuid)
        .outerjoin(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            Lead.status.in_((LeadStatus.ASSIGNED, LeadStatus.WORKING)),
            *customer_lead_predicates(),
            *lead_number_predicates(lead_number),
        )
        .order_by(Lead.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return [(lead, staff, user) for lead, staff, user in result.all()]
