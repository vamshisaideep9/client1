"""Personal analytics per role (see app/schemas/staff_analytics.py).

Each builder filters to the caller's own rows explicitly (assigned leads, own
calls, own tasks, leads the Agent introduced, content the Sub Admin created)
on top of the request-scoped RLS session. Volumes are per person, so rows are
read once and grouped in Python.

The period is an ``AnalyticsWindow``: inclusive India Standard Time calendar
dates turned into a half-open UTC range. The trend is bucketed per day up to
``DAILY_BUCKET_MAX_DAYS`` and per Monday-start IST week beyond that. Metrics
that describe the current state (open tasks, active leads, overdue
follow-ups, commission totals) ignore the period, as before.

Optional ``StaffAnalyticsFilters`` narrow the same rows further; each one only
ever removes rows from the caller's own scope.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banner import Banner, BannerPlacement, BannerStatus, BannerType
from app.models.commission import Commission, CommissionStatus
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import InterestLevel, LeadActivity
from app.models.loan import LoanApplication, LoanStatus
from app.models.offer import Offer, OfferStatus
from app.models.task import Task, TaskStatus, TaskType
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
from app.services.lead_signals import lead_signals
from app.services.telecaller import get_last_activities, request_summaries_for_leads

IST = ZoneInfo("Asia/Kolkata")
ALLOWED_RANGES = (7, 30, 90)
MAX_RANGE_DAYS = 366
DAILY_BUCKET_MAX_DAYS = 92

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


def today_ist(now: datetime) -> date:
    return _ist_day(now)


@dataclass(frozen=True)
class AnalyticsWindow:
    date_from: date
    date_to: date

    @classmethod
    def last_days(cls, days: int, now: datetime) -> AnalyticsWindow:
        """The ``days`` IST calendar days ending today (the legacy ``?days=`` period)."""
        today = today_ist(now)
        return cls(today - timedelta(days=days - 1), today)

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    @property
    def start(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=IST).astimezone(UTC)

    @property
    def end(self) -> datetime:
        return datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=IST).astimezone(
            UTC
        )

    @property
    def bucket(self) -> Literal["day", "week"]:
        return "day" if self.days <= DAILY_BUCKET_MAX_DAYS else "week"

    def contains(self, value: datetime) -> bool:
        return self.start <= _aware(value) < self.end

    def _bucket_start(self, day: date) -> date:
        if self.bucket == "day":
            return day
        return max(day - timedelta(days=day.weekday()), self.date_from)

    def bucket_of(self, value: datetime) -> date | None:
        if not self.contains(value):
            return None
        return self._bucket_start(_ist_day(value))

    def empty_points(self, keys: Iterable[str]) -> dict[date, dict[str, int]]:
        keys = list(keys)
        buckets: dict[date, dict[str, int]] = {}
        day = self.date_from
        while day <= self.date_to:
            buckets.setdefault(self._bucket_start(day), {key: 0 for key in keys})
            day += timedelta(days=1)
        return buckets


LeadSource = Literal["direct", "agent", "client"]


@dataclass(frozen=True)
class StaffAnalyticsFilters:
    """Role filters; the route rejects any filter that does not apply to the role."""

    business_line: str | None = None
    call_status: str | None = None
    interest: str | None = None
    loan_status: str | None = None
    lead_source: LeadSource | None = None
    lead_status: str | None = None
    task_type: str | None = None
    # Sub Admin content filters.
    content_type: Literal["banners", "offers"] | None = None
    content_status: str | None = None
    placement: str | None = None
    banner_type: str | None = None
    discount_type: str | None = None


NO_FILTERS = StaffAnalyticsFilters()


def _lines(filters: StaffAnalyticsFilters) -> tuple[str, ...] | None:
    # Content rows may target both lines; operational rows never do.
    return (filters.business_line, "both") if filters.business_line else None


class InvalidAnalyticsWindow(ValueError):
    """A requested period the analytics cannot serve; the message is user-facing."""


def resolve_analytics_window(
    date_from: date | None, date_to: date | None, days: int, now: datetime
) -> AnalyticsWindow:
    """Either both IST dates (inclusive, at most MAX_RANGE_DAYS, not in the
    future) or the legacy ``days`` snapped to 7/30/90 and ending today."""
    if date_from is None and date_to is None:
        return AnalyticsWindow.last_days(clamp_range(days), now)
    if date_from is None or date_to is None:
        raise InvalidAnalyticsWindow("Send both date_from and date_to, or neither.")
    if date_from > date_to:
        raise InvalidAnalyticsWindow("date_from must not be after date_to.")
    if date_to > today_ist(now):
        raise InvalidAnalyticsWindow("date_to cannot be in the future.")
    window = AnalyticsWindow(date_from, date_to)
    if window.days > MAX_RANGE_DAYS:
        raise InvalidAnalyticsWindow(f"Choose a period of at most {MAX_RANGE_DAYS} days.")
    return window


def _they(for_manager: bool) -> str:
    return "they" if for_manager else "you"


def _them(for_manager: bool) -> str:
    return "them" if for_manager else "you"


def _their(for_manager: bool) -> str:
    return "their" if for_manager else "your"


def _label(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _percent(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


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


def _response(role: str, window: AnalyticsWindow, **fields: object) -> StaffAnalyticsResponse:
    return StaffAnalyticsResponse(
        role=role,
        range_days=window.days,
        date_from=window.date_from,
        date_to=window.date_to,
        bucket=window.bucket,
        **fields,
    )


async def _lead_subset(
    db: AsyncSession, leads: list[Lead], filters: StaffAnalyticsFilters
) -> set[UUID] | None:
    """Lead ids matching the loan-status / source filters, or None when unfiltered."""
    if not filters.loan_status and not filters.lead_source:
        return None
    ids = {lead.id for lead in leads}
    if filters.loan_status and ids:
        ids &= set(
            await db.scalars(
                select(LoanApplication.lead_uuid).where(
                    LoanApplication.lead_uuid.in_(ids),
                    LoanApplication.status == LoanStatus(filters.loan_status),
                )
            )
        )
    if filters.lead_source and ids:
        signals = await lead_signals(db, [lead for lead in leads if lead.id in ids])
        ids = {
            lead_id
            for lead_id, signal in signals.items()
            if (signal.referrer.kind if signal.referrer else "direct") == filters.lead_source
        }
    return ids


# --- Telecaller ---------------------------------------------------------------


async def telecaller_analytics(
    db: AsyncSession,
    staff_profile_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
    filters: StaffAnalyticsFilters = NO_FILTERS,
    *,
    for_manager: bool = False,
) -> StaffAnalyticsResponse:
    lines = _lines(filters)
    call_stmt = select(LeadActivity).where(
        LeadActivity.telecaller_staff_profile_uuid == staff_profile_uuid,
        LeadActivity.created_at >= window.start,
        LeadActivity.created_at < window.end,
    )
    lead_stmt = select(Lead).where(Lead.assigned_telecaller_profile_uuid == staff_profile_uuid)
    contacted_stmt = (
        select(LeadActivity.lead_uuid)
        .where(LeadActivity.telecaller_staff_profile_uuid == staff_profile_uuid)
        .distinct()
    )
    if lines:
        call_stmt = call_stmt.where(LeadActivity.business_line.in_(lines))
        lead_stmt = lead_stmt.where(Lead.business_line.in_(lines))
        contacted_stmt = contacted_stmt.where(LeadActivity.business_line.in_(lines))
    calls = list(await db.scalars(call_stmt))
    leads = list(await db.scalars(lead_stmt))
    contacted_ids = set(await db.scalars(contacted_stmt))

    subset = await _lead_subset(db, leads, filters)
    if subset is not None:
        leads = [lead for lead in leads if lead.id in subset]
        calls = [call for call in calls if call.lead_uuid in subset]
    if filters.call_status:
        calls = [call for call in calls if call.disposition.value == filters.call_status]
    if filters.interest:
        calls = [
            call
            for call in calls
            if call.interest_level is not None and call.interest_level.value == filters.interest
        ]

    buckets = window.empty_points([series.key for series in _CALL_SERIES])
    for call in calls:
        bucket = window.bucket_of(call.created_at)
        if bucket is not None:
            buckets[bucket][_CALL_GROUP[call.disposition.value]] += 1

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
        if lead.status == LeadStatus.CONVERTED and window.contains(lead.updated_at)
    )

    summaries = await request_summaries_for_leads(db, [lead.id for lead in leads])
    request_status = Counter(
        summary.status for requests in summaries.values() for summary in requests
    )

    return _response(
        "telecaller",
        window,
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
            title="Calls per day" if window.bucket == "day" else "Calls per week",
            description=f"Every call {_they(for_manager)} logged, by outcome.",
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
                description=(
                    f"Every application, enquiry, visit and deal on {_their(for_manager)} leads."
                ),
                kind="ranked",
                items=_counter_items(request_status)[:8],
            ),
        ],
        funnel=AnalyticsFunnel(
            title="Lead funnel",
            description=f"All leads assigned to {_them(for_manager)}.",
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
    db: AsyncSession,
    staff_profile_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
    filters: StaffAnalyticsFilters = NO_FILTERS,
    *,
    for_manager: bool = False,
) -> StaffAnalyticsResponse:
    stmt = select(Task).where(Task.assigned_employee_profile_uuid == staff_profile_uuid)
    lines = _lines(filters)
    if lines:
        stmt = stmt.where(Task.business_line.in_(lines))
    if filters.task_type:
        stmt = stmt.where(Task.task_type == TaskType(filters.task_type))
    tasks = list(await db.scalars(stmt))
    # Tasks have no completion timestamp; the last update of a completed task
    # is when it was completed (status is the final write).
    completed = [
        task
        for task in tasks
        if task.status == TaskStatus.COMPLETED and window.contains(task.updated_at)
    ]
    buckets = window.empty_points(["assigned", "completed"])
    for task in tasks:
        bucket = window.bucket_of(task.created_at)
        if bucket is not None:
            buckets[bucket]["assigned"] += 1
    for task in completed:
        bucket = window.bucket_of(task.updated_at)
        if bucket is not None:
            buckets[bucket]["completed"] += 1

    with_due = [task for task in completed if task.due_at is not None]
    on_time = sum(1 for task in with_due if _aware(task.updated_at) <= _aware(task.due_at))
    turnaround = [
        (_aware(task.updated_at) - _aware(task.created_at)).total_seconds() / 3600
        for task in completed
    ]

    return _response(
        "employee",
        window,
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
            title="Tasks per day" if window.bucket == "day" else "Tasks per week",
            description=(
                f"Tasks assigned to {_them(for_manager)} and tasks {_they(for_manager)} completed."
            ),
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
                description=f"Everything currently assigned to {_them(for_manager)}.",
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
                        task.task_type.value for task in tasks if window.contains(task.created_at)
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
    window: AnalyticsWindow,
    now: datetime,
    filters: StaffAnalyticsFilters = NO_FILTERS,
) -> StaffAnalyticsResponse:
    lead_stmt = select(Lead).where(Lead.origin_agent_profile_uuid == agent_profile_uuid)
    commission_stmt = select(Commission).where(Commission.agent_auth_user_uuid == auth_user_uuid)
    lines = _lines(filters)
    if lines:
        lead_stmt = lead_stmt.where(Lead.business_line.in_(lines))
        commission_stmt = commission_stmt.where(Commission.business_line.in_(lines))
    if filters.lead_status:
        lead_stmt = lead_stmt.where(Lead.status == LeadStatus(filters.lead_status))
    leads = list(await db.scalars(lead_stmt))
    commissions = list(await db.scalars(commission_stmt))
    buckets = window.empty_points(["introduced"])
    for lead in leads:
        bucket = window.bucket_of(lead.created_at)
        if bucket is not None:
            buckets[bucket]["introduced"] += 1

    converted = sum(1 for lead in leads if lead.status == LeadStatus.CONVERTED)
    paid = sum(c.agreed_amount_paise for c in commissions if c.status == CommissionStatus.PAID)
    pending = sum(
        c.agreed_amount_paise for c in commissions if c.status == CommissionStatus.PENDING
    )
    commission_by_status: Counter[str] = Counter()
    for commission in commissions:
        commission_by_status[commission.status.value] += commission.agreed_amount_paise

    return _response(
        "agent",
        window,
        kpis=[
            AnalyticsKpi(
                key="introduced",
                label="Leads introduced",
                value=sum(1 for lead in leads if window.contains(lead.created_at)),
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
            title="Leads introduced per day"
            if window.bucket == "day"
            else "Leads introduced per week",
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

# One review-status vocabulary for both kinds of content. Offers have more
# lifecycle states than banners, so a few of them fold into the shared name:
# scheduled offers are approved, an active offer is live, and an expired offer
# is archived.
_OFFER_STATUSES: dict[str, tuple[OfferStatus, ...]] = {
    "draft": (OfferStatus.DRAFT,),
    "pending_approval": (OfferStatus.PENDING_APPROVAL,),
    "approved": (OfferStatus.APPROVED, OfferStatus.SCHEDULED),
    "live": (OfferStatus.ACTIVE,),
    "rejected": (OfferStatus.REJECTED,),
    "archived": (OfferStatus.ARCHIVED, OfferStatus.EXPIRED),
}


def _wants_banners(filters: StaffAnalyticsFilters) -> bool:
    # An offer-only filter (discount type) can never match a banner.
    return filters.content_type != "offers" and filters.discount_type is None


def _wants_offers(filters: StaffAnalyticsFilters) -> bool:
    # A banner-only filter (placement, banner type) can never match an offer.
    return (
        filters.content_type != "banners"
        and filters.placement is None
        and filters.banner_type is None
    )


async def sub_admin_analytics(
    db: AsyncSession,
    auth_user_uuid: UUID,
    window: AnalyticsWindow,
    now: datetime,
    filters: StaffAnalyticsFilters = NO_FILTERS,
) -> StaffAnalyticsResponse:
    """The Sub Admin's own banners and offers. Content filters narrow the rows
    in SQL; a combination that cannot match one kind of content (an offer
    filter with ``content_type=banners``, say) leaves that kind out instead of
    failing, so contradictions simply return nothing."""
    lines = _lines(filters)
    banners: list[Banner] = []
    offers: list[Offer] = []
    if _wants_banners(filters):
        banner_stmt = select(Banner).where(Banner.created_by_uuid == auth_user_uuid)
        if lines:
            banner_stmt = banner_stmt.where(Banner.business_line.in_(lines))
        if filters.content_status:
            banner_stmt = banner_stmt.where(Banner.status == BannerStatus(filters.content_status))
        if filters.placement:
            banner_stmt = banner_stmt.where(Banner.placement == BannerPlacement(filters.placement))
        if filters.banner_type:
            banner_stmt = banner_stmt.where(Banner.banner_type == BannerType(filters.banner_type))
        banners = list(await db.scalars(banner_stmt))
    if _wants_offers(filters):
        offer_stmt = select(Offer).where(Offer.created_by_uuid == auth_user_uuid)
        if lines:
            offer_stmt = offer_stmt.where(Offer.business_line.in_(lines))
        if filters.content_status:
            offer_stmt = offer_stmt.where(Offer.status.in_(_OFFER_STATUSES[filters.content_status]))
        if filters.discount_type:
            offer_stmt = offer_stmt.where(Offer.discount_type == filters.discount_type)
        offers = list(await db.scalars(offer_stmt))

    buckets = window.empty_points(["banners", "offers"])
    for key, rows in (("banners", banners), ("offers", offers)):
        for row in rows:
            bucket = window.bucket_of(row.created_at)
            if bucket is not None:
                buckets[bucket][key] += 1

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

    return _response(
        "sub_admin",
        window,
        kpis=[
            AnalyticsKpi(
                key="created",
                label="Content created",
                value=sum(1 for row in [*banners, *offers] if window.contains(row.created_at)),
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
            title="Content created per day"
            if window.bucket == "day"
            else "Content created per week",
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
