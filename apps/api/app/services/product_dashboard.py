"""One dashboard per financial product, for platform Admin and Team Managers.

Scope is server-derived, never taken from the request:

* ``platform`` — a platform Admin sees every lead, task and person.
* ``team`` — a Team Manager Sub Admin sees only the members of their own
  active Loans teams and the leads and tasks those members hold. The
  ``team_manager_reaches`` RLS policies independently limit every row to the
  caller's live teams, so the explicit member filters below can only narrow.

Every metric is one grouped query over ``leads.product_id`` (or the request's
own product for applications and enquiries), so the cost does not grow with the
number of staff. Inactive products stay readable for their history.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import LeadActivity
from app.models.loan import FinancialServiceEnquiry, LoanApplication, LoanType
from app.models.profile import ProfileStatus, StaffProfile, StaffRole
from app.models.task import Task, TaskStatus
from app.schemas.product_dashboards import (
    ManagerProductRow,
    ProductDashboardResponse,
    ProductLeadKpis,
    ProductRef,
    ProductStaffRow,
    ProductStageCount,
    ProductTaskKpis,
    ProductTrendPoint,
)
from app.schemas.staff_teams import StaffTeamRead
from app.services.product_staffing import OPEN_TASKS, UNASSIGNED_LEADS
from app.services.staff_analytics import IST, AnalyticsWindow
from app.services.staff_teams import people_by_profile

_CLOSED_LEADS = (LeadStatus.CONVERTED, LeadStatus.CLOSED)
_MEMBER_OPEN_LEADS = (LeadStatus.ASSIGNED, LeadStatus.WORKING)
_MEMBER_OPEN_TASKS = (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


class ProductNotFound(Exception):
    """No catalogue product has this id."""


@dataclass(frozen=True)
class DashboardScope:
    kind: Literal["platform", "team"]
    telecaller_ids: frozenset[UUID] = frozenset()
    officer_ids: frozenset[UUID] = frozenset()
    # Team scope: members' current specialties, from the caller's own teams.
    member_specialties: dict[UUID, UUID | None] = field(default_factory=dict)

    @property
    def is_team(self) -> bool:
        return self.kind == "team"


PLATFORM_SCOPE = DashboardScope(kind="platform")


def team_scope(teams: list[StaffTeamRead]) -> DashboardScope:
    """Members of the caller's own active Loans teams (the caller is resolved
    from the verified token by ``list_my_teams``)."""
    telecallers: set[UUID] = set()
    officers: set[UUID] = set()
    specialties: dict[UUID, UUID | None] = {}
    for team in teams:
        if team.business_line != "loans" or team.archived_at is not None:
            continue
        target = telecallers if team.member_role == "telecaller" else officers
        for member in team.members:
            target.add(member.staff_profile_uuid)
            specialties[member.staff_profile_uuid] = member.loan_specialty_id
    return DashboardScope(
        kind="team",
        telecaller_ids=frozenset(telecallers),
        officer_ids=frozenset(officers),
        member_specialties=specialties,
    )


def _lead_reach(scope: DashboardScope):  # noqa: ANN202
    if not scope.is_team:
        return ()
    if not scope.telecaller_ids:
        return (false(),)
    return (Lead.assigned_telecaller_profile_uuid.in_(scope.telecaller_ids),)


def _task_reach(scope: DashboardScope):  # noqa: ANN202
    if not scope.is_team:
        return ()
    if not scope.officer_ids:
        return (false(),)
    return (Task.assigned_employee_profile_uuid.in_(scope.officer_ids),)


def _in(column, window: AnalyticsWindow):  # noqa: ANN001, ANN202
    return and_(column >= window.start, column < window.end)


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


async def _product(db: AsyncSession, product_id: UUID) -> ProductRef:
    product = await db.get(LoanType, product_id)
    if product is None:
        raise ProductNotFound
    return ProductRef(
        product_id=product.id,
        label=product.label,
        category=product.category,
        active=product.active,
    )


async def _lead_kpis(
    db: AsyncSession, product_id: UUID, window: AnalyticsWindow, scope: DashboardScope
) -> ProductLeadKpis:
    created = _in(Lead.created_at, window)
    converted_now = Lead.status == LeadStatus.CONVERTED
    row = (
        await db.execute(
            select(
                func.count().filter(created),
                func.count().filter(Lead.status.not_in(_CLOSED_LEADS)),
                func.count().filter(and_(converted_now, _in(Lead.updated_at, window))),
                func.count().filter(and_(created, converted_now)),
                func.count().filter(
                    and_(
                        created,
                        Lead.assigned_telecaller_profile_uuid.is_not(None),
                        StaffProfile.loan_specialty_id.is_distinct_from(product_id),
                    )
                ),
                func.count().filter(
                    and_(
                        Lead.status.in_(UNASSIGNED_LEADS),
                        Lead.assigned_telecaller_profile_uuid.is_(None),
                    )
                ),
            )
            .select_from(Lead)
            .outerjoin(StaffProfile, StaffProfile.id == Lead.assigned_telecaller_profile_uuid)
            .where(
                Lead.product_id == product_id,
                Lead.business_line == "loans",
                *_lead_reach(scope),
            )
        )
    ).one()
    captured, open_count, converted, converted_of_captured, fallback, unassigned = row
    return ProductLeadKpis(
        captured=captured,
        open=open_count,
        converted=converted,
        conversion_rate=_percent(converted_of_captured, captured),
        served_by_fallback=fallback,
        unassigned=0 if scope.is_team else unassigned,
    )


async def _task_kpis(
    db: AsyncSession, product_id: UUID, window: AnalyticsWindow, scope: DashboardScope
) -> ProductTaskKpis:
    completed = and_(Task.status == TaskStatus.COMPLETED, _in(Task.completed_at, window))
    with_due = and_(completed, Task.due_at.is_not(None))
    open_statuses = _MEMBER_OPEN_TASKS if scope.is_team else OPEN_TASKS
    open_count, completed_count, due_count, on_time = (
        await db.execute(
            select(
                func.count().filter(Task.status.in_(open_statuses)),
                func.count().filter(completed),
                func.count().filter(with_due),
                func.count().filter(and_(with_due, Task.completed_at <= Task.due_at)),
            )
            .select_from(Task)
            .join(Lead, Lead.id == Task.lead_uuid)
            .where(
                Lead.product_id == product_id,
                Task.business_line == "loans",
                *_task_reach(scope),
            )
        )
    ).one()
    return ProductTaskKpis(
        open=open_count, completed=completed_count, on_time_rate=_percent(on_time, due_count)
    )


async def _requests_by_status(
    db: AsyncSession,
    product: ProductRef,
    window: AnalyticsWindow,
    scope: DashboardScope,
) -> tuple[Literal["applications", "enquiries"], list[ProductStageCount]]:
    if product.category == "loan":
        kind: Literal["applications", "enquiries"] = "applications"
        stmt = (
            select(LoanApplication.status, func.count())
            .join(Lead, Lead.id == LoanApplication.lead_uuid)
            .where(
                LoanApplication.loan_type_id == product.product_id,
                _in(LoanApplication.opened_at, window),
                *_lead_reach(scope),
            )
            .group_by(LoanApplication.status)
        )
    else:
        kind = "enquiries"
        stmt = (
            select(FinancialServiceEnquiry.status, func.count())
            .join(Lead, Lead.id == FinancialServiceEnquiry.lead_uuid)
            .where(
                FinancialServiceEnquiry.product_id == product.product_id,
                _in(FinancialServiceEnquiry.submitted_at, window),
                *_lead_reach(scope),
            )
            .group_by(FinancialServiceEnquiry.status)
        )
    rows = (await db.execute(stmt)).all()
    counts = [
        ProductStageCount(status=getattr(status, "value", status), count=count)
        for status, count in rows
    ]
    return kind, sorted(counts, key=lambda item: (-item.count, item.status))


def _ist_day(value: datetime) -> date:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(IST).date()


def _week_start(day: date, window: AnalyticsWindow) -> date:
    return max(day - timedelta(days=day.weekday()), window.date_from)


async def _trend(
    db: AsyncSession, product_id: UUID, window: AnalyticsWindow, scope: DashboardScope
) -> list[ProductTrendPoint]:
    points: dict[date, ProductTrendPoint] = {}
    day = window.date_from
    while day <= window.date_to:
        start = _week_start(day, window)
        points.setdefault(start, ProductTrendPoint(week_start=start))
        day += timedelta(days=1)
    base = (
        Lead.product_id == product_id,
        Lead.business_line == "loans",
        *_lead_reach(scope),
    )
    for created_at in await db.scalars(
        select(Lead.created_at).where(*base, _in(Lead.created_at, window))
    ):
        points[_week_start(_ist_day(created_at), window)].captured += 1
    for updated_at in await db.scalars(
        select(Lead.updated_at).where(
            *base, Lead.status == LeadStatus.CONVERTED, _in(Lead.updated_at, window)
        )
    ):
        points[_week_start(_ist_day(updated_at), window)].converted += 1
    return [points[key] for key in sorted(points)]


async def _staff(
    db: AsyncSession, product_id: UUID, window: AnalyticsWindow, scope: DashboardScope
) -> list[ProductStaffRow]:
    stats: dict[UUID, dict[str, int]] = defaultdict(
        lambda: {"assigned": 0, "contacted": 0, "converted": 0, "open": 0, "completed": 0}
    )
    roles: dict[UUID, str] = {}
    for staff_id, assigned, converted in (
        await db.execute(
            select(
                Lead.assigned_telecaller_profile_uuid,
                func.count(),
                func.count().filter(
                    and_(Lead.status == LeadStatus.CONVERTED, _in(Lead.updated_at, window))
                ),
            )
            .where(
                Lead.product_id == product_id,
                Lead.business_line == "loans",
                Lead.assigned_telecaller_profile_uuid.is_not(None),
                *_lead_reach(scope),
            )
            .group_by(Lead.assigned_telecaller_profile_uuid)
        )
    ).all():
        stats[staff_id]["assigned"] = assigned
        stats[staff_id]["converted"] = converted
        roles[staff_id] = "telecaller"

    contacted_stmt = (
        select(
            LeadActivity.telecaller_staff_profile_uuid,
            func.count(func.distinct(LeadActivity.lead_uuid)),
        )
        .join(Lead, Lead.id == LeadActivity.lead_uuid)
        .where(
            Lead.product_id == product_id,
            Lead.business_line == "loans",
            _in(LeadActivity.created_at, window),
        )
        .group_by(LeadActivity.telecaller_staff_profile_uuid)
    )
    if scope.is_team:
        contacted_stmt = contacted_stmt.where(
            LeadActivity.telecaller_staff_profile_uuid.in_(scope.telecaller_ids)
            if scope.telecaller_ids
            else false()
        )
    for staff_id, contacted in (await db.execute(contacted_stmt)).all():
        stats[staff_id]["contacted"] = contacted
        roles[staff_id] = "telecaller"

    for staff_id, open_count, completed in (
        await db.execute(
            select(
                Task.assigned_employee_profile_uuid,
                func.count().filter(Task.status.in_(_MEMBER_OPEN_TASKS)),
                func.count().filter(
                    and_(Task.status == TaskStatus.COMPLETED, _in(Task.completed_at, window))
                ),
            )
            .join(Lead, Lead.id == Task.lead_uuid)
            .where(
                Lead.product_id == product_id,
                Task.business_line == "loans",
                Task.assigned_employee_profile_uuid.is_not(None),
                *_task_reach(scope),
            )
            .group_by(Task.assigned_employee_profile_uuid)
        )
    ).all():
        stats[staff_id]["open"] = open_count
        stats[staff_id]["completed"] = completed
        roles[staff_id] = "employee"

    # Specialists appear even before they hold any of the product's work.
    specialist_stmt = select(StaffProfile.id, StaffProfile.role).where(
        StaffProfile.loan_specialty_id == product_id,
        StaffProfile.role.in_((StaffRole.TELECALLER, StaffRole.EMPLOYEE)),
        StaffProfile.status == ProfileStatus.ACTIVE,
    )
    if scope.is_team:
        members = scope.telecaller_ids | scope.officer_ids
        specialist_stmt = specialist_stmt.where(
            StaffProfile.id.in_(members) if members else false()
        )
    for staff_id, role in (await db.execute(specialist_stmt)).all():
        roles.setdefault(staff_id, role.value)

    # Leads and tasks a person no longer reaches drop out of the RLS reads, but
    # the explicit team filters keep non-members out even where RLS overlaps.
    if scope.is_team:
        allowed = scope.telecaller_ids | scope.officer_ids
        roles = {staff_id: role for staff_id, role in roles.items() if staff_id in allowed}
    people = await people_by_profile(db, roles)
    rows = []
    for staff_id, role in roles.items():
        person = people.get(staff_id)
        if person is None:
            continue
        values = stats[staff_id]
        rows.append(
            ProductStaffRow(
                staff_profile_uuid=staff_id,
                first_name=person.first_name,
                last_name=person.last_name,
                staff_code=person.staff_code,
                role=role,
                specialist=person.loan_specialty_id == product_id,
                assigned=values["assigned"],
                contacted=values["contacted"],
                converted=values["converted"],
                open_tasks=values["open"],
                completed_tasks=values["completed"],
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            not row.specialist,
            row.role != "telecaller",
            -(row.assigned + row.open_tasks),
            row.first_name.lower(),
            row.last_name.lower(),
        ),
    )


async def product_dashboard(
    db: AsyncSession,
    product_id: UUID,
    window: AnalyticsWindow,
    scope: DashboardScope,
) -> ProductDashboardResponse:
    product = await _product(db, product_id)
    kind, requests = await _requests_by_status(db, product, window, scope)
    return ProductDashboardResponse(
        product=product,
        scope=scope.kind,
        date_from=window.date_from,
        date_to=window.date_to,
        range_days=window.days,
        leads=await _lead_kpis(db, product_id, window, scope),
        tasks=await _task_kpis(db, product_id, window, scope),
        requests_kind=kind,
        requests_by_status=requests,
        trend=await _trend(db, product_id, window, scope),
        staff=await _staff(db, product_id, window, scope),
    )


async def manager_products(db: AsyncSession, scope: DashboardScope) -> list[ManagerProductRow]:
    """Products the caller's Loans team members specialise in or work on."""
    specialists: dict[UUID, int] = defaultdict(int)
    for specialty in scope.member_specialties.values():
        if specialty is not None:
            specialists[specialty] += 1
    lead_counts: dict[UUID, int] = {}
    if scope.telecaller_ids:
        lead_counts = dict(
            (
                await db.execute(
                    select(
                        Lead.product_id, func.count().filter(Lead.status.in_(_MEMBER_OPEN_LEADS))
                    )
                    .where(
                        Lead.product_id.is_not(None),
                        Lead.business_line == "loans",
                        *_lead_reach(scope),
                    )
                    .group_by(Lead.product_id)
                )
            ).all()
        )
    task_counts: dict[UUID, int] = {}
    if scope.officer_ids:
        task_counts = dict(
            (
                await db.execute(
                    select(
                        Lead.product_id, func.count().filter(Task.status.in_(_MEMBER_OPEN_TASKS))
                    )
                    .select_from(Task)
                    .join(Lead, Lead.id == Task.lead_uuid)
                    .where(
                        Lead.product_id.is_not(None),
                        Task.business_line == "loans",
                        *_task_reach(scope),
                    )
                    .group_by(Lead.product_id)
                )
            ).all()
        )
    ids = set(specialists) | set(lead_counts) | set(task_counts)
    if not ids:
        return []
    products = list(await db.scalars(select(LoanType).where(LoanType.id.in_(ids))))
    rows = [
        ManagerProductRow(
            product_id=product.id,
            label=product.label,
            category=product.category,
            active=product.active,
            specialists=specialists.get(product.id, 0),
            open_leads=lead_counts.get(product.id, 0),
            open_tasks=task_counts.get(product.id, 0),
        )
        for product in products
    ]
    return sorted(
        rows,
        key=lambda row: (not row.active, -(row.open_leads + row.open_tasks), row.label.lower()),
    )
