"""Transaction schemas — client lists own payout ledger. Read-only.

No create schema: transactions are never created via this router — a future
money-layer producer inserts rows on a bypass session, the same mechanism as
services.notifications.emit_notification.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.payout import PayoutDestination, PayoutStatus
from app.models.transaction import TransactionStatus, TransactionType


class TransactionRead(BaseModel):
    id: UUID
    type: TransactionType
    status: TransactionStatus
    amount_paise: int
    currency: str
    description: str
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionRead]


class TransactionSearchResponse(TransactionListResponse):
    total: int
    paid_amount_paise: int
    processing_count: int
    referral_count: int


class TransactionPaymentTrail(BaseModel):
    status: PayoutStatus
    method: PayoutDestination
    destination_hint: str
    reference: str | None
    requested_at: datetime
    approved_at: datetime | None
    issued_at: datetime | None
    paid_at: datetime | None
    reversed_at: datetime | None


class TransactionDetail(TransactionRead):
    display_id: str
    payment: TransactionPaymentTrail | None
