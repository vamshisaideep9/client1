"""Request-scoped reads for the identity-owned payout ledger."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, is_platform_admin
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.schemas.transactions import (
    TransactionDetail,
    TransactionPaymentTrail,
    TransactionRead,
    TransactionSearchResponse,
)
from app.services.agent_dashboard import IST


@dataclass(frozen=True)
class TransactionFilters:
    query: str | None = None
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_amount_paise: int | None = None
    max_amount_paise: int | None = None


def _visible_to(viewer: CurrentUser):
    owner = Transaction.user_uuid == viewer.id
    if is_platform_admin(viewer):
        return True
    if viewer.role == "sub_admin" and viewer.platform_scope == "true":
        return or_(owner, Transaction.type == TransactionType.REFERRAL_BONUS)
    return owner


def _ordered_transactions(viewer: CurrentUser):
    return (
        select(Transaction)
        .where(_visible_to(viewer))
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
    )


async def list_transactions(db: AsyncSession, viewer: CurrentUser) -> list[TransactionRead]:
    rows = await db.scalars(_ordered_transactions(viewer))
    return [TransactionRead.model_validate(row, from_attributes=True) for row in rows]


async def search_transactions(
    db: AsyncSession, viewer: CurrentUser, filters: TransactionFilters, *, limit: int, offset: int
) -> TransactionSearchResponse:
    conditions = []
    if query := (filters.query or "").strip():
        transaction_id = query.lower().removeprefix("txn-")
        conditions.append(
            or_(
                cast(Transaction.id, String).icontains(transaction_id or query, autoescape=True),
                Transaction.description.icontains(query, autoescape=True),
            )
        )
    if filters.type is not None:
        conditions.append(Transaction.type == filters.type)
    if filters.status is not None:
        conditions.append(Transaction.status == filters.status)
    if filters.date_from is not None:
        conditions.append(
            Transaction.created_at >= datetime.combine(filters.date_from, time.min, IST)
        )
    if filters.date_to is not None and filters.date_to < date.max:
        upper = datetime.combine(filters.date_to + timedelta(days=1), time.min, IST)
        conditions.append(Transaction.created_at < upper)
    if filters.min_amount_paise is not None:
        conditions.append(Transaction.amount_paise >= filters.min_amount_paise)
    if filters.max_amount_paise is not None:
        conditions.append(Transaction.amount_paise <= filters.max_amount_paise)

    totals = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(Transaction.amount_paise).filter(
                        Transaction.status == TransactionStatus.PAID
                    ),
                    0,
                ),
                func.count().filter(
                    Transaction.status.in_(
                        (TransactionStatus.PENDING, TransactionStatus.PROCESSING)
                    )
                ),
                func.count().filter(Transaction.type == TransactionType.REFERRAL_BONUS),
            )
            .select_from(Transaction)
            .where(_visible_to(viewer), *conditions)
        )
    ).one()
    rows = await db.scalars(
        _ordered_transactions(viewer).where(*conditions).limit(limit).offset(offset)
    )
    return TransactionSearchResponse(
        transactions=[TransactionRead.model_validate(row, from_attributes=True) for row in rows],
        total=totals[0],
        paid_amount_paise=totals[1],
        processing_count=totals[2],
        referral_count=totals[3],
    )


async def transaction_detail(
    db: AsyncSession, viewer: CurrentUser, transaction_id: UUID
) -> TransactionDetail | None:
    row = await db.scalar(
        select(Transaction).where(Transaction.id == transaction_id, _visible_to(viewer))
    )
    if row is None:
        return None
    trail = await db.scalar(select(func.transaction_payment_trail(row.id, type_=JSONB)))
    return TransactionDetail(
        **TransactionRead.model_validate(row, from_attributes=True).model_dump(),
        display_id=f"TXN-{row.id}",
        payment=TransactionPaymentTrail.model_validate(trail) if trail is not None else None,
    )
