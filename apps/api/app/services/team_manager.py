"""A Sub Admin manager's view over their own team's work (CS-019).

Runs on the manager's own request session. Row reach comes only from the
``*_team_manager_*`` RLS policies (``team_manager_reaches``); every function
here ALSO resolves the team by id *and* the caller's own staff profile, and
checks that the subject belongs to that team and line, so a wrong id yields a
404 rather than relying on an empty RLS result.

Reassignment moves work only between members of the same team. It never
touches the line-wide round-robin cursors, and never changes any column other
than the assignee and, where the new assignee has not started, the status.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import LeadActivity
from app.models.notification import NotificationType
from app.models.profile import ProfileStatus, StaffProfile
from app.models.staff_team import StaffTeam, TeamMemberRole
from app.models.task import Task, TaskStatus
from app.schemas.staff_analytics import AnalyticsKpi, StaffAnalyticsResponse
from app.schemas.staff_teams import (
    StaffTeamRead,
    TeamLastCall,
    TeamLeadDetailResponse,
    TeamLeadRow,
    TeamMemberRead,
    TeamMemberSummary,
    TeamMemberWorkResponse,
    TeamOverviewResponse,
    TeamReassignResponse,
    TeamTaskRow,
)
from app.services.audit_log import record as record_audit
from app.services.notifications import emit_notification
from app.services.staff_analytics import (
    AnalyticsWindow,
    StaffAnalyticsFilters,
    employee_analytics,
    telecaller_analytics,
)
from app.services.staff_teams import build_team_reads
from app.services.telecaller import (
    get_last_activities,
    request_summaries_for_leads,
    to_activity_read,
)

_OPEN_LEAD = (LeadStatus.ASSIGNED, LeadStatus.WORKING)
_OPEN_TASK = (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
_WORK_LIMIT = 200


class TeamNotFound(Exception):
    pass


class MemberNotInTeam(Exception):
    pass


class WorkNotFound(Exception):
    pass


class WorkNotReassignable(Exception):
    pass


class InvalidReassignTarget(Exception):
    pass


async def list_my_teams(db: AsyncSession, manager_uuid: UUID) -> list[StaffTeamRead]:
    teams = list(
        await db.scalars(
            select(StaffTeam)
            .where(
                StaffTeam.manager_staff_profile_uuid == manager_uuid,
                StaffTeam.archived_at.is_(None),
            )
            .order_by(StaffTeam.business_line)
        )
    )
    return await build_team_reads(db, teams)


async def _my_team(db: AsyncSession, team_id: UUID, manager_uuid: UUID) -> StaffTeamRead:
    team = await db.scalar(
        select(StaffTeam).where(
            StaffTeam.id == team_id,
            StaffTeam.manager_staff_profile_uuid == manager_uuid,
            StaffTeam.archived_at.is_(None),
        )
    )
    if team is None:
        raise TeamNotFound
    return (await build_team_reads(db, [team]))[0]


def _member(team: StaffTeamRead, staff_profile_uuid: UUID | None) -> TeamMemberRead | None:
    return next(
        (person for person in team.members if person.staff_profile_uuid == staff_profile_uuid),
        None,
    )


def _builder(team: StaffTeamRead):
    return telecaller_analytics if team.member_role == "telecaller" else employee_analytics


def _team_filters(team: StaffTeamRead) -> StaffAnalyticsFilters:
    # A dual-line member's other-line work never counts toward this team.
    return StaffAnalyticsFilters(business_line=team.business_line)


def _team_totals(summaries: list[StaffAnalyticsResponse]) -> list[AnalyticsKpi]:
    """Counts add up; rates and durations are the average over members that
    have a value (a member with no calls has no connect rate, not 0%)."""
    if not summaries:
        return []
    totals: list[AnalyticsKpi] = []
    for index, first in enumerate(summaries[0].kpis):
        values = [s.kpis[index].value for s in summaries if s.kpis[index].value is not None]
        if first.unit == "count":
            value: float | None = float(sum(values))
            hint = first.hint
        else:
            value = round(sum(values) / len(values), 1) if values else None
            hint = "Average across members"
        totals.append(
            AnalyticsKpi(key=first.key, label=first.label, value=value, unit=first.unit, hint=hint)
        )
    return totals


async def team_overview(
    db: AsyncSession, team_id: UUID, manager_uuid: UUID, window: AnalyticsWindow, now: datetime
) -> TeamOverviewResponse:
    team = await _my_team(db, team_id, manager_uuid)
    builder = _builder(team)
    analytics = [
        await builder(
            db, member.staff_profile_uuid, window, now, _team_filters(team), for_manager=True
        )
        for member in team.members
    ]
    return TeamOverviewResponse(
        team=team,
        date_from=window.date_from,
        date_to=window.date_to,
        range_days=window.days,
        totals=_team_totals(analytics),
        members=[
            TeamMemberSummary(member=member, kpis=result.kpis)
            for member, result in zip(team.members, analytics, strict=True)
        ],
    )


async def member_analytics(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    member_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
) -> StaffAnalyticsResponse:
    team = await _my_team(db, team_id, manager_uuid)
    if _member(team, member_uuid) is None:
        raise MemberNotInTeam
    return await _builder(team)(db, member_uuid, window, now, _team_filters(team), for_manager=True)


async def _lead_rows(db: AsyncSession, leads: list[Lead]) -> list[TeamLeadRow]:
    ids = [lead.id for lead in leads]
    summaries = await request_summaries_for_leads(db, ids)
    last = await get_last_activities(db, ids)
    rows: list[TeamLeadRow] = []
    for lead in leads:
        call = last.get(lead.id)
        rows.append(
            TeamLeadRow(
                id=lead.id,
                name=lead.name,
                mobile=lead.mobile,
                status=lead.status.value,
                business_line=lead.business_line,
                created_at=lead.created_at,
                updated_at=lead.updated_at,
                requests=summaries.get(lead.id, []),
                last_call=(
                    TeamLastCall(
                        disposition=call.disposition.value,
                        interest_level=call.interest_level.value if call.interest_level else None,
                        follow_up_at=call.follow_up_at,
                        created_at=call.created_at,
                    )
                    if call is not None
                    else None
                ),
            )
        )
    return rows


async def member_work(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    member_uuid: UUID,
    *,
    open_only: bool,
) -> TeamMemberWorkResponse:
    team = await _my_team(db, team_id, manager_uuid)
    member = _member(team, member_uuid)
    if member is None:
        raise MemberNotInTeam

    if team.member_role == TeamMemberRole.TELECALLER:
        stmt = select(Lead).where(
            Lead.assigned_telecaller_profile_uuid == member_uuid,
            Lead.business_line == team.business_line,
        )
        if open_only:
            stmt = stmt.where(Lead.status.in_(_OPEN_LEAD))
        leads = list(await db.scalars(stmt.order_by(Lead.updated_at.desc()).limit(_WORK_LIMIT)))
        return TeamMemberWorkResponse(
            member=member, kind="leads", leads=await _lead_rows(db, leads), tasks=[]
        )

    stmt = select(Task).where(
        Task.assigned_employee_profile_uuid == member_uuid,
        Task.business_line == team.business_line,
    )
    if open_only:
        stmt = stmt.where(Task.status.in_(_OPEN_TASK))
    tasks = list(await db.scalars(stmt.order_by(Task.updated_at.desc()).limit(_WORK_LIMIT)))
    names = dict(
        (
            await db.execute(
                select(Lead.id, Lead.name).where(Lead.id.in_({task.lead_uuid for task in tasks}))
            )
        ).all()
    )
    return TeamMemberWorkResponse(
        member=member,
        kind="tasks",
        leads=[],
        tasks=[
            TeamTaskRow(
                id=task.id,
                lead_uuid=task.lead_uuid,
                lead_name=names.get(task.lead_uuid),
                task_type=task.task_type.value,
                status=task.status.value,
                business_line=task.business_line,
                notes=task.notes,
                due_at=task.due_at,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in tasks
        ],
    )


async def lead_detail(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    lead_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> TeamLeadDetailResponse:
    team = await _my_team(db, team_id, manager_uuid)
    if team.member_role != TeamMemberRole.TELECALLER:
        raise WorkNotFound
    lead = await db.get(Lead, lead_id)
    member = _member(team, lead.assigned_telecaller_profile_uuid) if lead else None
    if lead is None or member is None or lead.business_line != team.business_line:
        raise WorkNotFound

    activities = list(
        await db.scalars(
            select(LeadActivity)
            .where(LeadActivity.lead_uuid == lead.id)
            .order_by(LeadActivity.created_at.desc())
        )
    )
    row = (await _lead_rows(db, [lead]))[0]
    await record_audit(
        db,
        action=AuditAction.TEAM_LEAD_VIEWED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=lead.business_line,
        detail={
            "team_uuid": str(team.id),
            "telecaller_staff_profile_uuid": str(member.staff_profile_uuid),
        },
    )
    await db.commit()
    return TeamLeadDetailResponse(
        lead=row,
        assigned_to=member,
        activities=[to_activity_read(activity) for activity in activities],
    )


async def _active_target(
    db: AsyncSession, team: StaffTeamRead, target_uuid: UUID, current_uuid: UUID | None
) -> StaffProfile:
    if target_uuid == current_uuid or _member(team, target_uuid) is None:
        raise InvalidReassignTarget
    target = await db.get(StaffProfile, target_uuid)
    if (
        target is None
        or target.status != ProfileStatus.ACTIVE
        or target.role.value != team.member_role
        or target.business_line not in (team.business_line, "both")
    ):
        raise InvalidReassignTarget
    return target


_REASSIGN_LEAD_SQL = text("SELECT team_manager_reassign_lead(:subject, :target)")
_REASSIGN_TASK_SQL = text("SELECT team_manager_reassign_task(:subject, :target)")


async def _reassign_in_db(db: AsyncSession, sql, subject_id: UUID, target_id: UUID) -> None:
    """Move the work through the confined DB function, which re-checks team
    reach, open status and the target under a row lock. A failure here means
    the team or the work changed after the checks above (a race)."""
    try:
        await db.execute(sql, {"subject": subject_id, "target": target_id})
    except DBAPIError as exc:
        await db.rollback()
        raise WorkNotReassignable from exc


async def reassign_lead(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    lead_id: UUID,
    target_uuid: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> TeamReassignResponse:
    team = await _my_team(db, team_id, manager_uuid)
    if team.member_role != TeamMemberRole.TELECALLER:
        raise WorkNotFound
    lead = await db.get(Lead, lead_id)
    if (
        lead is None
        or lead.business_line != team.business_line
        or _member(team, lead.assigned_telecaller_profile_uuid) is None
    ):
        raise WorkNotFound
    if lead.status not in _OPEN_LEAD:
        raise WorkNotReassignable

    previous_uuid = lead.assigned_telecaller_profile_uuid
    target = await _active_target(db, team, target_uuid, previous_uuid)
    previous = await db.get(StaffProfile, previous_uuid)
    await _reassign_in_db(db, _REASSIGN_LEAD_SQL, lead.id, target.id)

    await record_audit(
        db,
        action=AuditAction.TEAM_LEAD_REASSIGNED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=lead.business_line,
        detail={
            "team_uuid": str(team.id),
            "telecaller_staff_profile_uuid": str(target.id),
            "previous_telecaller_staff_profile_uuid": str(previous_uuid),
        },
    )
    await db.commit()

    if previous is not None:
        await emit_notification(
            user_uuid=previous.auth_user_uuid,
            notification_type=NotificationType.LEAD_RELEASED,
            title="Lead reassigned",
            body=f"Your manager moved a {lead.business_line} lead to a teammate.",
            href="/dashboard/leads",
        )
    await emit_notification(
        user_uuid=target.auth_user_uuid,
        notification_type=NotificationType.LEAD_ASSIGNED,
        title="New lead assigned",
        body=f"Your manager assigned a {lead.business_line} lead to you.",
        href="/dashboard/leads",
    )
    return TeamReassignResponse(
        id=lead.id, assigned_staff_profile_uuid=target.id, status=LeadStatus.ASSIGNED.value
    )


async def reassign_task(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    task_id: UUID,
    target_uuid: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> TeamReassignResponse:
    team = await _my_team(db, team_id, manager_uuid)
    if team.member_role != TeamMemberRole.EMPLOYEE:
        raise WorkNotFound
    task = await db.get(Task, task_id)
    if (
        task is None
        or task.business_line != team.business_line
        or _member(team, task.assigned_employee_profile_uuid) is None
    ):
        raise WorkNotFound
    if task.status not in _OPEN_TASK:
        raise WorkNotReassignable

    previous_uuid = task.assigned_employee_profile_uuid
    target = await _active_target(db, team, target_uuid, previous_uuid)
    previous = await db.get(StaffProfile, previous_uuid)
    # The new Employee has not started; a blocked task stays blocked.
    new_status = TaskStatus.ASSIGNED if task.status == TaskStatus.IN_PROGRESS else task.status
    await _reassign_in_db(db, _REASSIGN_TASK_SQL, task.id, target.id)

    await record_audit(
        db,
        action=AuditAction.TEAM_TASK_REASSIGNED,
        entity_type="task",
        entity_uuid=task.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=task.business_line,
        detail={
            "team_uuid": str(team.id),
            "employee_staff_profile_uuid": str(target.id),
            "previous_employee_staff_profile_uuid": str(previous_uuid),
        },
    )
    await db.commit()

    if previous is not None:
        await emit_notification(
            user_uuid=previous.auth_user_uuid,
            notification_type=NotificationType.TASK_ASSIGNED,
            title="Task reassigned",
            body=f"Your manager moved a {task.business_line} task to a teammate.",
            href="/dashboard/tasks",
        )
    await emit_notification(
        user_uuid=target.auth_user_uuid,
        notification_type=NotificationType.TASK_ASSIGNED,
        title="New task assigned",
        body=f"Your manager assigned a {task.business_line} task to you.",
        href="/dashboard/tasks",
    )
    return TeamReassignResponse(
        id=task.id, assigned_staff_profile_uuid=target.id, status=new_status.value
    )
