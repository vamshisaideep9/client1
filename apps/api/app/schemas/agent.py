"""Agent home + lead-introduction/tracking schemas (Agent Dashboard slice 1)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.lead_reference import LeadRef
from app.models.lead_activity import CallDisposition, InterestLevel
from app.models.property import PropertySubtype
from app.schemas.eligibility import EligibilityReasonLiteral, RowEligibilityLiteral
from app.schemas.telecaller import LeadFacets

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


_AGENT_REQUIREMENT_KEYS = {"notes", "property_id", "product_slug", "email", "property_type"}
# Keys an Agent may change after introduction (while the lead is still
# editable and the key is theirs in the detail-ownership ledger). The chosen
# product, listing and property type are fixed at introduction.
_AGENT_EDITABLE_REQUIREMENT_KEYS = {"notes", "email"}

LEAD_NOTES_MAX_LENGTH = 1000
LEAD_EMAIL_MAX_LENGTH = 254

# Human labels for the property types an Agent may name on a real-estate lead
# (one per ``PropertySubtype``). The label is stored beside the value as
# ``requirement.property_type_label`` so Telecallers and Admins read it
# without another lookup, like ``interest_title``.
PROPERTY_TYPE_LABELS: dict[PropertySubtype, str] = {
    PropertySubtype.INDIVIDUAL_HOUSE: "Individual house",
    PropertySubtype.STANDALONE_APARTMENT: "Standalone apartment",
    PropertySubtype.GATED_COMMUNITY_APARTMENT: "Gated community apartment",
    PropertySubtype.VILLA: "Villa",
    PropertySubtype.LOCKED_SPACE: "Locked commercial space",
    PropertySubtype.UNLOCKED_SPACE: "Unlocked commercial space",
    PropertySubtype.PLOT: "Plot",
    PropertySubtype.FARMLAND: "Farmland",
    PropertySubtype.AGRILAND: "Agriland",
}

_EMAIL = TypeAdapter(EmailStr)

# A lead must carry the person's name so the telecaller can address them. Leading
# and trailing whitespace is stripped first, so a blank name is rejected.
LeadName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def normalise_lead_email(value: object) -> str | None:
    """A lead's optional email: trimmed, lower-cased and syntax-checked.

    ``None`` or blank means "no email". Anything else must be a deliverable-
    looking address of at most 254 characters, or ``ValueError`` is raised.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Email must be text.")
    candidate = value.strip()
    if not candidate:
        return None
    if len(candidate) > LEAD_EMAIL_MAX_LENGTH:
        raise ValueError("Enter a valid email address.")
    try:
        validated = _EMAIL.validate_python(candidate)
    except ValidationError as exc:
        raise ValueError("Enter a valid email address.") from exc
    return str(validated).lower()


def parse_property_type(value: object) -> PropertySubtype:
    if not isinstance(value, str):
        raise ValueError("Requirement property_type must be a property type.")
    try:
        return PropertySubtype(value.strip().lower())
    except ValueError as exc:
        raise ValueError("Requirement property_type must be a property type.") from exc


def _validate_notes(requirement: dict[str, Any]) -> None:
    notes = requirement.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > LEAD_NOTES_MAX_LENGTH):
        raise ValueError("Requirement notes must be text of at most 1000 characters.")


def _normalise_email_key(requirement: dict[str, Any]) -> None:
    """Normalise ``requirement["email"]`` in place; drop it when blank."""
    if "email" not in requirement:
        return
    email = normalise_lead_email(requirement["email"])
    if email is None:
        requirement.pop("email")
    else:
        requirement["email"] = email


class AgentLeadCreate(BaseModel):
    mobile: Annotated[str, Field(pattern=r"^\+[1-9]\d{6,14}$")]
    name: LeadName
    # The top-level form field is folded into requirement.email so capture,
    # ownership, visibility and deletion have one storage path. Nested email
    # remains accepted for existing clients and the bulk-introduction path.
    email: Annotated[EmailStr, Field(max_length=LEAD_EMAIL_MAX_LENGTH)] | None = None
    # Agent-authored context: free-text notes, an optional email, and
    # optionally the one listing or property type (real estate) or product
    # (loans) the person is interested in. The service confirms the chosen
    # item exists, is published, and matches the Agent's business line, then
    # records its label for the telecaller.
    requirement: dict[str, Any] | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: object) -> str | None:
        return normalise_lead_email(value)

    @model_validator(mode="after")
    def _known_requirement_shape(self) -> AgentLeadCreate:
        if self.requirement is None:
            if self.email is not None:
                self.requirement = {"email": str(self.email)}
            return self
        unknown = set(self.requirement) - _AGENT_REQUIREMENT_KEYS
        if unknown:
            raise ValueError(
                "Requirement may only contain notes, email, property_id, property_type "
                "or product_slug."
            )
        _validate_notes(self.requirement)
        _normalise_email_key(self.requirement)
        if self.email is not None:
            nested_email = self.requirement.get("email")
            if nested_email is not None and nested_email != self.email:
                raise ValueError("Email and requirement.email must match when both are supplied.")
            self.requirement["email"] = str(self.email)
        property_id = self.requirement.get("property_id")
        if property_id is not None:
            try:
                UUID(str(property_id))
            except ValueError as exc:
                raise ValueError("Requirement property_id must be a property id.") from exc
        property_type = self.requirement.get("property_type")
        if property_type is not None:
            self.requirement["property_type"] = parse_property_type(property_type).value
        elif "property_type" in self.requirement:
            self.requirement.pop("property_type")
        slug = self.requirement.get("product_slug")
        if slug is not None and (not isinstance(slug, str) or not 0 < len(slug) <= 80):
            raise ValueError("Requirement product_slug must be a product identifier.")
        if slug is not None and (property_id is not None or property_type is not None):
            raise ValueError("Choose either a property or a loan product, not both.")
        if not self.requirement:
            self.requirement = None
        return self


class AgentLeadUpdate(BaseModel):
    # Omit name to leave it unchanged; a supplied name cannot be blank or null.
    name: LeadName | None = None
    # Only ``notes`` and ``email`` may be sent; a null or blank email removes it.
    requirement: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> AgentLeadUpdate:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Name is required and cannot be cleared.")
        if self.name is None and self.requirement is None:
            raise ValueError("Provide at least one of name or requirement.")
        return self

    @model_validator(mode="after")
    def _only_owned_requirement_keys(self) -> AgentLeadUpdate:
        if self.requirement is None:
            return self
        keys = set(self.requirement)
        if not keys or not keys <= _AGENT_EDITABLE_REQUIREMENT_KEYS:
            raise ValueError(
                "Only requirement.notes and requirement.email can be edited from the "
                "Agent workspace."
            )
        _validate_notes(self.requirement)
        if "email" in self.requirement:
            self.requirement["email"] = normalise_lead_email(self.requirement["email"])
        return self


# ---------------------------------------------------------------------------
# Bulk lead submit (CS-028): the browser parses the spreadsheet and sends at
# most 200 rows as JSON; the server never receives a file. Each row is
# validated and, unless ``dry_run``, submitted through the same path as a
# single introduction. Raw caps below only bound the request size; the
# per-row business rules (name ≤ 100, email ≤ 254, description ≤ 1000) are
# reported per row instead of failing the whole upload.
# ---------------------------------------------------------------------------

AGENT_LEAD_BULK_MAX_ROWS = 200

BulkText = Annotated[str, Field(max_length=500)]


class AgentLeadBulkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The row's own serial number from the sheet, echoed back as text.
    sno: Annotated[str, Field(max_length=40)] | Annotated[int, Field(ge=0, le=10**9)] | None = None
    name: BulkText | None = None
    # +91XXXXXXXXXX, 91XXXXXXXXXX or a 10-digit Indian mobile; spaces,
    # dashes, dots and brackets are ignored. A number cell may arrive as int.
    mobile: Annotated[str, Field(max_length=40)] | Annotated[int, Field(ge=0, le=10**13)] | None = (
        None
    )
    email: Annotated[str, Field(max_length=320)] | None = None
    # Loans Agent: an active product's label or slug. Real-estate Agent: a
    # property type's value or label. Case-insensitive.
    requirement: Annotated[str, Field(max_length=200)] | None = None
    # Stored as requirement.notes (at most 1000 characters).
    description: Annotated[str, Field(max_length=4000)] | None = None


class AgentLeadBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # True: validate and report only; nothing is created or recorded.
    dry_run: bool
    rows: Annotated[
        list[AgentLeadBulkRow], Field(min_length=1, max_length=AGENT_LEAD_BULK_MAX_ROWS)
    ]


AgentLeadBulkOutcomeLiteral = Literal[
    # Dry run only: the row passed validation and would be submitted.
    "ready",
    # A new lead, or an open unclaimed enquiry for the number became theirs.
    "created",
    # The number was already one of this Agent's live leads (nothing changed
    # beyond what a single re-submit would do).
    "already_introduced",
    # Turned away as a duplicate (CS-024 "already_linked").
    "duplicate",
    # Turned away by a rule (CS-024 "own_lead_window_ended": resubmit it).
    "not_eligible",
    # The same mobile appeared on an earlier row of this upload.
    "duplicate_in_file",
    "invalid",
    # Capture was temporarily unavailable; the row can be retried.
    "unavailable",
]
AgentLeadBulkFieldLiteral = Literal["sno", "name", "mobile", "email", "requirement", "description"]


class AgentLeadBulkFieldError(BaseModel):
    field: AgentLeadBulkFieldLiteral
    message: str


class AgentLeadBulkRowResult(BaseModel):
    # Zero-based position in the request's ``rows``.
    row_index: int
    sno: str | None = None
    outcome: AgentLeadBulkOutcomeLiteral
    # The Agent's own input, normalised (E.164); null when invalid.
    mobile: str | None = None
    # The product / property type the requirement text matched.
    requirement_label: str | None = None
    # CS-024 reason code and label for duplicate / not_eligible rows; the
    # same copy the Agent's attempts list already shows, never whose record
    # it is.
    reason: EligibilityReasonLiteral | None = None
    reason_label: str | None = None
    errors: list[AgentLeadBulkFieldError] = Field(default_factory=list)
    lead_id: UUID | None = None
    # For duplicate_in_file: the earlier row with the same mobile.
    duplicate_of_row_index: int | None = None


class AgentLeadBulkTotals(BaseModel):
    rows: int
    ready: int
    created: int
    already_introduced: int
    duplicate: int
    not_eligible: int
    duplicate_in_file: int
    invalid: int
    unavailable: int


class AgentLeadBulkResponse(BaseModel):
    dry_run: bool
    rows: list[AgentLeadBulkRowResult]
    totals: AgentLeadBulkTotals


# The choices a bulk upload's Requirement column accepts: exactly the
# catalogue ``services/agent_lead_bulk.load_catalogue`` matches against.
AgentLeadBulkProductCategoryLiteral = Literal["loan", "credit_card", "insurance", "property"]


class AgentLeadBulkProduct(BaseModel):
    # The product code (slug) or property type value; either it or the label
    # can be written in the Requirement column.
    code: str
    label: str


class AgentLeadBulkProductGroup(BaseModel):
    category: AgentLeadBulkProductCategoryLiteral
    label: str
    products: list[AgentLeadBulkProduct]


class AgentLeadBulkProductsResponse(BaseModel):
    business_line: Literal["loans", "real_estate"]
    groups: list[AgentLeadBulkProductGroup]


class AgentLeadStaff(BaseModel):
    """A staff member working an Agent's lead: display name, role and staff
    code only (2026-11-26 decision; shown regardless of the Agent's staff-name
    field rule). Never a phone number, email or profile id."""

    name: str | None
    role_label: str
    staff_code: str


class AgentLeadRead(BaseModel):
    id: UUID
    lead_ref: LeadRef
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
    # CS-028: how often and when the Agent last resubmitted it (0 / null
    # when never), for a "Resubmitted ×N" badge and client-side filters.
    resubmit_count: int
    last_resubmitted_at: datetime | None
    expires_at: datetime | None
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # CS-024: an accepted lead is eligible until its attribution window
    # expires. Reason codes and labels come from services/eligibility.py.
    eligibility: RowEligibilityLiteral
    eligibility_reason: EligibilityReasonLiteral | None = None
    eligibility_reason_label: str | None = None
    # List only: product and property facts of the lead's applications and
    # deals for the list filters (ids, labels and enums; no amounts), read
    # through the confined lead_list_signals reader's Agent branch.
    facets: LeadFacets | None = None
    # Who works the lead and its product, read through the confined
    # ``agent_lead_assignees`` function (own introduced leads on the Agent's
    # line only). The Officer is the assignee of the latest non-cancelled
    # task. Null when nobody is assigned or the product is unknown.
    product_label: str | None = None
    telecaller: AgentLeadStaff | None = None
    officer: AgentLeadStaff | None = None


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
