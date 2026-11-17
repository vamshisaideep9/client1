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
    ContestRead,
    ContestReject,
)
from app.services import contests as contest_service

router = APIRouter()

_ERROR_STATUS = {
    contest_service.ContestNotFound: status.HTTP_404_NOT_FOUND,
    contest_service.ContestNotOwned: status.HTTP_403_FORBIDDEN,
    contest_service.ContestMakerChecker: status.HTTP_403_FORBIDDEN,
    contest_service.ContestStateError: status.HTTP_409_CONFLICT,
    contest_service.ContestInvalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def map_contest_error(exc: contest_service.ContestError) -> HTTPException:
    code = _ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code=code, detail=str(exc) or "Contest request failed.")


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
    current_user: CurrentUser = Depends(require_sub_admin),
    db: AsyncSession = Depends(get_db),
) -> ContestRead:
    """The maker cancels a contest that has not been approved."""
    try:
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
