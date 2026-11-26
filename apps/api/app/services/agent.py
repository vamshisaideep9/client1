"""Agent lead sourcing + home summary (Agent Dashboard slice 1).

Read/update functions run on the request-scoped RLS session. Lead introduction
delegates its mobile-identity, Agent-attribution, and automatic-assignment
transaction to services.leads, then re-reads the result through the Agent's RLS
session before returning it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.lead_intake_attempt import IntakeActorType
from app.models.loan import LoanType
from app.models.profile import AgentProfile
from app.models.property import Property, PropertySubtype
from app.schemas.agent import PROPERTY_TYPE_LABELS, AgentLeadCreate, AgentLeadUpdate
from app.schemas.eligibility import EligibilitySummary
from app.schemas.lead_details import AgentLeadDetailsPatch
from app.services import lead_intake_attempts
from app.services.eligibility import EligibilityReason, agent_lead_eligibility
from app.services.lead_details import (
    DetailActor,
    LeadDetailsForbidden,
    LeadDetailsLocked,
    patch_details,
)
from app.services.leads import (
    AgentCaptureOutcome,
    AgentLeadConflict,
    AgentLeadNotResubmittable,
    capture_agent_lead_with_outcome,
    lead_number_predicates,
    resubmit_agent_lead,
)


class AgentProfileNotFound(Exception):
    """Raised when the current agent's AgentProfile row can't be found."""


class LeadCaptureFailed(Exception):
    """Raised when introduce_lead's capture write committed but produced no
    lead this agent can see or claim — blocked by the conflict guard (the
    mobile's existing active lead is on the OTHER business line, already
    assigned to a telecaller, or attributed to a different agent; see
    leads_rls's business_line-gated agent branch and services.leads.capture_lead's
    conflict_guard).

    ``reason`` is the CS-024 eligibility reason recorded for the attempt
    (None when the post-capture re-read found nothing); every reason maps to
    the same single-submit 409."""

    def __init__(self, reason: EligibilityReason | None = None) -> None:
        super().__init__(reason)
        self.reason = reason


class LeadCaptureUnavailable(Exception):
    """Raised when capture_lead's own write didn't commit (transient DB failure, rare).
    Distinct from LeadCaptureFailed, which means the write committed fine but the
    resulting lead isn't one this agent can see or claim (cross-line, locked, or
    attributed to another agent)."""


class LeadLocked(Exception):
    """Raised when a write is attempted on a lead already assigned to a telecaller."""


class InvalidStatusFilter(Exception):
    """Raised when list_my_leads is given a status_filter that isn't a valid LeadStatus value."""


class InvalidLeadInterest(Exception):
    """Raised when an introduced lead names a property or product the Agent cannot offer."""


class LeadNotResubmittable(Exception):
    """Raised when an Agent tries to resubmit a lead that is not eligible."""


async def _resolve_interest(
    db: AsyncSession, business_line: str, requirement: dict | None
) -> dict | None:
    """Validate the optional property / property type / product choice and
    snapshot its label.

    Reads through the Agent's request-scoped session, so only listings and
    products the Agent can already see are accepted. A real-estate Agent may
    pick only an active property and/or a property type; a loans Agent only
    an active product. The stored labels let the telecaller see the interest
    without another lookup. When both a listing and a property type are
    given they must agree.
    """
    if not requirement:
        return requirement
    resolved = dict(requirement)
    property_id = requirement.get("property_id")
    product_slug = requirement.get("product_slug")
    property_type = requirement.get("property_type")
    subtype: PropertySubtype | None = None
    if property_type is not None:
        if business_line != "real_estate":
            raise InvalidLeadInterest
        try:
            subtype = PropertySubtype(property_type)
        except ValueError as exc:
            raise InvalidLeadInterest from exc
        resolved["property_type"] = subtype.value
        resolved["property_type_label"] = PROPERTY_TYPE_LABELS[subtype]
    if property_id is not None:
        if business_line != "real_estate":
            raise InvalidLeadInterest
        prop = await db.scalar(
            select(Property).where(Property.id == UUID(str(property_id)), Property.active.is_(True))
        )
        if prop is None:
            raise InvalidLeadInterest
        if (
            subtype is not None
            and prop.property_subtype is not None
            and prop.property_subtype != subtype
        ):
            raise InvalidLeadInterest
        resolved["property_id"] = str(prop.id)
        resolved["interest_title"] = f"{prop.title}, {prop.location}"[:240]
    elif product_slug is not None:
        if business_line != "loans":
            raise InvalidLeadInterest
        product = await db.scalar(
            select(LoanType).where(LoanType.name == product_slug, LoanType.active.is_(True))
        )
        if product is None:
            raise InvalidLeadInterest
        resolved["interest_title"] = product.label[:240]
    return resolved


async def get_home_summary(
    db: AsyncSession, agent_profile_uuid: UUID
) -> tuple[AgentProfile, dict[str, int]]:
    profile = await db.get(AgentProfile, agent_profile_uuid)
    if profile is None:
        raise AgentProfileNotFound
    leads = await list_my_leads(db, agent_profile_uuid)
    counts: dict[str, int] = {}
    for lead in leads:
        status = "expired" if lead.agent_expired_at is not None else lead.status.value
        counts[status] = counts.get(status, 0) + 1
    return profile, counts


async def introduce_lead(
    db: AsyncSession,
    *,
    agent_profile_uuid: UUID,
    business_line: str,
    payload: AgentLeadCreate,
) -> Lead:
    """Capture and automatically assign a lead sourced by this Agent."""
    lead, _outcome = await introduce_lead_with_outcome(
        db,
        agent_profile_uuid=agent_profile_uuid,
        business_line=business_line,
        payload=payload,
    )
    return lead


async def introduce_lead_with_outcome(
    db: AsyncSession,
    *,
    agent_profile_uuid: UUID,
    business_line: str,
    payload: AgentLeadCreate,
) -> tuple[Lead, AgentCaptureOutcome]:
    """``introduce_lead`` that also says whether the lead was new to this
    Agent (created or claimed) or was already one of theirs (bulk submit)."""
    requirement = await _resolve_interest(db, business_line, payload.requirement)
    try:
        lead, outcome = await capture_agent_lead_with_outcome(
            mobile=payload.mobile,
            name=payload.name,
            business_line=business_line,
            agent_profile_uuid=agent_profile_uuid,
            requirement=requirement,
        )
    except AgentLeadConflict as exc:
        raise LeadCaptureFailed(exc.reason) from exc
    except Exception as exc:
        raise LeadCaptureUnavailable from exc

    # Re-read through the Agent's request-scoped RLS session so the response is
    # shaped only from a row the caller remains authorized to see.
    visible = await db.scalar(
        select(Lead).where(
            Lead.id == lead.id,
            Lead.origin_agent_profile_uuid == agent_profile_uuid,
            Lead.business_line == business_line,
        )
    )
    if visible is None:
        raise LeadCaptureFailed
    return visible, outcome


async def list_my_leads(
    db: AsyncSession,
    agent_profile_uuid: UUID,
    status_filter: str | None = None,
    *,
    lead_number: int | None = None,
) -> list[Lead]:
    stmt = select(Lead).where(
        Lead.origin_agent_profile_uuid == agent_profile_uuid,
        *lead_number_predicates(lead_number),
    )
    if status_filter is not None:
        if status_filter == "expired":
            stmt = stmt.where(Lead.agent_expired_at.is_not(None))
        else:
            try:
                status_enum = LeadStatus(status_filter)
            except ValueError as exc:
                raise InvalidStatusFilter from exc
            stmt = stmt.where(Lead.agent_expired_at.is_(None), Lead.status == status_enum)
    stmt = stmt.order_by(Lead.updated_at.desc())
    return list((await db.scalars(stmt)).all())


async def lead_eligibility_summary(
    db: AsyncSession, agent_profile_uuid: UUID
) -> EligibilitySummary:
    """Eligible / Not eligible / Duplicate for the Agent's leads (CS-024).

    Accepted leads are read on the Agent's RLS session and classified by
    services.eligibility; rejected introductions come from the recorded
    attempts.
    """
    expired_markers = (
        await db.scalars(
            select(Lead.agent_expired_at).where(
                Lead.origin_agent_profile_uuid == agent_profile_uuid
            )
        )
    ).all()
    return await lead_intake_attempts.eligibility_summary(
        db,
        IntakeActorType.AGENT,
        agent_profile_uuid,
        (agent_lead_eligibility(marker)[0] for marker in expired_markers),
    )


async def get_lead_for_agent(
    db: AsyncSession, lead_id: UUID, agent_profile_uuid: UUID
) -> Lead | None:
    return await db.scalar(
        select(Lead).where(Lead.id == lead_id, Lead.origin_agent_profile_uuid == agent_profile_uuid)
    )


async def update_lead_for_agent(
    db: AsyncSession,
    lead: Lead,
    payload: AgentLeadUpdate,
    *,
    auth_user_uuid: UUID,
    agent_profile_uuid: UUID,
) -> Lead:
    requirement = payload.requirement or {}
    # Legacy clients send a valid name with requirement:null to clear notes.
    # Keep that behavior without clearing the new email or fixed interest keys.
    if "requirement" in payload.model_fields_set and payload.requirement is None:
        requirement = {"notes": None}
    details = AgentLeadDetailsPatch.model_validate(
        {
            **({"name": payload.name} if "name" in payload.model_fields_set else {}),
            **{key: requirement[key] for key in ("notes", "email") if key in requirement},
        }
    )
    try:
        return await patch_details(
            db,
            lead=lead,
            payload=details,
            actor=DetailActor(
                role="agent",
                subject_uuid=agent_profile_uuid,
                auth_user_uuid=auth_user_uuid,
            ),
        )
    except (LeadDetailsForbidden, LeadDetailsLocked, DBAPIError) as exc:
        await db.rollback()
        raise LeadLocked from exc


async def resubmit_lead_for_agent(
    db: AsyncSession,
    lead_id: UUID,
    *,
    agent_profile_uuid: UUID,
    auth_user_uuid: UUID,
) -> Lead:
    """Restart this Agent's 30-day window on their expired lead.

    The write runs in services.leads on its own transaction; the result is then
    re-read through the Agent's request-scoped RLS session.
    """
    try:
        await resubmit_agent_lead(
            lead_id=lead_id,
            agent_profile_uuid=agent_profile_uuid,
            actor_auth_user_uuid=auth_user_uuid,
        )
    except AgentLeadNotResubmittable as exc:
        raise LeadNotResubmittable from exc
    visible = await db.scalar(
        select(Lead)
        .where(Lead.id == lead_id, Lead.origin_agent_profile_uuid == agent_profile_uuid)
        .execution_options(populate_existing=True)
    )
    if visible is None:
        raise LeadNotResubmittable
    return visible
