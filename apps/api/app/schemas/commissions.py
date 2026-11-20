"""Commission schemas — Admin entry against an eligible-deal queue (PR 1),
Admin oversight, and the agent's own read-only earnings ledger.

`CommissionCreate` deliberately carries no agent, line, or lead — those are
derived server-side from the deal row (`services/commissions.py::create_commission`),
never accepted from the request, the same discipline `ReferralPayoutRequest`
uses for amount/recipient.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.payout import PayoutDestination, PayoutProvider, PayoutStatus
from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.payments import PayoutDestinationInput, validate_destination

DealType = Literal["loan_application", "property_deal"]


class EligibleDealCommissionRate(BaseModel):
    """The product's approved indicative rate (CS-028) at the time of reading."""

    id: UUID
    kind: Literal["percent", "fixed"]
    # Basis points (150 = 1.5 %) for a percent rate; paise for a fixed one.
    percent_bps: int | None
    amount_paise: int | None
    note: str | None


class EligibleDeal(BaseModel):
    """One row in the Admin entry queue: a disbursed loan or a closed_won
    property deal with an origin agent and no live commission yet."""

    deal_type: DealType
    deal_uuid: UUID
    business_line: str
    agent_profile_uuid: UUID
    agent_code: str
    agent_name: str | None
    lead_uuid: UUID
    # The date this deal became commission-eligible: disbursed_at for a loan
    # (DISBURSED is not terminal — a loan can move on to CLOSED afterward,
    # so this is an event marker, not live status), closed_at for a property
    # deal (CLOSED genuinely is terminal there).
    eligible_since: datetime | None
    # CS-028 pre-fill, loans only (null for property deals): the loan's
    # product, its current approved rate, and the suggested commission —
    # the fixed amount, or the percent of the sanctioned amount (requested
    # when none was sanctioned) in integer paise rounded half up. The Admin
    # still enters the commission amount; this only pre-fills it.
    loan_type_id: UUID | None = None
    product_label: str | None = None
    commission_rate: EligibleDealCommissionRate | None = None
    suggested_amount_paise: int | None = None
    suggestion_basis: Literal["sanctioned", "requested", "fixed"] | None = None
    basis_amount_paise: int | None = None


class EligibleDealListResponse(BaseModel):
    deals: list[EligibleDeal]
    total: int


class CommissionCreate(BaseModel):
    deal_type: DealType
    deal_uuid: UUID
    agreed_amount_paise: int = Field(gt=0, le=10_000_000_000)
    notes: str | None = Field(default=None, max_length=1000)


class CommissionRead(BaseModel):
    id: UUID
    agent_profile_uuid: UUID
    agent_code: str
    agent_name: str | None
    business_line: str
    deal_type: DealType
    deal_uuid: UUID
    agreed_amount_paise: int
    status: str
    payout_uuid: UUID | None
    notes: str | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime


class CommissionListResponse(BaseModel):
    commissions: list[CommissionRead]
    total: int


class CommissionCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


CommissionStatusLiteral = Literal["pending", "paid", "cancelled"]


class AgentEarningsRow(BaseModel):
    """One commission in the Agent's history (CS-022).

    ``client_name`` follows the Admin's Agent "Lead name" rule and
    ``deal_amount`` the Agent "Loan and deal amounts" rule; a hidden value is
    null and listed in the response's ``hidden_fields``.
    """

    id: UUID
    business_line: str
    deal_type: DealType
    deal_uuid: UUID
    agreed_amount_paise: int
    status: CommissionStatusLiteral
    payout_txn_uuid: UUID | None
    created_at: datetime
    lead_uuid: UUID | None
    lead_status: str | None
    client_name: str | None
    product_uuid: UUID | None
    product_label: str | None
    bank_uuid: UUID | None
    bank_name: str | None
    property_uuid: UUID | None
    property_title: str | None
    property_category: str | None
    deal_status: str | None
    deal_amount: Decimal | None
    # When the settled ledger row was written (null until paid).
    paid_at: datetime | None


class AgentEarningsTotals(BaseModel):
    """Totals over every commission the Agent has on this line (filters do not
    change them). ``last_month_*`` is the previous calendar month in IST."""

    pending_amount_paise: int
    paid_amount_paise: int
    total_amount_paise: int
    last_month_paid_amount_paise: int
    last_month_start: date | None
    last_month_end: date | None


class AgentEarningsResponse(BaseModel):
    rows: list[AgentEarningsRow]
    totals: AgentEarningsTotals
    # Agent field rules the Admin switched off ("client_name", "deal_amount").
    hidden_fields: list[str]


class AgentPayoutActor(BaseModel):
    """A staff member on the payout trail: display name (null when the Admin
    hides payout staff names) and staff role."""

    name: str | None
    role: str | None


class AgentPayoutTrail(BaseModel):
    status: PayoutStatus
    method: PayoutDestination
    provider: PayoutProvider
    # Already masked at payout creation (never the raw UPI ID or account).
    destination_hint: str
    requested_at: datetime
    approved_at: datetime | None
    issued_at: datetime | None
    paid_at: datetime | None
    reversed_at: datetime | None
    requested_by: AgentPayoutActor | None
    approved_by: AgentPayoutActor | None
    # "standalone": the Main Admin approved their own request (no checker).
    approval_mode: Literal["maker_checker", "standalone"] | None


class AgentTransactionItem(BaseModel):
    """What a payout paid. Each payout pays exactly one commission today."""

    commission_id: UUID
    amount_paise: int
    status: CommissionStatusLiteral
    deal_type: DealType
    deal_uuid: UUID
    lead_uuid: UUID
    client_name: str | None
    product_label: str | None
    bank_name: str | None
    property_title: str | None
    deal_status: str | None
    deal_amount: Decimal | None
    entered_at: datetime


class AgentTransactionDetail(BaseModel):
    id: UUID
    type: TransactionType
    status: TransactionStatus
    amount_paise: int
    currency: str
    description: str
    created_at: datetime
    payout: AgentPayoutTrail | None
    items: list[AgentTransactionItem]
    # Agent field rules the Admin switched off ("client_name", "deal_amount",
    # "staff_names").
    hidden_fields: list[str]


class CommissionPayoutRequest(BaseModel):
    """No amount, no recipient: both come from the commission row
    (services/commissions.py::attach_payout), never the request body — same
    invariant as ReferralPayoutRequest. The idempotency key is derived
    server-side from the commission id (`com-{uuid.hex}`), not accepted from
    the client, for the identical reason ReferralPayoutRequest's docstring
    records: a client-chosen key let two concurrent "Pay commission" clicks
    each pick a fresh key and both slip past create_payout's dedupe guard."""

    destination_type: PayoutDestination
    destination: PayoutDestinationInput

    @model_validator(mode="after")
    def _require_matching_destination(self) -> CommissionPayoutRequest:
        validate_destination(self.destination_type, self.destination)
        return self


class CommissionPayoutResponse(BaseModel):
    payout_id: UUID
