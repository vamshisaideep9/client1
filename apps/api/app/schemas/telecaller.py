"""Telecaller lead-follow-up schemas (list/detail, status update, call log, home)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.lead_reference import LeadRef
from app.schemas.chat_inquiries import ChatInquiryRead
from app.schemas.financial_products import FormAnswers, ProductFormDefinition
from app.schemas.profile_metadata import TaskStaffRead

LeadStatusLiteral = Literal["new", "assigned", "working", "converted", "closed", "released"]
LoanStatusLiteral = Literal[
    "new",
    "assigned",
    "contacted",
    "docs_collected",
    "submitted_to_bank",
    "under_review",
    "sanctioned",
    "agreement_collected",
    "agreement_submitted_to_bank",
    "disbursed",
    "closed",
    "rejected",
    "on_hold",
]
PropertyDealStatusLiteral = Literal[
    "new",
    "contacted",
    "site_visit_done",
    "negotiation",
    "booked",
    "agreement_signed",
    "closed",
    "rejected",
    "on_hold",
]
TaskTypeLiteral = Literal["document_collection", "property_visit", "background_check"]
TaskStatusLiteral = Literal[
    "unassigned", "assigned", "in_progress", "completed", "cancelled", "blocked"
]
# A telecaller may only move a lead through these; new/assigned/released are
# system- or Admin-owned (design doc §4.1).
TelecallerLeadStatusLiteral = Literal["working", "converted", "closed"]
CallDispositionLiteral = Literal[
    "connected",
    "no_answer",
    "busy",
    "switched_off",
    "wrong_number",
    "callback_requested",
    "not_interested",
]
InterestLevelLiteral = Literal["hot", "warm", "cold"]
PropertyCategoryLiteral = Literal["houses", "apartments", "villas", "plots", "commercial"]
PropertySubtypeLiteral = Literal[
    "individual_house",
    "standalone_apartment",
    "gated_community_apartment",
    "villa",
    "locked_space",
    "unlocked_space",
    "plot",
    "farmland",
    "agriland",
]


class LeadReferrerRead(BaseModel):
    """Who brought a lead in, as an identifier only (no names or contacts).

    ``agent``: the introducing Agent's ``agent_code``. ``client``: the referral
    code of the client whose link the lead signed up through.
    """

    kind: Literal["agent", "client"]
    reference_id: str


class LeadTransactionItem(BaseModel):
    """One recorded transaction; a part the Admin hides is null."""

    txn_date: date | None = None
    bank_name: str | None = None
    # Rupees.
    amount: float | None = None


class LeadTransactionSummary(BaseModel):
    """Loan transactions recorded on a lead (FR-6.5), summarised for filters.

    Only for callers who may read the lead's transactions: the assigned
    Telecaller, or the Sub Admin managing that Telecaller's team. A part the
    Admin hides from Telecallers (bank name, amount, date) is null and named
    in ``hidden_fields``. ``items`` holds the latest 50 transactions, so a
    filter can require one transaction to match bank, date and amount together.
    """

    count: int
    # Distinct bank names as entered (trimmed), alphabetical.
    bank_names: list[str] | None = None
    # Smallest and largest transaction amount, in rupees.
    amount_min: float | None = None
    amount_max: float | None = None
    # Earliest and latest transaction date.
    first_date: date | None = None
    last_date: date | None = None
    items: list[LeadTransactionItem] = Field(default_factory=list)
    hidden_fields: list[Literal["bank_names", "amount", "dates"]] = Field(default_factory=list)


class LeadLoanFacet(BaseModel):
    """One loan application on the lead: product, lender and stage (labels
    included, so a filter can offer a product or bank no longer in the
    active catalogue)."""

    loan_type_id: UUID
    loan_type_label: str | None = None
    bank_id: UUID | None = None
    bank_name: str | None = None
    status: LoanStatusLiteral


class LeadDealFacet(BaseModel):
    """One property deal on the lead: stage and the property's kind."""

    status: PropertyDealStatusLiteral
    property_category: PropertyCategoryLiteral | None = None
    property_subtype: PropertySubtypeLiteral | None = None


class LeadFacets(BaseModel):
    """Product and property facts of a lead, for the list filters (CS-023).

    One entry per loan application (loans line) or property deal (real estate
    line), so a filter on product, bank and status matches one application.
    Ids and enums only; amounts are not included.
    """

    loans: list[LeadLoanFacet] = Field(default_factory=list)
    deals: list[LeadDealFacet] = Field(default_factory=list)


# Staff working notes (call logs, field tasks) allow about 1500 words. The
# columns are TEXT; this cap only bounds request size.
STAFF_NOTE_MAX_CHARS = 10_000


# What a client asked for: each kind maps to one lead_activities link column.
RequestKindLiteral = Literal[
    "loan_application",
    "financial_enquiry",
    "property_enquiry",
    "site_visit",
    "property_deal",
]


class RequestRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RequestKindLiteral
    id: UUID


class LeadRequestSummary(BaseModel):
    """One application/enquiry/visit/deal on a lead: what and when."""

    kind: RequestKindLiteral
    id: UUID
    title: str
    status: str
    applied_at: datetime


class LeadActivityCreate(BaseModel):
    disposition: CallDispositionLiteral
    interest_level: InterestLevelLiteral | None = None
    notes: Annotated[str | None, Field(default=None, max_length=STAFF_NOTE_MAX_CHARS)] = None
    follow_up_at: datetime | None = None
    # Optional: which request on this lead the call was about. Omit for a
    # general call. Validated server-side against the same lead.
    request: RequestRef | None = None

    @model_validator(mode="after")
    def _interest_level_matches_disposition(self) -> LeadActivityCreate:
        if self.disposition == "connected" and self.interest_level is None:
            raise ValueError("interest_level is required when disposition is 'connected'.")
        if self.disposition != "connected" and self.interest_level is not None:
            raise ValueError("interest_level is only set when disposition is 'connected'.")
        return self

    @model_validator(mode="after")
    def _follow_up_in_future(self) -> LeadActivityCreate:
        if self.follow_up_at is not None:
            now = datetime.now(UTC)
            follow_up = self.follow_up_at
            if follow_up.tzinfo is None:
                follow_up = follow_up.replace(tzinfo=UTC)
            if follow_up <= now:
                raise ValueError("follow_up_at must be in the future.")
        return self


class LeadActivityRead(BaseModel):
    id: UUID
    lead_uuid: UUID
    disposition: CallDispositionLiteral
    interest_level: InterestLevelLiteral | None
    notes: str | None
    follow_up_at: datetime | None
    created_at: datetime
    request: RequestRef | None = None


class TelecallerLeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TelecallerLeadStatusLiteral | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> TelecallerLeadUpdate:
        if self.status is None:
            raise ValueError("Provide status; qualification details belong in call activities.")
        return self


class TelecallerLeadRead(BaseModel):
    id: UUID
    lead_ref: LeadRef
    name: str | None = None
    mobile: str
    business_line: Literal["loans", "real_estate"]
    status: LeadStatusLiteral
    requirement: dict[str, Any] | None = None
    # The lead's stored product (loan, credit card or insurance) and its
    # label; null when unknown or ambiguous, and always on real estate.
    product_id: UUID | None = None
    product_label: str | None = None
    last_disposition: CallDispositionLiteral | None = None
    # Interest level recorded on that same latest call (set only when connected).
    last_interest_level: InterestLevelLiteral | None = None
    next_follow_up_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # The most recent application/enquiry/visit/deal on the lead, if any.
    latest_request: LeadRequestSummary | None = None
    # Distinct statuses across the lead's loan applications (empty for property leads).
    loan_statuses: list[LoanStatusLiteral] = Field(default_factory=list)
    # Absent when Admin hides the "Referred by" field; null when nobody referred.
    referrer: LeadReferrerRead | None = None
    # Products, banks and property facts of the lead (CS-023 list filters).
    facets: LeadFacets = Field(default_factory=LeadFacets)
    # Loan transactions recorded on the lead; null on the real estate line.
    transactions: LeadTransactionSummary | None = None
    # CS-028: how often and when the introducing Agent last resubmitted the
    # lead after its window ended (0 / null when never).
    resubmit_count: int = 0
    last_resubmitted_at: datetime | None = None


class LoanTxnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    amount: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    interest_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=6, decimal_places=3)]
    txn_date: date


class LoanTxnRead(BaseModel):
    id: UUID
    loan_application_uuid: UUID
    bank_name: str | None = None
    amount: Decimal | None = None
    interest_rate: Decimal | None = None
    txn_date: date | None = None
    created_at: datetime


class TelecallerLoanApplicationRead(BaseModel):
    id: UUID
    loan_type_id: UUID
    loan_type_name: str
    bank_id: UUID | None = None
    bank_name: str | None = None
    amount_requested: Decimal | None = None
    amount_sanctioned: Decimal | None = None
    interest_rate: Decimal | None = None
    processing_fee: Decimal | None = None
    fee_outcome: Literal["waived", "cashback", "none"] | None = None
    status: LoanStatusLiteral
    status_reason: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    txns: list[LoanTxnRead]
    form_version: int | None = None
    form_schema_snapshot: ProductFormDefinition | None = None
    form_answers: FormAnswers | None = None


class PropertyDealCreate(BaseModel):
    property_id: UUID


class TelecallerPropertyDealRead(BaseModel):
    id: UUID
    property_title: str
    property_location: str
    price_quoted: Decimal | None = None
    booking_amount: Decimal | None = None
    status: PropertyDealStatusLiteral
    status_reason: str | None = None
    site_visit_uuid: UUID | None
    opened_at: datetime
    closed_at: datetime | None


class TelecallerFinancialEnquiryRead(BaseModel):
    """A credit-card or insurance request (outside the loan pipeline)."""

    id: UUID
    product_name: str
    product_category: str
    status: str
    submitted_at: datetime


class TelecallerPropertyEnquiryRead(BaseModel):
    id: UUID
    property_ref: str
    title: str
    locality: str
    city: str
    message: str | None
    status: str
    created_at: datetime


class TelecallerSiteVisitRead(BaseModel):
    id: UUID
    property_ref: str
    title: str
    locality: str
    city: str
    preferred_date: date
    preferred_time_slot: str
    status: str
    created_at: datetime


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=STAFF_NOTE_MAX_CHARS),
    ]
    due_at: datetime | None = None

    @model_validator(mode="after")
    def _due_at_in_future(self) -> TaskCreate:
        if self.due_at is not None:
            due_at = self.due_at
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=UTC)
            if due_at <= datetime.now(UTC):
                raise ValueError("due_at must be in the future.")
        return self


class TaskRead(TaskStaffRead):
    id: UUID
    lead_uuid: UUID
    task_type: TaskTypeLiteral
    status: TaskStatusLiteral
    notes: str | None
    due_at: datetime | None
    assigned_employee_profile_uuid: UUID | None
    created_at: datetime


class ManagerNoteRead(BaseModel):
    """A Sub Admin manager's note on a lead or task (CS-020), read-only here."""

    id: UUID
    author_name: str
    body: str
    follow_up_at: datetime | None
    created_at: datetime


class TelecallerLeadDetailRead(TelecallerLeadRead):
    chat_inquiries: list[ChatInquiryRead] = Field(default_factory=list)
    activities: list[LeadActivityRead]
    loan_applications: list[TelecallerLoanApplicationRead] = []
    financial_enquiries: list[TelecallerFinancialEnquiryRead] = []
    property_enquiries: list[TelecallerPropertyEnquiryRead] = []
    site_visits: list[TelecallerSiteVisitRead] = []
    property_deals: list[TelecallerPropertyDealRead] = []
    tasks: list[TaskRead] = []
    manager_notes: list[ManagerNoteRead] = []


class ClientHistoryLead(BaseModel):
    """One lead (journey) of the same client, with this Telecaller's calls."""

    lead_id: UUID
    status: LeadStatusLiteral
    created_at: datetime
    requests: list[LeadRequestSummary]
    activities: list[LeadActivityRead]


class TelecallerClientHistoryResponse(BaseModel):
    """Every journey of this client on this line that is assigned to the
    caller, newest first. Calls are the caller's own (lead_activities_rls)."""

    business_line: Literal["loans", "real_estate"]
    leads: list[ClientHistoryLead]


class TelecallerFollowUpItem(BaseModel):
    lead_uuid: UUID
    name: str | None = None
    mobile: str
    follow_up_at: datetime
    latest_request: LeadRequestSummary | None = None


class TelecallerHomeResponse(BaseModel):
    follow_ups_due: list[TelecallerFollowUpItem]
    counts_by_status: dict[str, int]
