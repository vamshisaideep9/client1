"""/api/v1/admin/teams — Sub Admin–led Telecaller / Employee teams (CS-019).

Every platform Admin may read teams. Only the Main Admin may create, change,
archive or staff them, because a team grants its Sub Admin manager read and
reassign reach over the members' client work. RLS enforces the same rule.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_platform_admin
from app.db.session import get_db
from app.schemas.staff_teams import (
    StaffTeamCreate,
    StaffTeamListResponse,
    StaffTeamRead,
    StaffTeamUpdate,
    TeamEligibleResponse,
    TeamLine,
    TeamMemberRoleLiteral,
)
from app.services.admin import is_primary_admin
from app.services.staff_teams import (
    InvalidTeamManager,
    InvalidTeamMember,
    ManagerAlreadyHasTeam,
    MemberAlreadyInTeam,
    TeamArchived,
    TeamMemberNotFound,
    TeamNotFound,
    add_member,
    create_team,
    eligible_people,
    list_teams,
    remove_member,
    update_team,
)

router = APIRouter()

_ERRORS: dict[type[Exception], tuple[int, str]] = {
    TeamNotFound: (status.HTTP_404_NOT_FOUND, "Team not found."),
    TeamMemberNotFound: (status.HTTP_404_NOT_FOUND, "That person is not in this team."),
    TeamArchived: (status.HTTP_409_CONFLICT, "This team is archived."),
    InvalidTeamManager: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Choose an active Sub Admin as the manager.",
    ),
    ManagerAlreadyHasTeam: (
        status.HTTP_409_CONFLICT,
        "This Sub Admin already manages a team in this business line.",
    ),
    InvalidTeamMember: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Choose an active staff member of this team's role and business line.",
    ),
    MemberAlreadyInTeam: (
        status.HTTP_409_CONFLICT,
        "This person is already in a team in this business line.",
    ),
}


def _http(exc: Exception) -> HTTPException:
    code, detail = _ERRORS[type(exc)]
    return HTTPException(status_code=code, detail=detail)


async def _require_main_admin(current_user: CurrentUser, db: AsyncSession) -> None:
    if not await is_primary_admin(
        db,
        auth_user_uuid=current_user.id,
        staff_profile_uuid=current_user.staff_profile_uuid,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the Main Admin may manage teams.",
        )


@router.get("", response_model=StaffTeamListResponse)
async def get_teams(
    response: Response,
    include_archived: bool = Query(False),
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffTeamListResponse:
    response.headers["Cache-Control"] = "private, no-store"
    can_edit = await is_primary_admin(
        db, auth_user_uuid=current_user.id, staff_profile_uuid=current_user.staff_profile_uuid
    )
    return StaffTeamListResponse(
        teams=await list_teams(db, include_archived=include_archived), can_edit=can_edit
    )


@router.get("/eligible", response_model=TeamEligibleResponse)
async def get_eligible(
    response: Response,
    business_line: TeamLine,
    member_role: TeamMemberRoleLiteral,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> TeamEligibleResponse:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_main_admin(current_user, db)
    return await eligible_people(db, business_line=business_line, member_role=member_role)


@router.post("", response_model=StaffTeamRead, status_code=status.HTTP_201_CREATED)
async def post_team(
    payload: StaffTeamCreate,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffTeamRead:
    await _require_main_admin(current_user, db)
    try:
        return await create_team(
            db, payload, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except (InvalidTeamManager, ManagerAlreadyHasTeam) as exc:
        raise _http(exc) from exc


@router.patch("/{team_id}", response_model=StaffTeamRead)
async def patch_team(
    team_id: UUID,
    payload: StaffTeamUpdate,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffTeamRead:
    await _require_main_admin(current_user, db)
    try:
        return await update_team(
            db, team_id, payload, actor_uuid=current_user.id, actor_role=current_user.role
        )
    except (TeamNotFound, TeamArchived, InvalidTeamManager, ManagerAlreadyHasTeam) as exc:
        raise _http(exc) from exc


@router.post("/{team_id}/members/{staff_profile_uuid}", response_model=StaffTeamRead)
async def post_member(
    team_id: UUID,
    staff_profile_uuid: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffTeamRead:
    await _require_main_admin(current_user, db)
    try:
        return await add_member(
            db,
            team_id,
            staff_profile_uuid,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, TeamArchived, InvalidTeamMember, MemberAlreadyInTeam) as exc:
        raise _http(exc) from exc


@router.delete("/{team_id}/members/{staff_profile_uuid}", response_model=StaffTeamRead)
async def delete_member(
    team_id: UUID,
    staff_profile_uuid: UUID,
    current_user: CurrentUser = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> StaffTeamRead:
    await _require_main_admin(current_user, db)
    try:
        return await remove_member(
            db,
            team_id,
            staff_profile_uuid,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, TeamArchived, TeamMemberNotFound) as exc:
        raise _http(exc) from exc
