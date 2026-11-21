"""Read-only payout ledger with server-scoped history and detail."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user
from app.db.session import get_db
from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.transactions import (
    TransactionDetail,
    TransactionListResponse,
    TransactionSearchResponse,
)
from app.services import transactions
from app.services.transactions import TransactionFilters

router = APIRouter()


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionListResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return TransactionListResponse(
        transactions=await transactions.list_transactions(db, current_user)
    )


@router.get("/search", response_model=TransactionSearchResponse)
async def search_transactions(
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    type: TransactionType | None = None,
    status_filter: TransactionStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount_paise: int | None = Query(default=None, ge=-10_000_000_000, le=10_000_000_000),
    max_amount_paise: int | None = Query(default=None, ge=-10_000_000_000, le=10_000_000_000),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionSearchResponse:
    """Search visible ledger entries. Metrics cover the full filtered result."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The start date must precede the end date."
        )
    if (
        min_amount_paise is not None
        and max_amount_paise is not None
        and min_amount_paise > max_amount_paise
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The minimum amount must not exceed the maximum."
        )
    response.headers["Cache-Control"] = "private, no-store"
    return await transactions.search_transactions(
        db,
        current_user,
        TransactionFilters(
            q, type, status_filter, date_from, date_to, min_amount_paise, max_amount_paise
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/{transaction_id}", response_model=TransactionDetail)
async def transaction_detail(
    transaction_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionDetail:
    detail = await transactions.transaction_detail(db, current_user, transaction_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found.")
    response.headers["Cache-Control"] = "private, no-store"
    return detail
