"""Participant contest pages (CS-027): Agents, Telecallers, Employees and the
Sub Admins who manage teams.

Every route installs the RLS context through ``get_active_user``; which
contests a caller sees is decided by ``contests_select`` and narrowed in
``services/contest_views.py`` to the teams they belong to or manage.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user
from app.db.session import get_db
from app.schemas.contests import MyContestDetail, MyContestListResponse
from app.services import contest_views
from app.services.contests import ContestNotFound

router = APIRouter()

_PARTICIPANT_ROLES = frozenset({"agent", "telecaller", "employee", "sub_admin"})


def _require_participant(user: CurrentUser) -> None:
    if user.role not in _PARTICIPANT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contests are for Agents, Telecallers, Employees and team managers.",
        )


@router.get("", response_model=MyContestListResponse)
async def list_my_contests(
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> MyContestListResponse:
    _require_participant(current_user)
    return MyContestListResponse(contests=await contest_views.list_my_contests(db, current_user))


@router.get("/{contest_id}", response_model=MyContestDetail)
async def get_my_contest(
    contest_id: UUID,
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> MyContestDetail:
    _require_participant(current_user)
    try:
        return await contest_views.get_my_contest(db, current_user, contest_id)
    except ContestNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
