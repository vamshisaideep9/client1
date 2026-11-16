"""Agent home + lead-introduction/tracking schemas (Agent Dashboard slice 1)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.lead_activity import CallDisposition, InterestLevel

LeadStatusLiteral = Literal[
    "new", "assigned", "working", "converted", "closed", "released", "expired"
]
AgentProfileStatusLiteral = Literal["active", "inactive", "pending", "suspended"]


class AgentProfileStatusRead(BaseModel):
    agent_code: str
    business_line: Literal["loans", "real_estate"]
    kyc_status: str | None
    status: AgentProfileStatusLiteral
    rera_code: str | None
    approved_at: datetime | None


class AgentHomeResponse(BaseModel):
    profile: AgentProfileStatusRead
    counts_by_status: dict[str, int]


_AGENT_REQUIREMENT_KEYS = {"notes", "property_id", "product_slug"}

# A lead must carry the person's name so the telecaller can address them. Leading
# and trailing whitespace is stripped first, so a blank name is rejected.
LeadName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AgentLeadCreate(BaseModel):
    mobile: Annotated[str, Field(pattern=r"^\+[1-9]\d{6,14}$")]
    name: LeadName
    # Agent-authored context: free-text notes plus, optionally, the one listing
    # (real estate) or product (loans) the person is interested in. The service
    # confirms the chosen item exists, is published, and matches the Agent's
    # business line, then records its title for the telecaller.
    requirement: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _known_requirement_shape(self) -> AgentLeadCreate:
        if self.requirement is None:
            return self
        unknown = set(self.requirement) - _AGENT_REQUIREMENT_KEYS
        if unknown:
            raise ValueError("Requirement may only contain notes, property_id or product_slug.")
        notes = self.requirement.get("notes")
        if notes is not None and (not isinstance(notes, str) or len(notes) > 1000):
            raise ValueError("Requirement notes must be text of at most 1000 characters.")
        property_id = self.requirement.get("property_id")
        if property_id is not None:
            try:
                UUID(str(property_id))
            except ValueError as exc:
                raise ValueError("Requirement property_id must be a property id.") from exc
        slug = self.requirement.get("product_slug")
        if slug is not None and (not isinstance(slug, str) or not 0 < len(slug) <= 80):
            raise ValueError("Requirement product_slug must be a product identifier.")
        if property_id is not None and slug is not None:
            raise ValueError("Choose either a property or a loan product, not both.")
        return self


class AgentLeadUpdate(BaseModel):
    # Omit name to leave it unchanged; a supplied name cannot be blank or null.
    name: LeadName | None = None
    requirement: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> AgentLeadUpdate:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name is required and cannot be cleared.")
        if self.name is None and self.requirement is None:
            raise ValueError("Provide at least one of name or requirement.")
        return self

    @model_validator(mode="after")
    def _only_owned_requirement_notes(self) -> AgentLeadUpdate:
        if self.requirement is not None and set(self.requirement) != {"notes"}:
            raise ValueError("Only requirement.notes can be edited from the Agent workspace.")
        return self


class AgentLeadRead(BaseModel):
    id: UUID
    name: str | None = None
    mobile: str
    business_line: Literal["loans", "real_estate"] | None
    status: LeadStatusLiteral
    requirement: dict[str, Any] | None = None
    registered: bool
    editable: bool
    # True when the originating Agent may resubmit this expired lead for a
    # fresh window (2026-11-14 amendment to FR-4.6).
    resubmittable: bool
    expires_at: datetime | None
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Lead history (CS-022): what happened to a lead the Agent introduced.
# Read through the confined ``agent_lead_history`` database function; status
# reasons, rates, fees, form answers, contact details and messages are never
# part of it. Notes, amounts and staff names follow the Admin's Agent field
# rules: a hidden value is null and its key is listed in ``hidden_fields``.
# ---------------------------------------------------------------------------


class AgentHistoryApplication(BaseModel):
    id: UUID
    product_label: str | None
    bank_name: str | None
    status: str
    amount_requested: Decimal | None
    amount_sanctioned: Decimal | None
    opened_at: datetime
    closed_at: datetime | None
    disbursed_at: datetime | None


class AgentHistoryServiceEnquiry(BaseModel):
    id: UUID
    product_label: str | None
    product_category: str | None
    status: str
    submitted_at: datetime


class AgentHistoryDeal(BaseModel):
    id: UUID
    property_title: str | None
    property_category: str | None
    status: str
    price_quoted: Decimal | None
    booking_amount: Decimal | None
    opened_at: datetime
    closed_at: datetime | None


class AgentHistoryEnquiry(BaseModel):
    id: UUID
    title: str
    locality: str | None
    city: str | None
    status: str
    created_at: datetime


class AgentHistorySiteVisit(BaseModel):
    id: UUID
    title: str
    locality: str | None
    city: str | None
    preferred_date: date
    preferred_time_slot: str
    status: str
    created_at: datetime


class AgentHistoryCall(BaseModel):
    id: UUID
    disposition: CallDisposition
    interest_level: InterestLevel | None
    notes: str | None
    follow_up_at: datetime | None
    created_at: datetime
    staff_name: str | None


AgentHistoryEventKind = Literal[
    "introduced",
    "lead_assigned",
    "agent_lead_expired",
    "agent_lead_resubmitted",
    "team_lead_status_updated",
    "team_lead_reassigned",
    "loan_application_updated",
    "property_deal_updated",
]


class AgentHistoryEvent(BaseModel):
    event: AgentHistoryEventKind
    at: datetime
    # The loan application or property deal an update belongs to.
    request_id: UUID | None
    from_status: str | None
    to_status: str | None


class AgentLeadHistoryRead(BaseModel):
    lead_id: UUID
    status: LeadStatusLiteral
    created_at: datetime
    applications: list[AgentHistoryApplication]
    service_enquiries: list[AgentHistoryServiceEnquiry]
    deals: list[AgentHistoryDeal]
    enquiries: list[AgentHistoryEnquiry]
    site_visits: list[AgentHistorySiteVisit]
    calls: list[AgentHistoryCall]
    # Oldest first, starting with the introduction.
    timeline: list[AgentHistoryEvent]
    # Agent field rules the Admin switched off ("call_notes", "staff_names",
    # "deal_amount").
    hidden_fields: list[str]
