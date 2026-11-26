"""/api/v1/manager — a Sub Admin manager's own team (CS-019, CS-020).

The team is always resolved together with the caller's own staff profile from
the verified token; ids in the path only select within that. RLS
(``team_manager_reaches``) independently limits every row to the caller's live
teams, so a Sub Admin without a team sees nothing. Edits run through confined
database functions that re-check reach, line and the allowed change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, check_assignment_line, require_assignment
from app.core.lead_reference import lead_number_filter
from app.db.session import get_db
from app.models.staff_team import StaffTeam
from app.schemas.staff_analytics import StaffAnalyticsResponse
from app.schemas.staff_teams import (
    ManagerTeamsResponse,
    TeamLeadDetailResponse,
    TeamLeadStatusUpdate,
    TeamMemberWorkResponse,
    TeamNoteCreate,
    TeamOverviewResponse,
    TeamReassignRequest,
    TeamReassignResponse,
    TeamTaskDetailResponse,
    TeamTaskUpdate,
    TeamWorkNoteRead,
    TeamWorkResponse,
    TeamWorkUpdateResponse,
)
from app.schemas.telecaller import PropertyCategoryLiteral, PropertySubtypeLiteral
from app.services.staff_analytics import (
    AMOUNT_LIMIT,
    AnalyticsWindow,
    InvalidAnalyticsWindow,
    resolve_analytics_window,
)
from app.services.team_manager import (
    InvalidFollowUp,
    InvalidReassignTarget,
    MemberNotInTeam,
    TeamAnalyticsQuery,
    TeamNotFound,
    UnsupportedAnalyticsFilter,
    WorkNotEditable,
    WorkNotFound,
    WorkNotReassignable,
    add_note,
    lead_detail,
    list_my_teams,
    member_analytics,
    member_work,
    reassign_lead,
    reassign_task,
    set_lead_status,
    task_detail,
    team_overview,
    team_work,
    update_task,
)

team_view = require_assignment("team_manager", "view")
_team_edit_user = require_assignment("team_manager", "edit")


async def team_edit(
    team_id: UUID,
    user: CurrentUser = Depends(_team_edit_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if user.sub_admin_access is not None:
        line = await db.scalar(
            select(StaffTeam.business_line).where(
                StaffTeam.id == team_id,
                StaffTeam.manager_staff_profile_uuid == user.staff_profile_uuid,
            )
        )
        if line is None:
            raise HTTPException(404, detail="Team not found.")
        check_assignment_line(user, "team_manager", "edit", line)
    return user


router = APIRouter()

_ERRORS: dict[type[Exception], tuple[int, str]] = {
    TeamNotFound: (status.HTTP_404_NOT_FOUND, "Team not found."),
    MemberNotInTeam: (status.HTTP_404_NOT_FOUND, "That person is not in your team."),
    WorkNotFound: (status.HTTP_404_NOT_FOUND, "Not found in your team's work."),
    WorkNotReassignable: (
        status.HTTP_409_CONFLICT,
        "Only open work can be moved to another team member.",
    ),
    InvalidReassignTarget: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Choose another active member of this team.",
    ),
    WorkNotEditable: (
        status.HTTP_409_CONFLICT,
        "Only open work can be changed, and only to a different allowed value.",
    ),
    InvalidFollowUp: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Choose a date and time in the future (follow-ups are for leads only).",
    ),
}

_CallStatus = Literal[
    "connected",
    "no_answer",
    "busy",
    "switched_off",
    "wrong_number",
    "callback_requested",
    "not_interested",
]
_LoanStatus = Literal[
    "new",
    "assigned",
    "contacted",
    "docs_collected",
    "submitted_to_bank",
    "under_review",
    "sanctioned",
    "agreement_collected",
    "agreement_submitted_to_bank",
    "disbursed",
    "closed",
    "rejected",
    "on_hold",
]
_TaskType = Literal["document_collection", "property_visit", "background_check"]
_DealStatus = Literal[
    "new",
    "contacted",
    "site_visit_done",
    "negotiation",
    "booked",
    "agreement_signed",
    "closed",
    "rejected",
    "on_hold",
]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, UnsupportedAnalyticsFilter):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    code, detail = _ERRORS[type(exc)]
    return HTTPException(status_code=code, detail=detail)


@dataclass
class _Period:
    window: AnalyticsWindow
    now: datetime


def _period(
    days: int = Query(30, ge=1, le=365, description="Legacy period in days (7, 30 or 90)."),
    date_from: date | None = Query(None, description="First IST day of the period, inclusive."),
    date_to: date | None = Query(None, description="Last IST day of the period, inclusive."),
) -> _Period:
    now = datetime.now(UTC)
    try:
        return _Period(resolve_analytics_window(date_from, date_to, days, now), now)
    except InvalidAnalyticsWindow as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _analytics_query(
    call_status: _CallStatus | None = Query(None, description="Telecaller teams: call outcome."),
    interest: Literal["hot", "warm", "cold"] | None = Query(
        None, description="Telecaller teams: interest level."
    ),
    loan_status: _LoanStatus | None = Query(
        None, description="Telecaller teams: leads with a loan application in this status."
    ),
    lead_source: Literal["direct", "agent", "client"] | None = Query(
        None, description="Telecaller teams: leads from this referral source."
    ),
    task_type: _TaskType | None = Query(None, description="Employee teams: task type."),
    loan_type_id: UUID | None = Query(
        None, description="Loans teams: leads with an application for this product."
    ),
    bank_id: UUID | None = Query(None, description="Loans teams: applications with this bank."),
    deal_status: _DealStatus | None = Query(
        None, description="Real estate teams: deals in this status."
    ),
    property_category: PropertyCategoryLiteral | None = Query(
        None, description="Real estate teams: deals on a property of this category."
    ),
    property_subtype: PropertySubtypeLiteral | None = Query(
        None, description="Real estate teams: deals on a property of this subtype."
    ),
    amount_min: Decimal | None = Query(
        None,
        ge=0,
        le=AMOUNT_LIMIT,
        description=(
            "Telecaller teams, rupees: requested loan amount or quoted property price, "
            "while the Admin shows it to Telecallers."
        ),
    ),
    amount_max: Decimal | None = Query(
        None, ge=0, le=AMOUNT_LIMIT, description="Rupees; see amount_min."
    ),
    member: list[UUID] | None = Query(  # noqa: B008
        None, description="Only these members (repeatable); all when omitted."
    ),
) -> TeamAnalyticsQuery:
    return TeamAnalyticsQuery(
        call_status=call_status,
        interest=interest,
        loan_status=loan_status,
        lead_source=lead_source,
        task_type=task_type,
        loan_type_id=loan_type_id,
        bank_id=bank_id,
        deal_status=deal_status,
        property_category=property_category,
        property_subtype=property_subtype,
        amount_min=amount_min,
        amount_max=amount_max,
        member_ids=tuple(member or ()),
    )


def _manager_uuid(current_user: CurrentUser) -> UUID:
    if current_user.staff_profile_uuid is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No staff profile on this account.")
    return current_user.staff_profile_uuid


@router.get("/teams", response_model=ManagerTeamsResponse)
async def get_my_teams(
    response: Response,
    current_user: CurrentUser = Depends(team_view),
    db: AsyncSession = Depends(get_db),
) -> ManagerTeamsResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return ManagerTeamsResponse(teams=await list_my_teams(db, _manager_uuid(current_user)))


@router.get("/teams/{team_id}/overview", response_model=TeamOverviewResponse)
async def get_overview(
    team_id: UUID,
    response: Response,
    period: _Period = Depends(_period),
    query: TeamAnalyticsQuery = Depends(_analytics_query),
    current_user: CurrentUser = Depends(team_view),
    db: AsyncSession = Depends(get_db),
) -> TeamOverviewResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await team_overview(
            db, team_id, _manager_uuid(current_user), period.window, period.now, query
        )
    except (TeamNotFound, MemberNotInTeam, UnsupportedAnalyticsFilter) as exc:
        raise _http(exc) from exc


@router.get("/teams/{team_id}/members/{member_id}/analytics", response_model=StaffAnalyticsResponse)
async def get_member_analytics(
    team_id: UUID,
    member_id: UUID,
    response: Response,
    period: _Period = Depends(_period),
    query: TeamAnalyticsQuery = Depends(_analytics_query),
    current_user: CurrentUser = Depends(team_view),
    db: AsyncSession = Depends(get_db),
) -> StaffAnalyticsResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await member_analytics(
            db,
            team_id,
            _manager_uuid(current_user),
            member_id,
            period.window,
            period.now,
            query,
        )
    except (TeamNotFound, MemberNotInTeam, UnsupportedAnalyticsFilter) as exc:
        raise _http(exc) from exc


@router.get("/teams/{team_id}/work", response_model=TeamWorkResponse)
async def get_team_work(
    team_id: UUID,
    response: Response,
    scope: str = Query("open", pattern="^(open|all)$"),
    current_user: CurrentUser = Depends(team_view),
    lead_number: int | None = Depends(lead_number_filter),
    db: AsyncSession = Depends(get_db),
) -> TeamWorkResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await team_work(
            db,
            team_id,
            _manager_uuid(current_user),
            open_only=scope == "open",
            lead_number=lead_number,
        )
    except TeamNotFound as exc:
        raise _http(exc) from exc


@router.get("/teams/{team_id}/members/{member_id}/work", response_model=TeamMemberWorkResponse)
async def get_member_work(
    team_id: UUID,
    member_id: UUID,
    response: Response,
    scope: str = Query("open", pattern="^(open|all)$"),
    current_user: CurrentUser = Depends(team_view),
    lead_number: int | None = Depends(lead_number_filter),
    db: AsyncSession = Depends(get_db),
) -> TeamMemberWorkResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await member_work(
            db,
            team_id,
            _manager_uuid(current_user),
            member_id,
            open_only=scope == "open",
            lead_number=lead_number,
        )
    except (TeamNotFound, MemberNotInTeam) as exc:
        raise _http(exc) from exc


@router.get("/teams/{team_id}/leads/{lead_id}", response_model=TeamLeadDetailResponse)
async def get_lead_detail(
    team_id: UUID,
    lead_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(team_view),
    db: AsyncSession = Depends(get_db),
) -> TeamLeadDetailResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await lead_detail(
            db,
            team_id,
            _manager_uuid(current_user),
            lead_id,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, WorkNotFound) as exc:
        raise _http(exc) from exc


@router.get("/teams/{team_id}/tasks/{task_id}", response_model=TeamTaskDetailResponse)
async def get_task_detail(
    team_id: UUID,
    task_id: UUID,
    response: Response,
    current_user: CurrentUser = Depends(team_view),
    db: AsyncSession = Depends(get_db),
) -> TeamTaskDetailResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await task_detail(
            db,
            team_id,
            _manager_uuid(current_user),
            task_id,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, WorkNotFound) as exc:
        raise _http(exc) from exc


@router.patch("/teams/{team_id}/leads/{lead_id}", response_model=TeamWorkUpdateResponse)
async def patch_lead(
    team_id: UUID,
    lead_id: UUID,
    payload: TeamLeadStatusUpdate,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamWorkUpdateResponse:
    try:
        return await set_lead_status(
            db,
            team_id,
            _manager_uuid(current_user),
            lead_id,
            payload.status,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, WorkNotFound, WorkNotEditable) as exc:
        raise _http(exc) from exc


@router.patch("/teams/{team_id}/tasks/{task_id}", response_model=TeamWorkUpdateResponse)
async def patch_task(
    team_id: UUID,
    task_id: UUID,
    payload: TeamTaskUpdate,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamWorkUpdateResponse:
    try:
        return await update_task(
            db,
            team_id,
            _manager_uuid(current_user),
            task_id,
            payload,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
            now=datetime.now(UTC),
        )
    except (TeamNotFound, WorkNotFound, WorkNotEditable, InvalidFollowUp) as exc:
        raise _http(exc) from exc


@router.post(
    "/teams/{team_id}/leads/{lead_id}/notes",
    response_model=TeamWorkNoteRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_lead_note(
    team_id: UUID,
    lead_id: UUID,
    payload: TeamNoteCreate,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamWorkNoteRead:
    try:
        return await add_note(
            db,
            team_id,
            _manager_uuid(current_user),
            payload,
            lead_id=lead_id,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
            now=datetime.now(UTC),
        )
    except (TeamNotFound, WorkNotFound, WorkNotEditable, InvalidFollowUp) as exc:
        raise _http(exc) from exc


@router.post(
    "/teams/{team_id}/tasks/{task_id}/notes",
    response_model=TeamWorkNoteRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_task_note(
    team_id: UUID,
    task_id: UUID,
    payload: TeamNoteCreate,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamWorkNoteRead:
    try:
        return await add_note(
            db,
            team_id,
            _manager_uuid(current_user),
            payload,
            task_id=task_id,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
            now=datetime.now(UTC),
        )
    except (TeamNotFound, WorkNotFound, WorkNotEditable, InvalidFollowUp) as exc:
        raise _http(exc) from exc


@router.post("/teams/{team_id}/leads/{lead_id}/reassign", response_model=TeamReassignResponse)
async def post_reassign_lead(
    team_id: UUID,
    lead_id: UUID,
    payload: TeamReassignRequest,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamReassignResponse:
    try:
        return await reassign_lead(
            db,
            team_id,
            _manager_uuid(current_user),
            lead_id,
            payload.to_staff_profile_uuid,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, WorkNotFound, WorkNotReassignable, InvalidReassignTarget) as exc:
        raise _http(exc) from exc


@router.post("/teams/{team_id}/tasks/{task_id}/reassign", response_model=TeamReassignResponse)
async def post_reassign_task(
    team_id: UUID,
    task_id: UUID,
    payload: TeamReassignRequest,
    current_user: CurrentUser = Depends(team_edit),
    db: AsyncSession = Depends(get_db),
) -> TeamReassignResponse:
    try:
        return await reassign_task(
            db,
            team_id,
            _manager_uuid(current_user),
            task_id,
            payload.to_staff_profile_uuid,
            actor_uuid=current_user.id,
            actor_role=current_user.role,
        )
    except (TeamNotFound, WorkNotFound, WorkNotReassignable, InvalidReassignTarget) as exc:
        raise _http(exc) from exc
