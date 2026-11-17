"""Contest scoring (CS-027): who takes part, what they achieved, who wins.

Standings are computed on read from live data and never stored while a
contest runs; the lifecycle job snapshots them into ``contest_results`` when
the contest ends (``services/contest_lifecycle.py``). Everything here runs on
the session it is given. Full standings need every participant's work, which
no participant can read under RLS, so callers pass the bypass session and
expose only the minimized projection in ``services/contest_views.py``.

The window is the contest's inclusive IST dates as a half-open UTC range.

Business credit, by audience:

- Agents: loan cases and property deals on leads the Agent introduced
  (``leads.origin_agent_profile_uuid``). At the disbursed / closed stage this
  is exactly the commission-eligibility predicate of
  ``services/commissions.py`` (``loan_commission_eligible`` /
  ``deal_commission_eligible``), timed by ``disbursed_at`` / ``closed_at``.
- Telecallers: cases and deals on leads they hold now
  (``leads.assigned_telecaller_profile_uuid``). Only the current assignee is
  stored, so a reassigned lead counts for whoever holds it when scored.
- Employees: cases and deals on leads where they hold a task that is not
  cancelled.
- Teams: the union of the current members' cases (a case shared by two
  members counts once) and the sum of their activity.

A case counts when it reached the counted stage inside the window (the stage
markers on ``loan_applications`` / ``property_deals``). Before disbursal or
closing, a case that is now rejected counts for nothing. Its true amount is
read live: the requested amount when submitted, the sanctioned amount once
sanctioned or disbursed; a deal's quoted price, or its listing price until a
price is quoted. Per-case bounds apply to that amount; a case with no known
amount is left out when a bound is set.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.contest import (
    Contest,
    ContestAudience,
    ContestExclusion,
    ContestMetric,
    ContestResultKind,
    ContestWinMode,
)
from app.models.lead import Lead
from app.models.lead_activity import CallDisposition, LeadActivity
from app.models.loan import LoanApplication, LoanStatus
from app.models.profile import AgentProfile, ProfileStatus, StaffProfile
from app.models.property import Property
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.site_visit import SiteVisit, SiteVisitStatus
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.task import Task, TaskStatus, TaskType
from app.models.user import User, UserStatus
from app.schemas.contests import ContestCriteria, LoanCriteria, RealEstateCriteria
from app.services.commissions import deal_commission_eligible, loan_commission_eligible

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class ContestWindow:
    starts_on: date
    ends_on: date

    @property
    def start(self) -> datetime:
        return datetime.combine(self.starts_on, time.min, tzinfo=IST).astimezone(UTC)

    @property
    def end(self) -> datetime:
        return datetime.combine(self.ends_on + timedelta(days=1), time.min, tzinfo=IST).astimezone(
            UTC
        )

    @classmethod
    def of(cls, contest: Contest) -> ContestWindow:
        return cls(contest.starts_on, contest.ends_on)


@dataclass
class Tally:
    cases: dict[uuid.UUID, int] = field(default_factory=dict)  # case id -> paise
    calls: int = 0
    connected: int = 0
    follow_ups_on_time: int = 0
    tasks_completed: int = 0
    tasks_on_time: int = 0
    site_visits_completed: int = 0

    @property
    def count(self) -> int:
        return len(self.cases)

    @property
    def amount_paise(self) -> int:
        return sum(self.cases.values())

    def absorb(self, other: Tally) -> None:
        self.cases.update(other.cases)
        self.calls += other.calls
        self.connected += other.connected
        self.follow_ups_on_time += other.follow_ups_on_time
        self.tasks_completed += other.tasks_completed
        self.tasks_on_time += other.tasks_on_time
        self.site_visits_completed += other.site_visits_completed


@dataclass
class Participant:
    kind: str
    user_uuid: uuid.UUID | None
    first_name: str
    last_name: str
    agent_profile_uuid: uuid.UUID | None = None
    staff_profile_uuid: uuid.UUID | None = None
    team_uuid: uuid.UUID | None = None
    team_name: str | None = None
    tally: Tally = field(default_factory=Tally)
    metric_value: int = 0
    progress: dict[str, int] = field(default_factory=dict)
    qualified: bool = False
    rank: int | None = None
    # Decided at finalization (``decide_winners``).
    won: bool = False
    prize_paise: int = 0
    excluded_reason: str | None = None

    @property
    def key(self) -> uuid.UUID | None:
        return self.agent_profile_uuid or self.team_uuid or self.staff_profile_uuid

    @property
    def display_name(self) -> str:
        if self.kind == ContestResultKind.TEAM:
            return self.team_name or "Team"
        initial = f" {self.last_name[:1].upper()}." if self.last_name else ""
        return f"{self.first_name}{initial}".strip() or "Participant"


@dataclass
class Standings:
    contest_id: uuid.UUID
    computed_at: datetime
    ranked: list[Participant]  # individuals, or teams in a team contest
    team_people: list[Participant] = field(default_factory=list)  # managers and members


def _paise(value: Decimal | float | int | None) -> int | None:
    if value is None:
        return None
    return int((Decimal(value) * 100).to_integral_value())


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


def _tenure_cutoff(window: ContestWindow, criteria: ContestCriteria) -> datetime | None:
    """Joined on or before this moment, or None when no tenure is required
    (then someone who joins mid-contest takes part from the day they join)."""
    days = criteria.eligibility.min_tenure_days
    return window.start - timedelta(days=days) if days else None


async def _agents(
    db: AsyncSession, contest: Contest, criteria: ContestCriteria, window: ContestWindow
) -> list[Participant]:
    stmt = (
        select(AgentProfile.id, AgentProfile.auth_user_uuid, User.first_name, User.last_name)
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .where(
            AgentProfile.business_line == contest.business_line,
            AgentProfile.status == ProfileStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
        )
    )
    cutoff = _tenure_cutoff(window, criteria)
    if cutoff is not None:
        joined_on = func.coalesce(AgentProfile.approved_at, AgentProfile.created_at)
        stmt = stmt.where(joined_on <= cutoff)
    if criteria.eligibility.kyc_verified:
        stmt = stmt.where(func.lower(AgentProfile.kyc_status) == "verified")
    return [
        Participant(
            kind=ContestResultKind.INDIVIDUAL,
            user_uuid=row.auth_user_uuid,
            first_name=row.first_name or "",
            last_name=row.last_name or "",
            agent_profile_uuid=row.id,
        )
        for row in await db.execute(stmt)
    ]


def _staff_stmt(contest: Contest, role: str, cutoff: datetime | None) -> Select:
    stmt = (
        select(StaffProfile.id, StaffProfile.auth_user_uuid, User.first_name, User.last_name)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            StaffProfile.role == role,
            StaffProfile.status == ProfileStatus.ACTIVE,
            StaffProfile.business_line.in_((contest.business_line, "both")),
            User.status == UserStatus.ACTIVE,
        )
    )
    return stmt if cutoff is None else stmt.where(StaffProfile.created_at <= cutoff)


async def _staff(
    db: AsyncSession, contest: Contest, criteria: ContestCriteria, window: ContestWindow
) -> list[Participant]:
    rows = await db.execute(
        _staff_stmt(contest, contest.audience, _tenure_cutoff(window, criteria))
    )
    return [
        Participant(
            kind=ContestResultKind.INDIVIDUAL,
            user_uuid=row.auth_user_uuid,
            first_name=row.first_name or "",
            last_name=row.last_name or "",
            staff_profile_uuid=row.id,
        )
        for row in rows
    ]


async def _teams(
    db: AsyncSession, contest: Contest, criteria: ContestCriteria, window: ContestWindow
) -> tuple[list[Participant], list[Participant], dict[uuid.UUID, list[Participant]]]:
    """Live teams on the line for the member role: the team rows, the manager
    rows (an active managing Sub Admin) and each team's eligible members."""
    teams = list(
        await db.execute(
            select(StaffTeam.id, StaffTeam.name, StaffTeam.manager_staff_profile_uuid).where(
                StaffTeam.business_line == contest.business_line,
                StaffTeam.member_role == contest.team_member_role,
                StaffTeam.archived_at.is_(None),
            )
        )
    )
    if not teams:
        return [], [], {}
    team_ids = [team.id for team in teams]
    member_stmt = _staff_stmt(
        contest, contest.team_member_role or "", _tenure_cutoff(window, criteria)
    ).add_columns(StaffTeamMember.team_uuid)
    member_stmt = member_stmt.join(
        StaffTeamMember, StaffTeamMember.staff_profile_uuid == StaffProfile.id
    ).where(StaffTeamMember.team_uuid.in_(team_ids))
    members: dict[uuid.UUID, list[Participant]] = {team_id: [] for team_id in team_ids}
    for row in await db.execute(member_stmt):
        members[row.team_uuid].append(
            Participant(
                kind=ContestResultKind.TEAM_MEMBER,
                user_uuid=row.auth_user_uuid,
                first_name=row.first_name or "",
                last_name=row.last_name or "",
                staff_profile_uuid=row.id,
                team_uuid=row.team_uuid,
            )
        )
    managers = {
        row.id: row
        for row in await db.execute(
            select(StaffProfile.id, StaffProfile.auth_user_uuid, User.first_name, User.last_name)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(
                StaffProfile.id.in_([team.manager_staff_profile_uuid for team in teams]),
                StaffProfile.role == "sub_admin",
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
            )
        )
    }
    team_rows: list[Participant] = []
    manager_rows: list[Participant] = []
    for team in teams:
        team_rows.append(
            Participant(
                kind=ContestResultKind.TEAM,
                user_uuid=None,
                first_name="",
                last_name="",
                team_uuid=team.id,
                team_name=team.name,
            )
        )
        manager = managers.get(team.manager_staff_profile_uuid)
        if manager is not None:
            manager_rows.append(
                Participant(
                    kind=ContestResultKind.TEAM_MANAGER,
                    user_uuid=manager.auth_user_uuid,
                    first_name=manager.first_name or "",
                    last_name=manager.last_name or "",
                    staff_profile_uuid=manager.id,
                    team_uuid=team.id,
                    team_name=team.name,
                )
            )
    return team_rows, manager_rows, members


# ---------------------------------------------------------------------------
# Business credit
# ---------------------------------------------------------------------------

_LOAN_STAGE = {
    "submitted": LoanApplication.submitted_at,
    "sanctioned": LoanApplication.sanctioned_at,
    "disbursed": LoanApplication.disbursed_at,
}
_DEAL_STAGE = {
    "site_visit_done": PropertyDeal.site_visit_done_at,
    "booked": PropertyDeal.booked_at,
    "agreement_signed": PropertyDeal.agreement_signed_at,
    "closed": PropertyDeal.closed_at,
}


def _credit_column(role: str):
    """The lead column that names who gets credit, or None for Employees."""
    if role == "agent":
        return Lead.origin_agent_profile_uuid
    if role == "telecaller":
        return Lead.assigned_telecaller_profile_uuid
    return None


def _with_credit(stmt: Select, role: str, line: str, ids: list[uuid.UUID]) -> Select:
    column = _credit_column(role)
    if column is not None:
        return stmt.add_columns(column.label("who")).where(column.in_(ids))
    task = aliased(Task)
    return (
        stmt.add_columns(task.assigned_employee_profile_uuid.label("who"))
        .join(task, task.lead_uuid == Lead.id)
        .where(
            task.assigned_employee_profile_uuid.in_(ids),
            task.status != TaskStatus.CANCELLED,
            task.business_line == line,
        )
        .distinct()
    )


def _in_bounds(amount: int | None, low: int | None, high: int | None) -> bool:
    if low is None and high is None:
        return True
    if amount is None:
        return False
    return (low is None or amount >= low) and (high is None or amount <= high)


async def _loan_cases(
    db: AsyncSession,
    rules: LoanCriteria,
    role: str,
    line: str,
    ids: list[uuid.UUID],
    window: ContestWindow,
) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    stage = _LOAN_STAGE[rules.counted_stage]
    amount = (
        LoanApplication.amount_requested
        if rules.counted_stage == "submitted"
        else func.coalesce(LoanApplication.amount_sanctioned, LoanApplication.amount_requested)
    )
    stmt = (
        select(LoanApplication.id, amount.label("amount"))
        .join(Lead, Lead.id == LoanApplication.lead_uuid)
        .where(
            LoanApplication.business_line == line,
            stage >= window.start,
            stage < window.end,
        )
    )
    if rules.counted_stage == "disbursed":
        if role == "agent":
            stmt = stmt.where(loan_commission_eligible())
    else:
        stmt = stmt.where(LoanApplication.status != LoanStatus.REJECTED)
    if rules.loan_type_ids:
        stmt = stmt.where(LoanApplication.loan_type_id.in_(rules.loan_type_ids))
    if rules.bank_ids:
        stmt = stmt.where(LoanApplication.bank_id.in_(rules.bank_ids))
    stmt = _with_credit(stmt, role, line, ids)
    credited: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for row in await db.execute(stmt):
        paise = _paise(row.amount)
        if not _in_bounds(paise, rules.case_amount_min_paise, rules.case_amount_max_paise):
            continue
        credited.setdefault(row.who, {})[row.id] = paise or 0
    return credited


async def _deal_cases(
    db: AsyncSession,
    rules: RealEstateCriteria,
    role: str,
    line: str,
    ids: list[uuid.UUID],
    window: ContestWindow,
) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    stage = _DEAL_STAGE[rules.counted_stage]
    value = func.coalesce(PropertyDeal.price_quoted * 100, Property.price_paise)
    stmt = (
        select(PropertyDeal.id, value.label("value"))
        .join(Lead, Lead.id == PropertyDeal.lead_uuid)
        .join(Property, Property.id == PropertyDeal.property_id)
        .where(
            PropertyDeal.business_line == line,
            stage >= window.start,
            stage < window.end,
        )
    )
    if rules.counted_stage == "closed":
        stmt = stmt.where(
            deal_commission_eligible()
            if role == "agent"
            else PropertyDeal.status == PropertyDealStatus.CLOSED
        )
    else:
        stmt = stmt.where(PropertyDeal.status != PropertyDealStatus.REJECTED)
    if rules.property_categories:
        stmt = stmt.where(Property.category.in_(rules.property_categories))
    if rules.property_subtypes:
        stmt = stmt.where(Property.property_subtype.in_(rules.property_subtypes))
    if rules.listing_intents:
        stmt = stmt.where(Property.listing_intent.in_(rules.listing_intents))
    if rules.cities:
        stmt = stmt.where(
            func.lower(func.btrim(Property.city)).in_([city.casefold() for city in rules.cities])
        )
    stmt = _with_credit(stmt, role, line, ids)
    credited: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for row in await db.execute(stmt):
        paise = int(row.value) if row.value is not None else None
        if not _in_bounds(paise, rules.deal_value_min_paise, rules.deal_value_max_paise):
            continue
        credited.setdefault(row.who, {})[row.id] = paise or 0
    return credited


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


async def _telecaller_activity(
    db: AsyncSession,
    line: str,
    ids: list[uuid.UUID],
    window: ContestWindow,
    now: datetime,
    tallies: dict[uuid.UUID, Tally],
) -> None:
    calls = await db.execute(
        select(
            LeadActivity.telecaller_staff_profile_uuid.label("who"),
            func.count().label("calls"),
            func.count()
            .filter(LeadActivity.disposition == CallDisposition.CONNECTED)
            .label("connected"),
        )
        .where(
            LeadActivity.business_line == line,
            LeadActivity.telecaller_staff_profile_uuid.in_(ids),
            LeadActivity.created_at >= window.start,
            LeadActivity.created_at < window.end,
        )
        .group_by(LeadActivity.telecaller_staff_profile_uuid)
    )
    for row in calls:
        tallies[row.who].calls = row.calls
        tallies[row.who].connected = row.connected

    # A follow-up is kept on time when the same Telecaller logs another call on
    # the lead after scheduling it and before the end of the IST day it was due.
    later = aliased(LeadActivity)
    due_day_end = func.timezone(
        "Asia/Kolkata",
        func.date_trunc("day", func.timezone("Asia/Kolkata", LeadActivity.follow_up_at))
        + timedelta(days=1),
    )
    kept = (
        select(literal(1))
        .where(
            later.lead_uuid == LeadActivity.lead_uuid,
            later.telecaller_staff_profile_uuid == LeadActivity.telecaller_staff_profile_uuid,
            later.created_at > LeadActivity.created_at,
            later.created_at < due_day_end,
        )
        .exists()
    )
    follow_ups = await db.execute(
        select(LeadActivity.telecaller_staff_profile_uuid.label("who"), func.count().label("n"))
        .where(
            LeadActivity.business_line == line,
            LeadActivity.telecaller_staff_profile_uuid.in_(ids),
            LeadActivity.follow_up_at >= window.start,
            LeadActivity.follow_up_at < min(window.end, now),
            kept,
        )
        .group_by(LeadActivity.telecaller_staff_profile_uuid)
    )
    for row in follow_ups:
        tallies[row.who].follow_ups_on_time = row.n

    if line == "real_estate":
        visits = await db.execute(
            select(
                Lead.assigned_telecaller_profile_uuid.label("who"),
                func.count(func.distinct(SiteVisit.id)).label("n"),
            )
            .join(Lead, Lead.id == SiteVisit.lead_uuid)
            .where(
                SiteVisit.business_line == line,
                SiteVisit.status == SiteVisitStatus.DONE,
                SiteVisit.updated_at >= window.start,
                SiteVisit.updated_at < window.end,
                Lead.assigned_telecaller_profile_uuid.in_(ids),
            )
            .group_by(Lead.assigned_telecaller_profile_uuid)
        )
        for row in visits:
            tallies[row.who].site_visits_completed = row.n


async def _employee_activity(
    db: AsyncSession,
    line: str,
    ids: list[uuid.UUID],
    window: ContestWindow,
    tallies: dict[uuid.UUID, Tally],
) -> None:
    # Tasks have no completion timestamp; a completed task's last update is
    # its completion (the staff analytics convention).
    rows = await db.execute(
        select(
            Task.assigned_employee_profile_uuid.label("who"),
            func.count().label("completed"),
            func.count()
            .filter(and_(Task.due_at.is_not(None), Task.updated_at <= Task.due_at))
            .label("on_time"),
            func.count().filter(Task.task_type == TaskType.PROPERTY_VISIT).label("visits"),
        )
        .where(
            Task.business_line == line,
            Task.assigned_employee_profile_uuid.in_(ids),
            Task.status == TaskStatus.COMPLETED,
            Task.updated_at >= window.start,
            Task.updated_at < window.end,
        )
        .group_by(Task.assigned_employee_profile_uuid)
    )
    for row in rows:
        tally = tallies[row.who]
        tally.tasks_completed = row.completed
        tally.tasks_on_time = row.on_time
        if line == "real_estate":
            tally.site_visits_completed = row.visits


async def _tally(
    db: AsyncSession,
    contest: Contest,
    criteria: ContestCriteria,
    role: str,
    ids: list[uuid.UUID],
    window: ContestWindow,
    now: datetime,
) -> dict[uuid.UUID, Tally]:
    tallies = {person: Tally() for person in ids}
    if not ids:
        return tallies
    line = contest.business_line
    credited: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    if criteria.loans is not None:
        credited = await _loan_cases(db, criteria.loans, role, line, ids, window)
    elif criteria.real_estate is not None:
        credited = await _deal_cases(db, criteria.real_estate, role, line, ids, window)
    for person, cases in credited.items():
        tallies[person].cases = cases
    if role == "telecaller":
        await _telecaller_activity(db, line, ids, window, now, tallies)
    elif role == "employee":
        await _employee_activity(db, line, ids, window, tallies)
    return tallies


# ---------------------------------------------------------------------------
# Targets, metric and rank
# ---------------------------------------------------------------------------


def metric_value(metric: str, tally: Tally) -> int:
    return {
        ContestMetric.CASES: tally.count,
        ContestMetric.AMOUNT: tally.amount_paise,
        ContestMetric.CALLS_LOGGED: tally.calls,
        ContestMetric.FOLLOW_UPS_ON_TIME: tally.follow_ups_on_time,
        ContestMetric.TASKS_COMPLETED: tally.tasks_completed,
        ContestMetric.TASKS_ON_TIME: tally.tasks_on_time,
        ContestMetric.SITE_VISITS_COMPLETED: tally.site_visits_completed,
    }[ContestMetric(metric)]


def connect_rate_percent(tally: Tally) -> int:
    return (tally.connected * 100) // tally.calls if tally.calls else 0


def progress_of(criteria: ContestCriteria, metric: str, tally: Tally) -> dict[str, int]:
    """Numbers only, for the populated targets and the ranking metric."""
    progress: dict[str, int] = {}
    if criteria.business is not None:
        progress["count"] = tally.count
        progress["amount_paise"] = tally.amount_paise
    activity = criteria.activity
    wanted = set(activity.populated) if activity else set()
    metric_target = f"{metric}_at_least"
    if metric_target in {
        "calls_logged_at_least",
        "follow_ups_on_time_at_least",
        "tasks_completed_at_least",
        "tasks_on_time_at_least",
        "site_visits_completed_at_least",
    }:
        wanted.add(metric_target)
    values = {
        "calls_logged_at_least": ("calls_logged", tally.calls),
        "follow_ups_on_time_at_least": ("follow_ups_on_time", tally.follow_ups_on_time),
        "tasks_completed_at_least": ("tasks_completed", tally.tasks_completed),
        "tasks_on_time_at_least": ("tasks_on_time", tally.tasks_on_time),
        "site_visits_completed_at_least": ("site_visits_completed", tally.site_visits_completed),
    }
    for target in sorted(wanted):
        if target == "connect_rate_at_least_percent":
            progress["connect_rate_percent"] = connect_rate_percent(tally)
            progress["calls_logged"] = tally.calls
        elif target in values:
            key, value = values[target]
            progress[key] = value
    return progress


def meets_targets(criteria: ContestCriteria, tally: Tally) -> bool:
    business = criteria.business
    if business is not None:
        if business.count_at_least is not None and tally.count < business.count_at_least:
            return False
        if business.count_at_most is not None and tally.count > business.count_at_most:
            return False
        amount_target = (
            business.amount_at_least_paise
            if isinstance(business, LoanCriteria)
            else business.value_at_least_paise
        )
        if amount_target is not None and tally.amount_paise < amount_target:
            return False
    activity = criteria.activity
    if activity is not None:
        checks = (
            (activity.calls_logged_at_least, tally.calls),
            (activity.follow_ups_on_time_at_least, tally.follow_ups_on_time),
            (activity.tasks_completed_at_least, tally.tasks_completed),
            (activity.tasks_on_time_at_least, tally.tasks_on_time),
            (activity.site_visits_completed_at_least, tally.site_visits_completed),
        )
        if any(target is not None and value < target for target, value in checks):
            return False
        if activity.connect_rate_at_least_percent is not None:
            if tally.calls < (activity.connect_rate_min_calls or 0):
                return False
            if connect_rate_percent(tally) < activity.connect_rate_at_least_percent:
                return False
    return True


def _score(criteria: ContestCriteria, metric: str, person: Participant) -> None:
    person.metric_value = metric_value(metric, person.tally)
    person.progress = progress_of(criteria, metric, person.tally)
    person.qualified = meets_targets(criteria, person.tally)


def rank_in_place(people: list[Participant]) -> list[Participant]:
    """Competition ranking by metric value (1, 2, 2, 4); stable by name."""
    people.sort(key=lambda p: (-p.metric_value, p.display_name.casefold(), str(p.key)))
    previous: int | None = None
    for index, person in enumerate(people):
        if person.metric_value != previous:
            rank = index + 1
            previous = person.metric_value
        person.rank = rank
    return people


async def compute_standings(
    db: AsyncSession, contest: Contest, criteria: ContestCriteria, now: datetime | None = None
) -> Standings:
    now = now or datetime.now(UTC)
    window = ContestWindow.of(contest)
    metric = contest.metric
    if contest.audience == ContestAudience.TEAM:
        team_rows, manager_rows, members = await _teams(db, contest, criteria, window)
        everyone = [person for group in members.values() for person in group]
        tallies = await _tally(
            db,
            contest,
            criteria,
            contest.team_member_role or "",
            list({person.staff_profile_uuid for person in everyone}),
            window,
            now,
        )
        by_team: dict[uuid.UUID, Tally] = {}
        for person in everyone:
            own = tallies.get(person.staff_profile_uuid, Tally())
            person.tally = own
            _score(criteria, metric, person)
            by_team.setdefault(person.team_uuid, Tally()).absorb(own)
        for team in team_rows:
            team.tally = by_team.get(team.team_uuid, Tally())
            _score(criteria, metric, team)
        rank_in_place(team_rows)
        team_by_id = {team.team_uuid: team for team in team_rows}
        for manager in manager_rows:
            team = team_by_id[manager.team_uuid]
            manager.tally = team.tally
            manager.metric_value = team.metric_value
            manager.progress = dict(team.progress)
            manager.qualified = team.qualified
            manager.rank = team.rank
        return Standings(contest.id, now, team_rows, manager_rows + everyone)

    if contest.audience == ContestAudience.AGENT:
        people = await _agents(db, contest, criteria, window)
        ids = [person.agent_profile_uuid for person in people]
    else:
        people = await _staff(db, contest, criteria, window)
        ids = [person.staff_profile_uuid for person in people]
    tallies = await _tally(db, contest, criteria, contest.audience, ids, window, now)
    for person in people:
        person.tally = tallies.get(person.key, Tally())
        _score(criteria, metric, person)
    return Standings(contest.id, now, rank_in_place(people))


# ---------------------------------------------------------------------------
# Winners (finalization)
# ---------------------------------------------------------------------------


def _groups(people: Iterable[Participant]) -> list[list[Participant]]:
    """Consecutive equal metric values form one group (ties are treated alike)."""
    groups: list[list[Participant]] = []
    for person in people:
        if groups and groups[-1][0].metric_value == person.metric_value:
            groups[-1].append(person)
        else:
            groups.append([person])
    return groups


def decide_winners(contest: Contest, standings: Standings) -> None:
    """Mark winners and prizes in place.

    Candidates are the participants who met every target. ``threshold``: all
    of them win. ``top_n``: candidates with an achieved metric above zero are
    ranked among themselves (competition ranking) and everyone ranked N or
    better wins, so a tie at the cut-off is kept whole. A budget cap then pays
    winners in rank order; the first group of equal achievers that would cross
    the cap is left out entirely, with everyone below it (``budget_cap``).

    Team contests pay the managing Sub Admin the manager prize and every
    member whose own contribution (the contest metric) reached the member
    minimum the member prize; members below it are ``below_member_minimum``.
    """
    candidates = [person for person in standings.ranked if person.qualified]
    candidates.sort(key=lambda p: (-p.metric_value, p.display_name.casefold(), str(p.key)))
    if contest.win_mode == ContestWinMode.TOP_N:
        candidates = [person for person in candidates if person.metric_value > 0]
        winners: list[Participant] = []
        for index, person in enumerate(candidates):
            better = sum(1 for other in candidates if other.metric_value > person.metric_value)
            if better + 1 <= (contest.top_n or 0):
                winners.append(person)
            elif index >= (contest.top_n or 0):
                break
    else:
        winners = candidates

    people_by_team: dict[uuid.UUID, list[Participant]] = {}
    for person in standings.team_people:
        people_by_team.setdefault(person.team_uuid, []).append(person)

    def cost(entry: Participant) -> int:
        if contest.audience != ContestAudience.TEAM:
            return contest.prize_paise or 0
        total = 0
        for person in people_by_team.get(entry.team_uuid, []):
            if person.kind == ContestResultKind.TEAM_MANAGER:
                total += contest.manager_prize_paise or 0
            elif person.metric_value >= (contest.member_min_contribution or 0):
                total += contest.member_prize_paise or 0
        return total

    paid_out = 0
    capped = False
    awarded: list[Participant] = []
    for group in _groups(winners):
        group_cost = sum(cost(entry) for entry in group)
        if not capped and (
            contest.budget_cap_paise is None or paid_out + group_cost <= contest.budget_cap_paise
        ):
            paid_out += group_cost
            awarded.extend(group)
        else:
            capped = True
            for entry in group:
                entry.excluded_reason = ContestExclusion.BUDGET_CAP.value

    for entry in awarded:
        entry.won = True
        if contest.audience != ContestAudience.TEAM:
            entry.prize_paise = contest.prize_paise or 0
            continue
        for person in people_by_team.get(entry.team_uuid, []):
            if person.kind == ContestResultKind.TEAM_MANAGER:
                person.won = True
                person.prize_paise = contest.manager_prize_paise or 0
            elif contest.member_prize_paise and person.metric_value >= (
                contest.member_min_contribution or 0
            ):
                person.won = True
                person.prize_paise = contest.member_prize_paise
            elif contest.member_prize_paise:
                person.excluded_reason = ContestExclusion.BELOW_MEMBER_MINIMUM.value
