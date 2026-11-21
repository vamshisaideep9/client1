"""Admin commission endpoints — entry against an eligible-deal queue,
oversight, and cancellation (FR-8.1/8.2, IDR v1.4 §5.5).

Gated by `deps.require_platform_admin` (feature-status.md §2-20), not the
role-only `deps.require_admin`: every RLS admin-bypass predicate in this
codebase is `role='admin' AND platform_scope='true'`. A line-scoped admin
who passed a role-only guard would get either a 403 further down or a
silently-empty result, neither of which is a substitute for a real 403 at
the boundary.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user, require_assignment, require_platform_admin
from app.db.session import get_db
from app.models.commission import Commission, CommissionStatus
from app.models.payout import Payout, PayoutType
from app.schemas.commissions import (
    BulkCommissionPayoutRequest,
    CommissionCancelRequest,
    CommissionCreate,
    CommissionListResponse,
    CommissionPayoutGroupList,
    CommissionPayoutRequest,
    CommissionPayoutResponse,
    CommissionRead,
    CoveredCommission,
    EligibleDealListResponse,
)
from app.schemas.sub_admin_access import ScopedCommission
from app.services import commission_payouts, commissions
from app.services import payments as payments_service

router = APIRouter()
_finance_view = require_assignment("account_manager", "view", include_admin=True)

# Same typed-error -> HTTP mapping convention as api/v1/referrals.py's
# _ERROR_STATUS, duplicated rather than imported cross-router: the two
# surfaces are independent HTTP boundaries and only share the exception
# TYPES (from services.payments), not a router-to-router dependency.
_PAYOUT_ERROR_STATUS = {
    payments_service.RecipientNotFound: status.HTTP_404_NOT_FOUND,
    payments_service.RecipientInactive: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.RecipientLineMismatch: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutAmountExceeded: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutDailyCapExceeded: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.PayoutCapNotConfigured: status.HTTP_422_UNPROCESSABLE_CONTENT,
    payments_service.DuplicatePayout: status.HTTP_409_CONFLICT,
    payments_service.SelfPayoutForbidden: status.HTTP_403_FORBIDDEN,
    payments_service.GatewayError: status.HTTP_502_BAD_GATEWAY,
}


def _map_error(exc: commissions.CommissionError) -> HTTPException:
    if isinstance(exc, (commissions.DealNotFound, commissions.CommissionNotFound)):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (commissions.DealNotEligible, commissions.CommissionAlreadyResolved)):
        code = status.HTTP_409_CONFLICT
    else:  # pragma: no cover — defensive default
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _map_payout_error(exc: payments_service.PayoutError) -> HTTPException:
    code = _PAYOUT_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/eligible", response_model=EligibleDealListResponse)
async def list_eligible(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> EligibleDealListResponse:
    await require_platform_admin(current_user)
    deals, total = await commissions.list_eligible_deals(db, limit=limit, offset=offset)
    return EligibleDealListResponse(deals=deals, total=total)


@router.post("", response_model=CommissionRead, status_code=status.HTTP_201_CREATED)
async def create_commission(
    payload: CommissionCreate,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommissionRead:
    await require_platform_admin(current_user)
    try:
        commission = await commissions.create_commission(
            db,
            deal_type=payload.deal_type,
            deal_uuid=payload.deal_uuid,
            agreed_amount_paise=payload.agreed_amount_paise,
            notes=payload.notes,
            entered_by_uuid=current_user.id,
            entered_by_role=current_user.role,
        )
    except commissions.CommissionError as exc:
        raise _map_error(exc) from exc
    await db.commit()

    read = await commissions.get_for_admin(db, commission.id)
    if read is None:  # pragma: no cover — the row we just committed must read back
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Commission entry failed to read back."
        )
    return read


@router.get("", response_model=CommissionListResponse)
async def list_commissions(
    status_filter: CommissionStatus | None = None,
    business_line: Literal["loans", "real_estate"] | None = None,
    agent_profile_uuid: UUID | None = None,
    awaiting_payout: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommissionListResponse:
    await require_platform_admin(current_user)
    rows, total = await commissions.list_for_admin(
        db,
        status_filter=status_filter,
        business_line=business_line,
        agent_profile_uuid=agent_profile_uuid,
        awaiting_payout=awaiting_payout,
        limit=limit,
        offset=offset,
    )
    return CommissionListResponse(commissions=rows, total=total)


@router.get("/scoped-summary", response_model=list[ScopedCommission])
async def scoped_commission_summary(
    user: CurrentUser = Depends(_finance_view),
    db: AsyncSession = Depends(get_db),
) -> list[ScopedCommission]:
    if user.sub_admin_access is None:
        await require_platform_admin(user)
    rows = await db.execute(
        select(
            Commission.id,
            Commission.business_line,
            Commission.status,
            Commission.agreed_amount_paise,
            Commission.created_at,
        )
        .order_by(Commission.created_at.desc(), Commission.id.desc())
        .limit(100)
    )
    return [ScopedCommission.model_validate(row) for row in rows.mappings()]


@router.get("/pending-payout-groups", response_model=CommissionPayoutGroupList)
async def list_pending_payout_groups(
    response: Response,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommissionPayoutGroupList:
    """Group every unlinked pending commission by Agent and business line."""
    await require_platform_admin(current_user)
    response.headers["Cache-Control"] = "private, no-store"
    return await commission_payouts.list_pending_groups(db, limit=limit, offset=offset)


@router.post("/{commission_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_commission(
    commission_id: UUID,
    payload: CommissionCancelRequest,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_platform_admin(current_user)
    try:
        await commissions.cancel_commission(
            db,
            commission_id=commission_id,
            reason=payload.reason,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except commissions.CommissionError as exc:
        raise _map_error(exc) from exc
    await db.commit()


@router.post(
    "/bulk-payout",
    response_model=CommissionPayoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bulk_commission_payout(
    req: BulkCommissionPayoutRequest,
    current_user: CurrentUser = Depends(get_active_user),
) -> CommissionPayoutResponse:
    """Create one payout from selected pending commissions for the same Agent."""
    return await _create_commission_payout(req.commission_ids, req, current_user, bulk=True)


@router.get("/payouts/{payout_id}/items", response_model=list[CoveredCommission])
async def list_covered_commissions(
    payout_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[CoveredCommission]:
    await require_platform_admin(current_user)
    payout = await db.get(Payout, payout_id)
    if payout is None or payout.type != PayoutType.COMMISSION:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commission payout not found.")
    response.headers["Cache-Control"] = "private, no-store"
    return await commission_payouts.list_items(db, payout_id)


@router.post(
    "/{commission_id}/payout",
    response_model=CommissionPayoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_commission_payout(
    commission_id: UUID,
    req: CommissionPayoutRequest,
    current_user: CurrentUser = Depends(get_active_user),
) -> CommissionPayoutResponse:
    """Create a payout for a single pending commission."""
    return await _create_commission_payout([commission_id], req, current_user, bulk=False)


async def _create_commission_payout(
    ids: list[UUID], req: CommissionPayoutRequest, current_user: CurrentUser, *, bulk: bool
) -> CommissionPayoutResponse:
    await require_platform_admin(current_user)
    try:
        payout_id = await commission_payouts.create_for_commissions(
            ids, req, maker_uuid=current_user.id, maker_role=current_user.role, bulk=bulk
        )
    except commissions.CommissionError as exc:
        raise _map_error(exc) from exc
    except payments_service.PayoutError as exc:
        raise _map_payout_error(exc) from None
    return CommissionPayoutResponse(payout_id=payout_id)
