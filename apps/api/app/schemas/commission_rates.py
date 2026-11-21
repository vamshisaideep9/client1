"""Per-loan-product commission rate schemas (CS-028).

Money is integer paise; a percent rate is basis points (``percent_bps``:
1..10000, so 150 = 1.5 %). A rate is indicative: it pre-fills the Admin's
per-deal commission entry and is shown to loans Agents for the product they
pick; it is never part of any public or Client response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CommissionRateKindLiteral = Literal["percent", "fixed"]
CommissionRateStatusLiteral = Literal[
    "pending_approval", "approved", "rejected", "superseded", "withdrawn"
]

# Same per-commission ceiling as CommissionCreate.agreed_amount_paise.
MAX_FIXED_COMMISSION_PAISE = 10_000_000_000


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CommissionRateInput(BaseModel):
    """Propose (Sub Admin) or set (platform Admin) a product's rate."""

    model_config = ConfigDict(extra="forbid")

    kind: CommissionRateKindLiteral
    percent_bps: Annotated[int, Field(ge=1, le=10_000)] | None = None
    amount_paise: Annotated[int, Field(ge=1, le=MAX_FIXED_COMMISSION_PAISE)] | None = None
    note: Annotated[str, Field(max_length=280)] | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _one_amount(self) -> CommissionRateInput:
        if self.kind == "percent" and (self.percent_bps is None or self.amount_paise is not None):
            raise ValueError("A percent rate needs percent_bps and no amount_paise.")
        if self.kind == "fixed" and (self.amount_paise is None or self.percent_bps is not None):
            raise ValueError("A fixed rate needs amount_paise and no percent_bps.")
        return self


class CommissionRateApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, Field(max_length=500)] | None = None

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class CommissionRateReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("note")
    @classmethod
    def _note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Say why the rate is rejected.")
        return value


class CommissionRateRead(BaseModel):
    id: UUID
    loan_type_id: UUID
    kind: CommissionRateKindLiteral
    percent_bps: int | None
    amount_paise: int | None
    note: str | None
    status: CommissionRateStatusLiteral
    created_by_uuid: UUID
    created_by_name: str | None
    created_by_role: Literal["admin", "sub_admin"]
    # True when the caller made this entry (a Sub Admin may withdraw it).
    is_mine: bool
    checker_name: str | None
    reviewed_at: datetime | None
    review_note: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ProductCommissionRates(BaseModel):
    """One loan product: its approved rate, any proposal awaiting approval,
    and up to 20 earlier entries (newest first)."""

    loan_type_id: UUID
    product_slug: str
    product_label: str
    product_active: bool
    current: CommissionRateRead | None
    pending: CommissionRateRead | None
    history: list[CommissionRateRead]


class CommissionRateListResponse(BaseModel):
    products: list[ProductCommissionRates]


class AgentCommissionRateRead(BaseModel):
    """The approved rate a loans Agent sees for a product they can offer."""

    loan_type_id: UUID
    product_label: str
    kind: CommissionRateKindLiteral
    percent_bps: int | None
    amount_paise: int | None
    note: str | None
    approved_at: datetime | None


class AgentCommissionRatesResponse(BaseModel):
    # Keyed by product slug (``loan_types.name``, the lead form's
    # ``requirement.product_slug``). Empty for a real-estate Agent.
    rates: dict[str, AgentCommissionRateRead]
