"""Per-loan-product commission rates (CS-028): Sub Admin maker, platform Admin
checker. The loans Agent's read is ``GET /api/v1/agent/commission-rates``.

Every route needs a Sub Admin or a platform Admin (line-scoped Admins are
refused, like every other platform-wide configuration surface). Proposals and
withdrawals are Sub Admin-only; approval and rejection are platform Admin-only;
``PUT`` is a proposal for a Sub Admin and an immediately approved entry for a
platform Admin. RLS on ``product_commission_rates`` is the wall behind these
gates. Rates never appear on public or Client endpoints.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    is_platform_admin,
    require_platform_admin,
    require_sub_admin,
    require_sub_admin_or_platform_admin,
)
from app.db.session import get_db
from app.schemas.commission_rates import (
    CommissionRateApprove,
    CommissionRateInput,
    CommissionRateListResponse,
    CommissionRateReject,
    ProductCommissionRates,
)
from app.services import commission_rates as service

router = APIRouter()

_ERROR_STATUS: dict[type[service.CommissionRateError], int] = {
    service.ProductNotFound: status.HTTP_404_NOT_FOUND,
    service.RateNotFound: status.HTTP_404_NOT_FOUND,
    service.RateNotOwned: status.HTTP_403_FORBIDDEN,
    service.RateMakerChecker: status.HTTP_403_FORBIDDEN,
    service.RateStateError: status.HTTP_409_CONFLICT,
    service.RateConflict: status.HTTP_409_CONFLICT,
}


def _error(exc: service.CommissionRateError) -> HTTPException:
    return HTTPException(_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST), str(exc))


@router.get("", response_model=CommissionRateListResponse)
async def list_rates(
    response: Response,
    current_user: CurrentUser = Depends(require_sub_admin_or_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> CommissionRateListResponse:
    """Every loan product with its approved rate, any proposal awaiting
    approval, and up to 20 earlier entries with maker and checker names."""
    response.headers["Cache-Control"] = "private, no-store"
    products = await service.list_for_staff(db, viewer_uuid=current_user.id)
    return CommissionRateListResponse(products=products)


@router.put("/{loan_type_id}", response_model=ProductCommissionRates)
async def set_rate(
    loan_type_id: UUID,
    payload: CommissionRateInput,
    response: Response,
    current_user: CurrentUser = Depends(require_sub_admin_or_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductCommissionRates:
    """Sub Admin: propose a rate (awaits a platform Admin; replaces your own
    earlier proposal). Platform Admin: set the rate now."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        if is_platform_admin(current_user):
            await service.set_by_admin(
                loan_type_id,
                payload,
                admin_uuid=current_user.id,
                admin_role=current_user.role,
            )
        else:
            await service.propose(db, loan_type_id, payload, actor_uuid=current_user.id)
    except service.CommissionRateError as exc:
        raise _error(exc) from exc
    return await service.product_for_staff(db, loan_type_id, viewer_uuid=current_user.id)


@router.post("/{rate_id}/approve", response_model=ProductCommissionRates)
async def approve_rate(
    rate_id: UUID,
    response: Response,
    payload: CommissionRateApprove | None = None,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductCommissionRates:
    """Approve a Sub Admin's proposal; the previous approved rate is superseded."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        rate = await service.approve(
            rate_id,
            reviewer_uuid=current_user.id,
            reviewer_role=current_user.role,
            note=payload.note if payload else None,
        )
    except service.CommissionRateError as exc:
        raise _error(exc) from exc
    return await service.product_for_staff(db, rate.loan_type_id, viewer_uuid=current_user.id)


@router.post("/{rate_id}/reject", response_model=ProductCommissionRates)
async def reject_rate(
    rate_id: UUID,
    payload: CommissionRateReject,
    response: Response,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductCommissionRates:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        rate = await service.reject(
            rate_id,
            reviewer_uuid=current_user.id,
            reviewer_role=current_user.role,
            note=payload.note,
        )
    except service.CommissionRateError as exc:
        raise _error(exc) from exc
    return await service.product_for_staff(db, rate.loan_type_id, viewer_uuid=current_user.id)


@router.post("/{rate_id}/withdraw", response_model=ProductCommissionRates)
async def withdraw_rate(
    rate_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductCommissionRates:
    """The proposing Sub Admin takes back a rate awaiting approval."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        rate = await service.withdraw(db, rate_id, actor_uuid=current_user.id)
    except service.CommissionRateError as exc:
        raise _error(exc) from exc
    return await service.product_for_staff(db, rate.loan_type_id, viewer_uuid=current_user.id)
