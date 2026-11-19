"""Per-loan-product commission rates with maker-checker (CS-028).

A Sub Admin proposes a rate for a loan product (``pending_approval``); a
platform Admin who is not the maker approves it (the previous ``approved``
row becomes ``superseded``) or rejects it with a note. A platform Admin's
own entry is approved at once with themselves as checker. The maker may
withdraw a pending proposal, and a new proposal from the same Sub Admin
replaces (withdraws) their earlier one.

The rate is either a percent of the loan amount (``percent_bps``, basis
points 1..10000) or a fixed amount (``amount_paise``). It is indicative: a
loans Agent sees the approved rate for the product they pick, and the Admin's
commission entry is pre-filled from it; the per-deal commission itself is
still entered by the Admin (``models/commission.py``).

Rows are append-only in substance: the trigger
``trg_product_commission_rates_transition`` keeps terms and maker fixed and
allows only ``pending_approval -> approved | rejected | withdrawn`` and
``approved -> superseded``. Access rules are in migration ``e4a6c8d0f2b3``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommissionRateKind(enum.StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"


class CommissionRateStatus(enum.StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


def _now() -> datetime:
    return datetime.now(UTC)


class ProductCommissionRate(Base):
    __tablename__ = "product_commission_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loan_types.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    percent_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CommissionRateStatus.PENDING_APPROVAL.value
    )
    created_by_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_role: Mapped[str] = mapped_column(String(16), nullable=False)
    checker_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
