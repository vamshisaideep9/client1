"""Field-level lead-detail ownership and lifecycle enforcement (FR-2.8)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.lead import Lead, LeadStatus
from app.models.profile import ClientProfile
from app.schemas.lead_details import LeadDetailsPatch, LeadDetailsRead
from app.services.audit_log import record as record_audit

OwnerRole = Literal[
    "agent", "client", "telecaller", "admin", "system", "unclaimed", "legacy_locked"
]
_EDITABLE_PATHS = ("name", "requirement.notes")
_AGENT_EDITABLE_STATUSES = {LeadStatus.NEW, LeadStatus.ASSIGNED}
_CLIENT_EDITABLE_STATUSES = {
    LeadStatus.NEW,
    LeadStatus.ASSIGNED,
    LeadStatus.WORKING,
    LeadStatus.RELEASED,
}


class LeadDetailsNotFound(Exception):
    pass


class LeadDetailsForbidden(Exception):
    pass


class LeadDetailsLocked(Exception):
    pass


@dataclass(frozen=True)
class DetailActor:
    role: Literal["agent", "client", "telecaller", "admin"]
    subject_uuid: UUID
    auth_user_uuid: UUID


def owner(role: OwnerRole, subject_uuid: UUID | None = None) -> dict[str, str | None]:
    return {"role": role, "subject_uuid": str(subject_uuid) if subject_uuid else None}


def initial_ownership(
    *,
    name: str | None,
    requirement: dict[str, Any] | None,
    creator_role: OwnerRole,
    creator_subject_uuid: UUID | None = None,
) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    creator = owner(creator_role, creator_subject_uuid)
    if name is not None:
        result["name"] = creator
    for key in requirement or {}:
        result[f"requirement.{key}"] = (
            owner("system") if key in {"page", "product", "property_ref", "topic"} else creator
        )
    return result


def transfer_unclaimed_to_client(lead: Lead, client_profile_uuid: UUID) -> None:
    ownership = dict(lead.detail_ownership or {})
    for path, descriptor in ownership.items():
        if isinstance(descriptor, dict) and descriptor.get("role") == "unclaimed":
            ownership[path] = owner("client", client_profile_uuid)
    lead.detail_ownership = ownership


def _descriptor_matches(descriptor: object, actor: DetailActor) -> bool:
    return (
        isinstance(descriptor, dict)
        and descriptor.get("role") == actor.role
        and descriptor.get("subject_uuid") == str(actor.subject_uuid)
    )


def _lifecycle_allows(lead: Lead, actor: DetailActor) -> bool:
    if actor.role == "admin":
        return True
    if actor.role == "agent":
        return (
            lead.status in _AGENT_EDITABLE_STATUSES
            and lead.agent_expired_at is None
            and (lead.expires_at is None or lead.expires_at > datetime.now(UTC))
        )
    if actor.role == "client":
        return lead.status in _CLIENT_EDITABLE_STATUSES
    return lead.status not in {LeadStatus.CONVERTED, LeadStatus.CLOSED}


def editable_paths(lead: Lead, actor: DetailActor) -> list[str]:
    if not _lifecycle_allows(lead, actor):
        return []
    ownership = lead.detail_ownership or {}
    return [
        path
        for path in _EDITABLE_PATHS
        if actor.role == "admin"
        or ownership.get(path) is None
        or _descriptor_matches(ownership.get(path), actor)
    ]


# ---------------------------------------------------------------------------
# Requirement shaping: the ONE allowlist every role's lead read goes through
# (CS-028 security review). Unknown keys never pass a read; each role sees
# only the keys below.
# ---------------------------------------------------------------------------

# Every key a product path writes under ``leads.requirement``:
# - the Agent lead form (services/agent._resolve_interest);
AGENT_FORM_REQUIREMENT_KEYS = frozenset(
    {
        "notes",
        "email",
        "product_slug",
        "property_id",
        "property_type",
        "property_type_label",
        "interest_title",
    }
)
# - the public lead form (api/v1/leads.py) and older "topic" captures.
PUBLIC_FORM_REQUIREMENT_KEYS = frozenset(
    {
        "page",
        "topic",
        "product",
        "property_ref",
        "property_title",
        "property_location",
        "email",
        "message",
    }
)
# What the assigned Telecaller works the lead with: every known key, the
# person's email included (they already see the mobile). It stays behind
# the Admin's Telecaller "Requirement details" field rule (there is no
# separate email rule), applied by the caller through project_values.
_TELECALLER_REQUIREMENT_KEYS = AGENT_FORM_REQUIREMENT_KEYS | PUBLIC_FORM_REQUIREMENT_KEYS
# Client and Admin lead-details reads: notes plus the labels the server
# resolved for the listing / product / property type an Agent picked. Only a
# platform Admin's read adds the email.
_LEAD_DETAILS_REQUIREMENT_KEYS = frozenset(
    {"notes", "interest_title", "property_type", "property_type_label"}
)
_ADMIN_REQUIREMENT_KEYS = _LEAD_DETAILS_REQUIREMENT_KEYS | {"email"}

RequirementViewer = Literal["admin", "client", "agent", "telecaller"]


def _owned_by_agent(lead: Lead, key: str, agent_profile_uuid: UUID | None) -> bool:
    descriptor = (lead.detail_ownership or {}).get(f"requirement.{key}")
    return (
        agent_profile_uuid is not None
        and isinstance(descriptor, dict)
        and descriptor.get("role") == "agent"
        and descriptor.get("subject_uuid") == str(agent_profile_uuid)
    )


def visible_requirement(
    lead: Lead,
    viewer: RequirementViewer,
    *,
    agent_profile_uuid: UUID | None = None,
) -> dict[str, Any] | None:
    """The part of ``lead.requirement`` a viewer may read, or None.

    - ``admin`` (platform Admin lead details): notes, the resolved labels and
      the email.
    - ``client`` (and any other lead-details reader): notes and the resolved
      labels; never the email.
    - ``agent`` (the originating Agent): only Agent-form keys whose ownership
      descriptor names this Agent, so an Agent who claimed an existing
      enquiry never reads what the person, a Telecaller, another Agent or
      the public form ("unclaimed" / "system") recorded.
    - ``telecaller`` (the assigned Telecaller): every known key, email
      included; the caller still applies the field-visibility rule.

    Employees, Sub Admin team reads and the Agent history carry no
    requirement at all.
    """
    source = lead.requirement or {}
    if viewer == "admin":
        allowed = _ADMIN_REQUIREMENT_KEYS
    elif viewer == "telecaller":
        allowed = _TELECALLER_REQUIREMENT_KEYS
    elif viewer == "agent":
        allowed = frozenset(
            key
            for key in AGENT_FORM_REQUIREMENT_KEYS
            if _owned_by_agent(lead, key, agent_profile_uuid)
        )
    else:
        allowed = _LEAD_DETAILS_REQUIREMENT_KEYS
    return {key: value for key, value in source.items() if key in allowed} or None


def to_read(lead: Lead, actor: DetailActor) -> LeadDetailsRead:
    safe_requirement = visible_requirement(lead, "admin" if actor.role == "admin" else "client")
    safe_owners = {
        path: descriptor["role"]
        for path, descriptor in (lead.detail_ownership or {}).items()
        if path in _EDITABLE_PATHS
        and isinstance(descriptor, dict)
        and descriptor.get("role")
        in {"agent", "client", "telecaller", "admin", "system", "unclaimed", "legacy_locked"}
    }
    return LeadDetailsRead(
        id=lead.id,
        business_line=lead.business_line,
        status=lead.status,
        name=lead.name,
        requirement=safe_requirement,
        field_owners=safe_owners,
        editable_fields=editable_paths(lead, actor),
        updated_at=lead.updated_at,
    )


async def get_for_actor(db: AsyncSession, lead_id: UUID, actor: DetailActor) -> Lead:
    lead = await db.scalar(select(Lead).where(Lead.id == lead_id))
    if lead is None:
        raise LeadDetailsNotFound
    return lead


async def get_for_client_line(
    db: AsyncSession, *, auth_user_uuid: UUID, business_line: str, for_update: bool = False
) -> tuple[Lead, UUID]:
    stmt = (
        select(Lead, ClientProfile.id)
        .join(ClientProfile, ClientProfile.id == Lead.client_profile_uuid)
        .where(
            ClientProfile.auth_user_uuid == auth_user_uuid,
            ClientProfile.business_line == business_line,
        )
        .order_by(
            Lead.status.in_([LeadStatus.CONVERTED, LeadStatus.CLOSED]),
            Lead.updated_at.desc(),
            Lead.id,
        )
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Lead)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise LeadDetailsNotFound
    return row[0], row[1]


async def patch_details(
    db: AsyncSession,
    *,
    lead: Lead,
    payload: LeadDetailsPatch,
    actor: DetailActor,
    admin_reason: str | None = None,
) -> Lead:
    locked_lead = await db.scalar(select(Lead).where(Lead.id == lead.id).with_for_update(of=Lead))
    if locked_lead is None:
        # RLS intentionally hides rows that the actor can still read but may no
        # longer update after a lifecycle transition.
        raise LeadDetailsLocked
    lead = locked_lead

    if not _lifecycle_allows(lead, actor):
        raise LeadDetailsLocked

    ownership = dict(lead.detail_ownership or {})
    requested: dict[str, object] = {}
    if "name" in payload.model_fields_set:
        requested["name"] = payload.name.strip() if payload.name is not None else None
    if "notes" in payload.model_fields_set:
        requested["requirement.notes"] = (
            payload.notes.strip() if payload.notes is not None else None
        )
    if "email" in payload.model_fields_set:
        # Only AgentLeadDetailsPatch carries an email, and only the
        # originating Agent's edit builds one (already normalised).
        if actor.role != "agent":
            raise LeadDetailsForbidden
        requested["requirement.email"] = getattr(payload, "email", None)

    changed_paths: list[str] = []
    for path, value in requested.items():
        key = path.removeprefix("requirement.")
        current_value = lead.name if path == "name" else (lead.requirement or {}).get(key)
        if current_value == value:
            continue

        descriptor = ownership.get(path)
        if descriptor is None:
            ownership[path] = owner(actor.role, actor.subject_uuid)
        elif actor.role != "admin" and not _descriptor_matches(descriptor, actor):
            raise LeadDetailsForbidden

        if path == "name":
            lead.name = value  # type: ignore[assignment]
            changed_paths.append(path)
        else:
            requirement = dict(lead.requirement or {})
            if path == "requirement.email" and value is None:
                requirement.pop("email", None)
            else:
                requirement[key] = value
            lead.requirement = requirement
            changed_paths.append(path)

    if not changed_paths:
        return lead
    lead.detail_ownership = ownership

    if actor.role == "admin":
        if not admin_reason:
            raise LeadDetailsForbidden
        await record_audit(
            db,
            action=AuditAction.LEAD_DETAILS_UPDATED,
            entity_type="lead",
            entity_uuid=lead.id,
            actor_uuid=actor.auth_user_uuid,
            actor_role="admin",
            business_line=lead.business_line,
            detail={"fields": sorted(changed_paths), "reason": admin_reason},
        )
    await db.commit()
    await db.refresh(lead)
    return lead
