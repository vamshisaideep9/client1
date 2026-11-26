"""A Sub Admin manager's view over their own team's work (CS-019).

Runs on the manager's own request session. Row reach comes only from the
``*_team_manager_*`` RLS policies (``team_manager_reaches``); every function
here ALSO resolves the team by id *and* the caller's own staff profile, and
checks that the subject belongs to that team and line, so a wrong id yields a
404 rather than relying on an empty RLS result.

Edits (CS-020) and reassignment go through confined database functions;
managers have no UPDATE or INSERT policy of their own.

Reassignment moves work only between members of the same team. It never
touches the line-wide round-robin cursors, and never changes any column other
than the assignee and, where the new assignee has not started, the status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.field_visibility import FieldTargetRole, FieldVisibilityMode
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import LeadActivity
from app.models.notification import NotificationType
from app.models.profile import ProfileStatus, StaffProfile
from app.models.staff_team import StaffTeam, TeamMemberRole, TeamWorkNote
from app.models.task import Task, TaskStatus
from app.schemas.staff_analytics import (
    AnalyticsBreakdown,
    AnalyticsKpi,
    BreakdownItem,
    StaffAnalyticsResponse,
    TrendPoint,
)
from app.schemas.staff_teams import (
    StaffTeamRead,
    TeamAssignee,
    TeamLastCall,
    TeamLeadDetailResponse,
    TeamLeadRow,
    TeamLeadSignals,
    TeamMemberRead,
    TeamMemberSummary,
    TeamMemberWorkResponse,
    TeamNoteCreate,
    TeamOverviewResponse,
    TeamReassignResponse,
    TeamTaskDetailResponse,
    TeamTaskRow,
    TeamTaskUpdate,
    TeamWorkNoteRead,
    TeamWorkResponse,
    TeamWorkUpdateResponse,
)
from app.services.audit_log import record as record_audit
from app.services.field_visibility import effective_modes
from app.services.lead_products import product_labels
from app.services.lead_signals import facets, team_lead_signals_for_ids, transaction_summary
from app.services.leads import lead_number_predicates
from app.services.notifications import emit_notification
from app.services.staff_analytics import (
    AnalyticsWindow,
    InvalidAnalyticsFilter,
    StaffAnalyticsFilters,
    employee_analytics,
    hidden_filters,
    telecaller_analytics,
    validate_filters,
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


class WorkNotEditable(Exception):
    """Closed work, an unchanged value, or a change the rules do not allow."""


class InvalidFollowUp(Exception):
    """A due or follow-up date in the past, or a follow-up on a task."""


class UnsupportedAnalyticsFilter(Exception):
    """An analytics filter the team cannot use; the message is user-facing."""


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


@dataclass(frozen=True)
class TeamAnalyticsQuery:
    """Optional filters a manager applies to team or member analytics (the
    same names, and the same per-role and per-line rules, as /me/analytics)."""

    call_status: str | None = None
    interest: str | None = None
    loan_status: str | None = None
    lead_source: str | None = None
    task_type: str | None = None
    loan_type_id: UUID | None = None
    bank_id: UUID | None = None
    deal_status: str | None = None
    property_category: str | None = None
    property_subtype: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    member_ids: tuple[UUID, ...] = ()


async def _team_filters(
    db: AsyncSession, team: StaffTeamRead, query: TeamAnalyticsQuery | None = None
) -> StaffAnalyticsFilters:
    """Always pin the team's line, so a dual-line member's other-line work
    never counts; reject a filter the team's role, line or the member role's
    field rules do not support."""
    query = query or TeamAnalyticsQuery()
    filters = StaffAnalyticsFilters(
        business_line=team.business_line,
        call_status=query.call_status,
        interest=query.interest,
        loan_status=query.loan_status,
        lead_source=query.lead_source,  # type: ignore[arg-type]
        task_type=query.task_type,
        loan_type_id=query.loan_type_id,
        bank_id=query.bank_id,
        deal_status=query.deal_status,
        property_category=query.property_category,
        property_subtype=query.property_subtype,
        amount_min=query.amount_min,
        amount_max=query.amount_max,
    )
    try:
        await validate_filters(db, team.member_role, team.business_line, filters, subject="team")
    except InvalidAnalyticsFilter as exc:
        raise UnsupportedAnalyticsFilter(str(exc)) from exc
    return filters


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


_TEAM_COPY = (
    ("Every call they logged", "Every call the team logged"),
    ("assigned to them and tasks they completed", "assigned to the team and tasks it completed"),
    ("assigned to them", "assigned to the team"),
    ("on their leads", "on the team's leads"),
)


def _team_copy(description: str) -> str:
    for before, after in _TEAM_COPY:
        description = description.replace(before, after)
    return description


def _team_report(
    reports: list[StaffAnalyticsResponse], totals: list[AnalyticsKpi]
) -> StaffAnalyticsResponse | None:
    """One report for the chosen members: totals as KPIs, trend points and
    breakdown items summed by key (counts; other units are averaged), funnel
    steps summed. Copy says "the team" instead of one person."""
    if not reports:
        return None
    first = reports[0]
    points: dict[date, dict[str, int]] = {}
    for report in reports:
        for point in report.trend.points:
            bucket = points.setdefault(point.day, {})
            for key, value in point.values.items():
                bucket[key] = bucket.get(key, 0) + value
    breakdowns: list[AnalyticsBreakdown] = []
    for index, template in enumerate(first.breakdowns):
        sums: dict[str, list[float]] = {}
        labels: dict[str, str] = {}
        for report in reports:
            for item in report.breakdowns[index].items:
                sums.setdefault(item.key, []).append(item.value)
                labels[item.key] = item.label
        items = [
            BreakdownItem(
                key=key,
                label=labels[key],
                value=(
                    float(sum(values))
                    if template.unit == "count"
                    else round(sum(values) / len(values), 1)
                ),
            )
            for key, values in sums.items()
        ]
        if template.kind == "ranked":
            items.sort(key=lambda item: item.value, reverse=True)
        breakdowns.append(
            template.model_copy(
                update={"items": items, "description": _team_copy(template.description)}
            )
        )
    funnel = None
    if first.funnel is not None:
        funnel = first.funnel.model_copy(
            update={
                "description": _team_copy(first.funnel.description),
                "steps": [
                    step.model_copy(
                        update={
                            "value": sum(
                                report.funnel.steps[index].value
                                for report in reports
                                if report.funnel is not None
                            )
                        }
                    )
                    for index, step in enumerate(first.funnel.steps)
                ],
            }
        )
    return first.model_copy(
        update={
            "kpis": totals,
            "trend": first.trend.model_copy(
                update={
                    "description": _team_copy(first.trend.description),
                    "points": [
                        TrendPoint(day=day, values=values) for day, values in sorted(points.items())
                    ],
                }
            ),
            "breakdowns": breakdowns,
            "funnel": funnel,
        }
    )


def _chosen_members(team: StaffTeamRead, member_ids: tuple[UUID, ...]) -> list[TeamMemberRead]:
    if not member_ids:
        return list(team.members)
    chosen = [member for member in team.members if member.staff_profile_uuid in member_ids]
    if len(chosen) != len(set(member_ids)):
        raise MemberNotInTeam
    return chosen


async def team_overview(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
    query: TeamAnalyticsQuery | None = None,
) -> TeamOverviewResponse:
    team = await _my_team(db, team_id, manager_uuid)
    query = query or TeamAnalyticsQuery()
    filters = await _team_filters(db, team, query)
    members = _chosen_members(team, query.member_ids)
    builder = _builder(team)
    analytics = [
        await builder(db, member.staff_profile_uuid, window, now, filters, for_manager=True)
        for member in members
    ]
    totals = _team_totals(analytics)
    hidden = await hidden_filters(db, team.member_role, team.business_line)
    report = _team_report(analytics, totals)
    return TeamOverviewResponse(
        team=team,
        date_from=window.date_from,
        date_to=window.date_to,
        range_days=window.days,
        totals=totals,
        members=[
            TeamMemberSummary(member=member, kpis=result.kpis)
            for member, result in zip(members, analytics, strict=True)
        ],
        report=report.model_copy(update={"hidden_filters": hidden}) if report else None,
        hidden_filters=hidden,
    )


async def member_analytics(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    member_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
    query: TeamAnalyticsQuery | None = None,
) -> StaffAnalyticsResponse:
    team = await _my_team(db, team_id, manager_uuid)
    if _member(team, member_uuid) is None:
        raise MemberNotInTeam
    result = await _builder(team)(
        db, member_uuid, window, now, await _team_filters(db, team, query), for_manager=True
    )
    return result.model_copy(
        update={"hidden_filters": await hidden_filters(db, team.member_role, team.business_line)}
    )


# --- Work rows -----------------------------------------------------------------


async def _signals(
    db: AsyncSession, team: StaffTeamRead, lead_ids: list[UUID]
) -> dict[UUID, TeamLeadSignals]:
    """Filter signals for leads the caller reaches (team_lead_signals re-checks).

    The loan-transaction summary is only returned by the database for leads
    reached through their Telecaller; it then follows the Admin's Telecaller
    field rules, exactly as on the member's own list."""
    signals = await team_lead_signals_for_ids(db, lead_ids)
    txn_modes = (
        await effective_modes(db, FieldTargetRole.TELECALLER)
        if team.member_role == TeamMemberRole.TELECALLER
        else {}
    )
    return {
        lead_uuid: TeamLeadSignals(
            loan_statuses=signal.loan_statuses,  # type: ignore[arg-type]
            last_disposition=signal.last_disposition,  # type: ignore[arg-type]
            last_interest_level=signal.last_interest_level,  # type: ignore[arg-type]
            referrer=signal.referrer,
            facets=facets(signal),
            transactions=(
                transaction_summary(signal.transactions, txn_modes, team.business_line)
                if team.member_role == TeamMemberRole.TELECALLER
                else None
            ),
        )
        for lead_uuid, signal in signals.items()
    }


async def _hidden_fields(db: AsyncSession, team: StaffTeamRead, keys: tuple[str, ...]) -> list[str]:
    """The Admin's field rules for this team's member role: a manager never
    sees a lead field the member's own screen hides."""
    modes = await effective_modes(db, FieldTargetRole(team.member_role))
    return [
        key
        for key in keys
        if modes.get(("lead", key), FieldVisibilityMode.DENY) != FieldVisibilityMode.ALLOW
    ]


def _assignee(team: StaffTeamRead, staff_profile_uuid: UUID | None) -> TeamAssignee | None:
    member = _member(team, staff_profile_uuid)
    if member is None:
        return None
    return TeamAssignee(
        staff_profile_uuid=member.staff_profile_uuid,
        first_name=member.first_name,
        last_name=member.last_name,
    )


def _without_referrer(signals: TeamLeadSignals, hidden: list[str]) -> TeamLeadSignals:
    return signals.model_copy(update={"referrer": None}) if "referrer" in hidden else signals


async def _lead_rows(db: AsyncSession, team: StaffTeamRead, leads: list[Lead]) -> list[TeamLeadRow]:
    ids = [lead.id for lead in leads]
    summaries = await request_summaries_for_leads(db, ids)
    last = await get_last_activities(db, ids)
    signals = await _signals(db, team, ids)
    labels = await product_labels(db, (lead.product_id for lead in leads))
    # Lead mobile is locked visible for Telecallers; name and referrer follow
    # the Admin's Telecaller rules.
    hidden = await _hidden_fields(db, team, ("name", "referrer"))
    rows: list[TeamLeadRow] = []
    for lead in leads:
        call = last.get(lead.id)
        rows.append(
            TeamLeadRow(
                id=lead.id,
                lead_ref=lead.lead_ref,
                product_id=lead.product_id,
                product_label=labels.get(lead.product_id) if lead.product_id else None,
                name=None if "name" in hidden else lead.name,
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
                assigned_to=_assignee(team, lead.assigned_telecaller_profile_uuid),
                signals=_without_referrer(signals.get(lead.id, TeamLeadSignals()), hidden),
                hidden_fields=hidden,
            )
        )
    return rows


async def _task_rows(db: AsyncSession, team: StaffTeamRead, tasks: list[Task]) -> list[TeamTaskRow]:
    lead_ids = list(dict.fromkeys(task.lead_uuid for task in tasks))
    leads = {
        lead_id: (name, mobile, product_id)
        for lead_id, name, mobile, product_id in (
            await db.execute(
                select(Lead.id, Lead.name, Lead.mobile, Lead.product_id).where(
                    Lead.id.in_(lead_ids)
                )
            )
        ).all()
    }
    labels = await product_labels(db, (row[2] for row in leads.values()))
    signals = await _signals(db, team, lead_ids)
    hidden = await _hidden_fields(db, team, ("name", "mobile", "referrer"))
    rows: list[TeamTaskRow] = []
    for task in tasks:
        name, mobile, product_id = leads.get(task.lead_uuid, (None, None, None))
        rows.append(
            TeamTaskRow(
                id=task.id,
                lead_uuid=task.lead_uuid,
                product_id=product_id,
                product_label=labels.get(product_id) if product_id else None,
                lead_name=None if "name" in hidden else name,
                lead_mobile=None if "mobile" in hidden else mobile,
                task_type=task.task_type.value,
                status=task.status.value,
                business_line=task.business_line,
                notes=task.notes,
                due_at=task.due_at,
                created_at=task.created_at,
                updated_at=task.updated_at,
                assigned_to=_assignee(team, task.assigned_employee_profile_uuid),
                signals=_without_referrer(signals.get(task.lead_uuid, TeamLeadSignals()), hidden),
                hidden_fields=hidden,
            )
        )
    return rows


async def _work(
    db: AsyncSession,
    team: StaffTeamRead,
    member_ids: list[UUID],
    *,
    open_only: bool,
    lead_number: int | None = None,
) -> tuple[str, list[TeamLeadRow], list[TeamTaskRow]]:
    is_telecaller = team.member_role == TeamMemberRole.TELECALLER
    if not member_ids:
        return ("leads" if is_telecaller else "tasks"), [], []
    if is_telecaller:
        stmt = select(Lead).where(
            Lead.assigned_telecaller_profile_uuid.in_(member_ids),
            Lead.business_line == team.business_line,
            *lead_number_predicates(lead_number),
        )
        if open_only:
            stmt = stmt.where(Lead.status.in_(_OPEN_LEAD))
        leads = list(await db.scalars(stmt.order_by(Lead.updated_at.desc()).limit(_WORK_LIMIT)))
        return "leads", await _lead_rows(db, team, leads), []
    stmt = select(Task).where(
        Task.assigned_employee_profile_uuid.in_(member_ids),
        Task.business_line == team.business_line,
    )
    if lead_number is not None:
        # Tasks of the referenced lead, read through the manager's own
        # RLS reach on leads, so it narrows and never widens.
        stmt = stmt.where(
            Task.lead_uuid.in_(select(Lead.id).where(*lead_number_predicates(lead_number)))
        )
    if open_only:
        stmt = stmt.where(Task.status.in_(_OPEN_TASK))
    tasks = list(await db.scalars(stmt.order_by(Task.updated_at.desc()).limit(_WORK_LIMIT)))
    return "tasks", [], await _task_rows(db, team, tasks)


async def team_work(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    *,
    open_only: bool,
    lead_number: int | None = None,
) -> TeamWorkResponse:
    team = await _my_team(db, team_id, manager_uuid)
    kind, leads, tasks = await _work(
        db,
        team,
        [member.staff_profile_uuid for member in team.members],
        open_only=open_only,
        lead_number=lead_number,
    )
    return TeamWorkResponse(team_id=team.id, kind=kind, leads=leads, tasks=tasks)


async def member_work(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    member_uuid: UUID,
    *,
    open_only: bool,
    lead_number: int | None = None,
) -> TeamMemberWorkResponse:
    team = await _my_team(db, team_id, manager_uuid)
    member = _member(team, member_uuid)
    if member is None:
        raise MemberNotInTeam
    kind, leads, tasks = await _work(
        db, team, [member_uuid], open_only=open_only, lead_number=lead_number
    )
    return TeamMemberWorkResponse(member=member, kind=kind, leads=leads, tasks=tasks)


async def work_notes(
    db: AsyncSession, *, lead_id: UUID | None = None, task_id: UUID | None = None
) -> list[TeamWorkNoteRead]:
    """Manager notes on one lead or task, newest first, as RLS lets the caller
    read them (the reaching manager, the assigned member, platform Admin)."""
    condition = (
        TeamWorkNote.lead_uuid == lead_id
        if lead_id is not None
        else TeamWorkNote.task_uuid == task_id
    )
    notes = await db.scalars(
        select(TeamWorkNote).where(condition).order_by(TeamWorkNote.created_at.desc())
    )
    return [
        TeamWorkNoteRead(
            id=note.id,
            author_name=note.author_name,
            body=note.body,
            follow_up_at=note.follow_up_at,
            created_at=note.created_at,
        )
        for note in notes
    ]


async def _team_lead(
    db: AsyncSession, team: StaffTeamRead, lead_id: UUID
) -> tuple[Lead, TeamMemberRead]:
    if team.member_role != TeamMemberRole.TELECALLER:
        raise WorkNotFound
    lead = await db.get(Lead, lead_id)
    member = _member(team, lead.assigned_telecaller_profile_uuid) if lead else None
    if lead is None or member is None or lead.business_line != team.business_line:
        raise WorkNotFound
    return lead, member


async def _team_task(
    db: AsyncSession, team: StaffTeamRead, task_id: UUID
) -> tuple[Task, TeamMemberRead]:
    if team.member_role != TeamMemberRole.EMPLOYEE:
        raise WorkNotFound
    task = await db.get(Task, task_id)
    member = _member(team, task.assigned_employee_profile_uuid) if task else None
    if task is None or member is None or task.business_line != team.business_line:
        raise WorkNotFound
    return task, member


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
    lead, member = await _team_lead(db, team, lead_id)
    activities = list(
        await db.scalars(
            select(LeadActivity)
            .where(LeadActivity.lead_uuid == lead.id)
            .order_by(LeadActivity.created_at.desc())
        )
    )
    row = (await _lead_rows(db, team, [lead]))[0]
    notes = await work_notes(db, lead_id=lead.id)
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
        notes=notes,
    )


async def task_detail(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    task_id: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> TeamTaskDetailResponse:
    team = await _my_team(db, team_id, manager_uuid)
    task, member = await _team_task(db, team, task_id)
    row = (await _task_rows(db, team, [task]))[0]
    notes = await work_notes(db, task_id=task.id)
    # Shows the client's name and mobile, so it is audited like lead detail.
    await record_audit(
        db,
        action=AuditAction.TEAM_TASK_VIEWED,
        entity_type="task",
        entity_uuid=task.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=task.business_line,
        detail={
            "team_uuid": str(team.id),
            "employee_staff_profile_uuid": str(member.staff_profile_uuid),
        },
    )
    await db.commit()
    return TeamTaskDetailResponse(task=row, assigned_to=member, notes=notes)


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


# --- Edits (CS-020) ------------------------------------------------------------

_SET_LEAD_STATUS_SQL = text("SELECT team_manager_set_lead_status(:subject, :status)")
_UPDATE_TASK_SQL = text("SELECT team_manager_update_task(:subject, :due_at, :cancel)")
_ADD_NOTE_SQL = text("SELECT team_manager_add_note(:lead, :task, :body, :follow_up)")
_IST = ZoneInfo("Asia/Kolkata")


def _when(value: datetime) -> str:
    return value.astimezone(_IST).strftime("%d %b, %I:%M %p").lstrip("0")


async def _edit_in_db(db: AsyncSession, sql, params: dict) -> object:
    """Run a confined edit function. It re-checks team reach, line, open
    status and the change under a row lock; a refusal here means the work or
    team changed after the checks above."""
    try:
        return await db.scalar(sql, params)
    except DBAPIError as exc:
        await db.rollback()
        raise WorkNotEditable from exc


async def _member_auth_uuid(db: AsyncSession, member: TeamMemberRead) -> UUID | None:
    profile = await db.get(StaffProfile, member.staff_profile_uuid)
    return profile.auth_user_uuid if profile else None


async def set_lead_status(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    lead_id: UUID,
    status: str,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> TeamWorkUpdateResponse:
    team = await _my_team(db, team_id, manager_uuid)
    lead, member = await _team_lead(db, team, lead_id)
    previous = lead.status.value
    if lead.status not in _OPEN_LEAD or status == previous:
        raise WorkNotEditable
    line = lead.business_line
    await _edit_in_db(db, _SET_LEAD_STATUS_SQL, {"subject": lead.id, "status": status})
    await record_audit(
        db,
        action=AuditAction.TEAM_LEAD_STATUS_UPDATED,
        entity_type="lead",
        entity_uuid=lead.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=line,
        detail={"team_uuid": str(team.id), "from": previous, "to": status},
    )
    await db.commit()
    recipient = await _member_auth_uuid(db, member)
    if recipient is not None:
        await emit_notification(
            user_uuid=recipient,
            notification_type=NotificationType.LEAD_ASSIGNED,
            title="Lead updated by your manager",
            body=f"Your manager marked a {line} lead as {status}.",
            href="/dashboard/leads",
        )
    return TeamWorkUpdateResponse(id=lead.id, status=status)


async def update_task(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    task_id: UUID,
    payload: TeamTaskUpdate,
    *,
    actor_uuid: UUID,
    actor_role: str,
    now: datetime,
) -> TeamWorkUpdateResponse:
    team = await _my_team(db, team_id, manager_uuid)
    task, member = await _team_task(db, team, task_id)
    if task.status not in _OPEN_TASK:
        raise WorkNotEditable
    if payload.due_at is not None and payload.due_at <= now:
        raise InvalidFollowUp
    cancel = payload.cancel_reason is not None
    line = task.business_line
    previous_status = task.status.value
    await _edit_in_db(
        db,
        _UPDATE_TASK_SQL,
        {"subject": task.id, "due_at": payload.due_at, "cancel": cancel},
    )
    if cancel:
        # The reason travels with the task as a manager note the Employee reads.
        await _edit_in_db(
            db,
            _ADD_NOTE_SQL,
            {
                "lead": None,
                "task": task.id,
                "body": f"Cancelled: {payload.cancel_reason}",
                "follow_up": None,
            },
        )
    await record_audit(
        db,
        action=AuditAction.TEAM_TASK_UPDATED,
        entity_type="task",
        entity_uuid=task.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=line,
        detail={
            "team_uuid": str(team.id),
            "change": "cancelled" if cancel else "due_at",
            "from_status": previous_status,
            "due_at": payload.due_at.isoformat() if payload.due_at else None,
        },
    )
    await db.commit()
    recipient = await _member_auth_uuid(db, member)
    if recipient is not None:
        await emit_notification(
            user_uuid=recipient,
            notification_type=NotificationType.TASK_ASSIGNED,
            title="Task cancelled by your manager" if cancel else "Task due date changed",
            body=(
                f"Your manager cancelled a {line} task."
                if cancel
                else f"Your manager set a {line} task due {_when(payload.due_at)}."
            ),
            href="/dashboard/tasks",
        )
    return TeamWorkUpdateResponse(
        id=task.id,
        status="cancelled" if cancel else previous_status,
        due_at=None if cancel else payload.due_at,
    )


async def add_note(
    db: AsyncSession,
    team_id: UUID,
    manager_uuid: UUID,
    payload: TeamNoteCreate,
    *,
    lead_id: UUID | None = None,
    task_id: UUID | None = None,
    actor_uuid: UUID,
    actor_role: str,
    now: datetime,
) -> TeamWorkNoteRead:
    team = await _my_team(db, team_id, manager_uuid)
    if lead_id is not None:
        subject, member = await _team_lead(db, team, lead_id)
    else:
        if payload.follow_up_at is not None:
            raise InvalidFollowUp
        subject, member = await _team_task(db, team, task_id)
    if payload.follow_up_at is not None and payload.follow_up_at <= now:
        raise InvalidFollowUp
    line = subject.business_line
    note_id = await _edit_in_db(
        db,
        _ADD_NOTE_SQL,
        {
            "lead": lead_id,
            "task": task_id,
            "body": payload.body,
            "follow_up": payload.follow_up_at,
        },
    )
    await record_audit(
        db,
        action=AuditAction.TEAM_NOTE_ADDED,
        entity_type="lead" if lead_id is not None else "task",
        entity_uuid=subject.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=line,
        detail={
            "team_uuid": str(team.id),
            "note_uuid": str(note_id),
            "follow_up": payload.follow_up_at is not None,
        },
    )
    await db.commit()
    note = await db.get(TeamWorkNote, note_id)
    recipient = await _member_auth_uuid(db, member)
    if recipient is not None:
        follow_up = f" Follow up by {_when(payload.follow_up_at)}." if payload.follow_up_at else ""
        subject_word = "lead" if lead_id else "task"
        await emit_notification(
            user_uuid=recipient,
            notification_type=(
                NotificationType.LEAD_ASSIGNED if lead_id else NotificationType.TASK_ASSIGNED
            ),
            title="Note from your manager",
            body=f"Your manager added a note on a {line} {subject_word}.{follow_up}",
            href="/dashboard/leads" if lead_id else "/dashboard/tasks",
        )
    return TeamWorkNoteRead(
        id=note.id,
        author_name=note.author_name,
        body=note.body,
        follow_up_at=note.follow_up_at,
        created_at=note.created_at,
    )
