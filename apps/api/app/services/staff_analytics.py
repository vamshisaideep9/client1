"""Personal analytics per role (see app/schemas/staff_analytics.py).

Each builder filters to the caller's own rows explicitly (assigned leads, own
calls, own tasks, leads the Agent introduced, content the Sub Admin created)
on top of the request-scoped RLS session. Volumes are per person, so rows are
read once and grouped in Python; days are India Standard Time calendar days.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banner import Banner, BannerStatus
from app.models.commission import Commission, CommissionStatus
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import InterestLevel, LeadActivity
from app.models.offer import Offer, OfferStatus
from app.models.task import Task, TaskStatus
from app.schemas.staff_analytics import (
    AnalyticsBreakdown,
    AnalyticsFunnel,
    AnalyticsKpi,
    AnalyticsTrend,
    BreakdownItem,
    FunnelStep,
    StaffAnalyticsResponse,
    TrendPoint,
    TrendSeries,
)
from app.services.telecaller import get_last_activities, request_summaries_for_leads

IST = ZoneInfo("Asia/Kolkata")
ALLOWED_RANGES = (7, 30, 90)

_CALL_GROUP = {
    "connected": "connected",
    "no_answer": "not_reached",
    "busy": "not_reached",
    "switched_off": "not_reached",
    "callback_requested": "callback",
    "wrong_number": "lost",
    "not_interested": "lost",
}
_CALL_SERIES = [
    TrendSeries(key="connected", label="Connected"),
    TrendSeries(key="not_reached", label="Not reached"),
    TrendSeries(key="callback", label="Callback asked"),
    TrendSeries(key="lost", label="Not interested / wrong number"),
]


def clamp_range(days: int) -> int:
    return min(ALLOWED_RANGES, key=lambda allowed: abs(allowed - days))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ist_day(value: datetime) -> date:
    return _aware(value).astimezone(IST).date()


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _empty_points(now: datetime, days: int, keys: Iterable[str]) -> dict[date, dict[str, int]]:
    today = _ist_day(now)
    return {
        today - timedelta(days=offset): {key: 0 for key in keys}
        for offset in range(days - 1, -1, -1)
    }


def _points(buckets: dict[date, dict[str, int]]) -> list[TrendPoint]:
    return [TrendPoint(day=day, values=values) for day, values in sorted(buckets.items())]


def _counter_items(
    counter: Counter[str], labels: dict[str, str] | None = None
) -> list[BreakdownItem]:
    return [
        BreakdownItem(key=key, label=(labels or {}).get(key, _label(key)), value=count)
        for key, count in counter.most_common()
        if count
    ]


def _ordered_items(counter: Counter[str], order: Iterable[str]) -> list[BreakdownItem]:
    """Parts of a whole in a fixed category order, so a part keeps its color
    (colors follow the entity, never its rank). Empty parts are omitted."""
    return [
        BreakdownItem(key=key, label=_label(key), value=counter[key])
        for key in order
        if counter.get(key)
    ]


# --- Telecaller ---------------------------------------------------------------


async def telecaller_analytics(
    db: AsyncSession, staff_profile_uuid: UUID, days: int, now: datetime
) -> StaffAnalyticsResponse:
    start = now - timedelta(days=days)
    calls = list(
        await db.scalars(
            select(LeadActivity).where(
                LeadActivity.telecaller_staff_profile_uuid == staff_profile_uuid,
                LeadActivity.created_at >= start,
            )
        )
    )
    leads = list(
        await db.scalars(
            select(Lead).where(Lead.assigned_telecaller_profile_uuid == staff_profile_uuid)
        )
    )
    contacted_ids = set(
        await db.scalars(
            select(LeadActivity.lead_uuid)
            .where(LeadActivity.telecaller_staff_profile_uuid == staff_profile_uuid)
            .distinct()
        )
    )

    buckets = _empty_points(now, days, [series.key for series in _CALL_SERIES])
    for call in calls:
        day = _ist_day(call.created_at)
        if day in buckets:
            buckets[day][_CALL_GROUP[call.disposition.value]] += 1

    connected = [call for call in calls if call.disposition.value == "connected"]
    active = [lead for lead in leads if lead.status in (LeadStatus.ASSIGNED, LeadStatus.WORKING)]
    last_by_lead = await get_last_activities(db, [lead.id for lead in active])
    overdue = sum(
        1
        for activity in last_by_lead.values()
        if activity.follow_up_at is not None and _aware(activity.follow_up_at) < now
    )
    converted_in_range = sum(
        1
        for lead in leads
        if lead.status == LeadStatus.CONVERTED and _aware(lead.updated_at) >= start
    )

    summaries = await request_summaries_for_leads(db, [lead.id for lead in leads])
    request_status = Counter(
        summary.status for requests in summaries.values() for summary in requests
    )

    return StaffAnalyticsResponse(
        role="telecaller",
        range_days=days,
        kpis=[
            AnalyticsKpi(key="calls", label="Calls logged", value=len(calls), unit="count"),
            AnalyticsKpi(
                key="connect_rate",
                label="Connect rate",
                value=_percent(len(connected), len(calls)),
                unit="percent",
                hint="Calls marked connected",
            ),
            AnalyticsKpi(key="active_leads", label="Active leads", value=len(active), unit="count"),
            AnalyticsKpi(
                key="converted", label="Converted", value=converted_in_range, unit="count"
            ),
            AnalyticsKpi(
                key="overdue_follow_ups",
                label="Overdue follow-ups",
                value=overdue,
                unit="count",
            ),
        ],
        trend=AnalyticsTrend(
            title="Calls per day",
            description="Every call you logged, by outcome.",
            series=_CALL_SERIES,
            points=_points(buckets),
        ),
        breakdowns=[
            AnalyticsBreakdown(
                key="interest",
                title="Interest on connected calls",
                description="How interested the client sounded.",
                kind="share",
                items=_ordered_items(
                    Counter(call.interest_level.value for call in connected if call.interest_level),
                    [level.value for level in InterestLevel],
                ),
            ),
            AnalyticsBreakdown(
                key="request_status",
                title="Applications by stage",
                description="Every application, enquiry, visit and deal on your leads.",
                kind="ranked",
                items=_counter_items(request_status)[:8],
            ),
        ],
        funnel=AnalyticsFunnel(
            title="Lead funnel",
            description="All leads assigned to you.",
            steps=[
                FunnelStep(key="assigned", label="Assigned", value=len(leads)),
                FunnelStep(
                    key="contacted",
                    label="Contacted",
                    value=sum(1 for lead in leads if lead.id in contacted_ids),
                ),
                FunnelStep(
                    key="converted",
                    label="Converted",
                    value=sum(1 for lead in leads if lead.status == LeadStatus.CONVERTED),
                ),
            ],
        ),
    )


# --- Employee ------------------------------------------------------------------

_OPEN_TASK = {TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}


async def employee_analytics(
    db: AsyncSession, staff_profile_uuid: UUID, days: int, now: datetime
) -> StaffAnalyticsResponse:
    start = now - timedelta(days=days)
    tasks = list(
        await db.scalars(
            select(Task).where(Task.assigned_employee_profile_uuid == staff_profile_uuid)
        )
    )
    # Tasks have no completion timestamp; the last update of a completed task
    # is when it was completed (status is the final write).
    completed = [
        task
        for task in tasks
        if task.status == TaskStatus.COMPLETED and _aware(task.updated_at) >= start
    ]
    buckets = _empty_points(now, days, ["assigned", "completed"])
    for task in tasks:
        day = _ist_day(task.created_at)
        if _aware(task.created_at) >= start and day in buckets:
            buckets[day]["assigned"] += 1
    for task in completed:
        day = _ist_day(task.updated_at)
        if day in buckets:
            buckets[day]["completed"] += 1

    with_due = [task for task in completed if task.due_at is not None]
    on_time = sum(1 for task in with_due if _aware(task.updated_at) <= _aware(task.due_at))
    turnaround = [
        (_aware(task.updated_at) - _aware(task.created_at)).total_seconds() / 3600
        for task in completed
    ]

    return StaffAnalyticsResponse(
        role="employee",
        range_days=days,
        kpis=[
            AnalyticsKpi(
                key="open_tasks",
                label="Open tasks",
                value=sum(1 for task in tasks if task.status in _OPEN_TASK),
                unit="count",
            ),
            AnalyticsKpi(key="completed", label="Completed", value=len(completed), unit="count"),
            AnalyticsKpi(
                key="on_time",
                label="On time",
                value=_percent(on_time, len(with_due)),
                unit="percent",
                hint="Completed tasks that had a due time",
            ),
            AnalyticsKpi(
                key="turnaround",
                label="Average turnaround",
                value=round(sum(turnaround) / len(turnaround), 1) if turnaround else None,
                unit="hours",
                hint="From assignment to completion",
            ),
        ],
        trend=AnalyticsTrend(
            title="Tasks per day",
            description="Tasks assigned to you and tasks you completed.",
            series=[
                TrendSeries(key="assigned", label="Assigned"),
                TrendSeries(key="completed", label="Completed"),
            ],
            points=_points(buckets),
        ),
        breakdowns=[
            AnalyticsBreakdown(
                key="status",
                title="Tasks by status",
                description="Everything currently assigned to you.",
                kind="share",
                items=_ordered_items(
                    Counter(task.status.value for task in tasks), [s.value for s in TaskStatus]
                ),
            ),
            AnalyticsBreakdown(
                key="type",
                title="Tasks by type",
                description="Tasks assigned in this period.",
                kind="ranked",
                items=_counter_items(
                    Counter(
                        task.task_type.value for task in tasks if _aware(task.created_at) >= start
                    )
                ),
            ),
        ],
    )


# --- Agent ---------------------------------------------------------------------


async def agent_analytics(
    db: AsyncSession,
    agent_profile_uuid: UUID,
    auth_user_uuid: UUID,
    days: int,
    now: datetime,
) -> StaffAnalyticsResponse:
    start = now - timedelta(days=days)
    leads = list(
        await db.scalars(select(Lead).where(Lead.origin_agent_profile_uuid == agent_profile_uuid))
    )
    commissions = list(
        await db.scalars(
            select(Commission).where(Commission.agent_auth_user_uuid == auth_user_uuid)
        )
    )
    buckets = _empty_points(now, days, ["introduced"])
    for lead in leads:
        day = _ist_day(lead.created_at)
        if _aware(lead.created_at) >= start and day in buckets:
            buckets[day]["introduced"] += 1

    converted = sum(1 for lead in leads if lead.status == LeadStatus.CONVERTED)
    paid = sum(c.agreed_amount_paise for c in commissions if c.status == CommissionStatus.PAID)
    pending = sum(
        c.agreed_amount_paise for c in commissions if c.status == CommissionStatus.PENDING
    )
    commission_by_status: Counter[str] = Counter()
    for commission in commissions:
        commission_by_status[commission.status.value] += commission.agreed_amount_paise

    return StaffAnalyticsResponse(
        role="agent",
        range_days=days,
        kpis=[
            AnalyticsKpi(
                key="introduced",
                label="Leads introduced",
                value=sum(1 for lead in leads if _aware(lead.created_at) >= start),
                unit="count",
            ),
            AnalyticsKpi(
                key="conversion",
                label="Conversion rate",
                value=_percent(converted, len(leads)),
                unit="percent",
                hint="All leads you introduced",
            ),
            AnalyticsKpi(key="paid", label="Commission paid", value=paid / 100, unit="rupees"),
            AnalyticsKpi(
                key="pending", label="Commission pending", value=pending / 100, unit="rupees"
            ),
        ],
        trend=AnalyticsTrend(
            title="Leads introduced per day",
            description="New leads you brought in.",
            series=[TrendSeries(key="introduced", label="Introduced")],
            points=_points(buckets),
        ),
        breakdowns=[
            AnalyticsBreakdown(
                key="lead_status",
                title="Your leads by status",
                description="Where every lead you introduced is now.",
                kind="share",
                items=_ordered_items(
                    Counter(lead.status.value for lead in leads), [s.value for s in LeadStatus]
                ),
            ),
            AnalyticsBreakdown(
                key="commission",
                title="Commission by status",
                description="Agreed commission amounts.",
                kind="ranked",
                unit="rupees",
                items=[
                    BreakdownItem(key=key, label=_label(key), value=amount / 100)
                    for key, amount in commission_by_status.most_common()
                ],
            ),
        ],
        funnel=AnalyticsFunnel(
            title="Lead funnel",
            description="From introduction to conversion.",
            steps=[
                FunnelStep(key="introduced", label="Introduced", value=len(leads)),
                FunnelStep(
                    key="assigned",
                    label="With a Telecaller",
                    value=sum(
                        1
                        for lead in leads
                        if lead.status
                        in (LeadStatus.ASSIGNED, LeadStatus.WORKING, LeadStatus.CONVERTED)
                    ),
                ),
                FunnelStep(key="converted", label="Converted", value=converted),
            ],
        ),
    )


# --- Sub Admin -----------------------------------------------------------------

_APPROVED_BANNER = {BannerStatus.APPROVED, BannerStatus.LIVE, BannerStatus.ARCHIVED}
_APPROVED_OFFER = {OfferStatus.APPROVED, OfferStatus.SCHEDULED, OfferStatus.ACTIVE}


async def sub_admin_analytics(
    db: AsyncSession, auth_user_uuid: UUID, days: int, now: datetime
) -> StaffAnalyticsResponse:
    start = now - timedelta(days=days)
    banners = list(await db.scalars(select(Banner).where(Banner.created_by_uuid == auth_user_uuid)))
    offers = list(await db.scalars(select(Offer).where(Offer.created_by_uuid == auth_user_uuid)))

    buckets = _empty_points(now, days, ["banners", "offers"])
    for key, rows in (("banners", banners), ("offers", offers)):
        for row in rows:
            day = _ist_day(row.created_at)
            if _aware(row.created_at) >= start and day in buckets:
                buckets[day][key] += 1

    approved = sum(1 for b in banners if b.status in _APPROVED_BANNER) + sum(
        1 for o in offers if o.status in _APPROVED_OFFER
    )
    rejected = sum(1 for b in banners if b.status == BannerStatus.REJECTED) + sum(
        1 for o in offers if o.status == OfferStatus.REJECTED
    )
    pending = sum(1 for b in banners if b.status == BannerStatus.PENDING_APPROVAL) + sum(
        1 for o in offers if o.status == OfferStatus.PENDING_APPROVAL
    )
    live = sum(1 for b in banners if b.status == BannerStatus.LIVE) + sum(
        1 for o in offers if o.status == OfferStatus.ACTIVE
    )

    return StaffAnalyticsResponse(
        role="sub_admin",
        range_days=days,
        kpis=[
            AnalyticsKpi(
                key="created",
                label="Content created",
                value=sum(1 for row in [*banners, *offers] if _aware(row.created_at) >= start),
                unit="count",
            ),
            AnalyticsKpi(key="live", label="Live now", value=live, unit="count"),
            AnalyticsKpi(key="pending", label="Awaiting approval", value=pending, unit="count"),
            AnalyticsKpi(
                key="approval_rate",
                label="Approval rate",
                value=_percent(approved, approved + rejected),
                unit="percent",
                hint="Of your banners and offers that were reviewed",
            ),
        ],
        trend=AnalyticsTrend(
            title="Content created per day",
            description="Banners and offers you created.",
            series=[
                TrendSeries(key="banners", label="Banners"),
                TrendSeries(key="offers", label="Offers"),
            ],
            points=_points(buckets),
        ),
        breakdowns=[
            AnalyticsBreakdown(
                key="banner_status",
                title="Your banners by status",
                description="Every banner you created.",
                kind="share",
                items=_ordered_items(
                    Counter(banner.status.value for banner in banners),
                    [s.value for s in BannerStatus],
                ),
            ),
            AnalyticsBreakdown(
                key="offer_status",
                title="Your offers by status",
                description="Every offer you created.",
                kind="ranked",
                items=_counter_items(Counter(offer.status.value for offer in offers)),
            ),
        ],
    )
