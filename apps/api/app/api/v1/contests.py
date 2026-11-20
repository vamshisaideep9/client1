"""Contest management (CS-027): Sub Admin authoring, platform Admin review.

Every route depends on an authenticated guard, so the RLS context is
installed. Sub Admins author and act on their own contests through the
``contests_*`` policies; review commands are platform-Admin only and run in
``services/contests.py`` on the bypass session with the maker-checker check.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    is_platform_admin,
    require_platform_admin,
    require_sub_admin,
    require_sub_admin_or_platform_admin,
)
from app.db.session import get_db
from app.models.contest import ContestAudience, ContestStatus
from app.schemas.contests import (
    ContestCancel,
    ContestDefinition,
    ContestListResponse,
    ContestPrizeMarkPaid,
    ContestPrizePayoutResponse,
    ContestRead,
    ContestReject,
    ContestResultPayment,
    ContestStandingsResponse,
)
from app.schemas.payments import ContestPrizePayoutRequest
from app.services import contest_awards, contest_views
from app.services import contests as contest_service
from app.services import payments as payments_service

router = APIRouter()

_ERROR_STATUS = {
    contest_service.ContestNotFound: status.HTTP_404_NOT_FOUND,
    contest_service.ContestNotOwned: status.HTTP_403_FORBIDDEN,
    contest_service.ContestMakerChecker: status.HTTP_403_FORBIDDEN,
    contest_service.ContestStateError: status.HTTP_409_CONFLICT,
    contest_service.ContestInvalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


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


def map_contest_error(exc: contest_service.ContestError) -> HTTPException:
    code = next(
        (_ERROR_STATUS[kind] for kind in type(exc).__mro__ if kind in _ERROR_STATUS),
        status.HTTP_400_BAD_REQUEST,
    )
    return HTTPException(status_code=code, detail=str(exc) or "Contest request failed.")


def _map_payout_error(exc: payments_service.PayoutError) -> HTTPException:
    code = _PAYOUT_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code=code, detail=str(exc))


async def _read(contest, viewer: CurrentUser) -> ContestRead:
    return (await contest_service.reads_for([contest], viewer.id))[0]


@router.get("", response_model=ContestListResponse)
async def list_contests(
    status_filter: list[ContestStatus] | None = Query(default=None, alias="status"),
    audience: ContestAudience | None = None,
    business_line: Literal["loans", "real_estate"] | None = None,
    q: str | None = Query(default=None, max_length=80),
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_sub_admin_or_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestListResponse:
    rows, total = await contest_service.list_contests(
        db,
        statuses=[value.value for value in status_filter] if status_filter else None,
        audience=audience.value if audience else None,
        business_line=business_line,
        search=q,
        mine_only_for=current_user.id if mine else None,
        limit=limit,
        offset=offset,
    )
    return ContestListResponse(
        contests=await contest_service.reads_for(rows, current_user.id), total=total
    )


@router.post("", response_model=ContestRead, status_code=status.HTTP_201_CREATED)
async def create_contest(
    payload: ContestDefinition,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    try:
        contest = await contest_service.create_contest(
            db, payload, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.get("/{contest_id}", response_model=ContestRead)
async def get_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_sub_admin_or_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    try:
        contest = await contest_service.get_contest(db, contest_id)
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.get("/{contest_id}/standings", response_model=ContestStandingsResponse)
async def contest_standings(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestStandingsResponse:
    """Full standings with names: live while running, the snapshot after."""
    try:
        return await contest_views.admin_standings(db, contest_id, current_user.id)
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc


@router.put("/{contest_id}", response_model=ContestRead)
async def update_contest(
    contest_id: UUID,
    payload: ContestDefinition,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    try:
        contest = await contest_service.update_contest(
            db, contest_id, payload, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.delete("/{contest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await contest_service.delete_contest(
            db, contest_id, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc


@router.post("/{contest_id}/submit", response_model=ContestRead)
async def submit_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    try:
        contest = await contest_service.submit_contest(
            db, contest_id, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post("/{contest_id}/withdraw", response_model=ContestRead)
async def withdraw_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    try:
        contest = await contest_service.withdraw_contest(
            db, contest_id, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post("/{contest_id}/cancel", response_model=ContestRead)
async def cancel_contest(
    contest_id: UUID,
    payload: ContestCancel,
    current_user: CurrentUser = Depends(require_sub_admin_or_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    """The maker (Sub Admin) cancels a contest that has not been approved; a
    platform Admin who is not the maker cancels an approved, live or ended
    one. A finalized contest cannot be cancelled."""
    try:
        if is_platform_admin(current_user):
            contest = await contest_awards.admin_cancel(
                contest_id,
                reason=payload.reason,
                actor_uuid=current_user.id,
                actor_role=current_user.role,
            )
        else:
            contest = await contest_service.cancel_by_maker(
                db,
                contest_id,
                reason=payload.reason,
                actor_uuid=current_user.id,
                actor_role=current_user.role,
            )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post("/{contest_id}/recalculate", response_model=ContestRead)
async def recalculate_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestRead:
    """Re-snapshot an ended contest's standings from live data."""
    try:
        contest = await contest_awards.recalculate(
            contest_id, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post("/{contest_id}/finalize", response_model=ContestRead)
async def finalize_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestRead:
    """Confirm the winners of an ended contest; prizes become owed."""
    try:
        contest = await contest_awards.finalize(
            contest_id, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post(
    "/{contest_id}/results/{result_id}/payout",
    response_model=ContestPrizePayoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_prize_payout(
    contest_id: UUID,
    result_id: UUID,
    req: ContestPrizePayoutRequest,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestPrizePayoutResponse:
    """Maker step for an Agent prize: one contest_reward payout, always
    approved at POST /payouts/{id}/approve by a different Admin."""
    try:
        payout_id = await contest_awards.request_agent_prize_payout(
            contest_id,
            result_id,
            destination_type=req.destination_type,
            destination=req.destination.model_dump(),
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    except payments_service.PayoutError as exc:
        raise _map_payout_error(exc) from None
    return ContestPrizePayoutResponse(payout_id=payout_id)


@router.post("/{contest_id}/results/{result_id}/mark-paid", response_model=ContestResultPayment)
async def mark_prize_paid(
    contest_id: UUID,
    result_id: UUID,
    payload: ContestPrizeMarkPaid,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestResultPayment:
    """Record a staff prize as paid outside Payouts (audited)."""
    try:
        row = await contest_awards.mark_staff_prize_paid(
            contest_id,
            result_id,
            reference=payload.reference,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return ContestResultPayment(
        result_id=row.id,
        payment_status=row.payment_status,
        paid_marked_at=row.paid_marked_at,
        paid_reference=row.paid_reference,
    )


@router.post("/{contest_id}/approve", response_model=ContestRead)
async def approve_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestRead:
    try:
        contest = await contest_service.approve_contest(
            contest_id, reviewer_uuid=current_user.id, reviewer_role=current_user.role
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)


@router.post("/{contest_id}/reject", response_model=ContestRead)
async def reject_contest(
    contest_id: UUID,
    payload: ContestReject,
    current_user: CurrentUser = Depends(require_platform_admin),
) -> ContestRead:
    try:
        contest = await contest_service.reject_contest(
            contest_id,
            reviewer_uuid=current_user.id,
            reviewer_role=current_user.role,
            note=payload.note,
        )
    except contest_service.ContestError as exc:
        raise map_contest_error(exc) from exc
    return await _read(contest, current_user)
