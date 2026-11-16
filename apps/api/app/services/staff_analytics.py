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
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banner import Banner, BannerPlacement, BannerStatus, BannerType
from app.models.commission import Commission, CommissionStatus
from app.models.field_visibility import FieldTargetRole, FieldVisibilityMode
from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import InterestLevel, LeadActivity
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
from app.services.field_visibility import effective_modes
from app.services.lead_signals import (
    EMPTY_SIGNALS,
    DealItem,
    LeadSignals,
    LoanItem,
    lead_signals,
    lead_signals_for_ids,
    team_lead_signals_for_ids,
)
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
    """Role filters; the route rejects any filter that does not apply to the role.

    Product and property filters (CS-023) select the leads (and, for an
    Employee, the tasks on leads) that have one loan application matching every
    loan filter at once — loan type, bank, status and, for a Telecaller, the
    requested amount — or one property deal matching every property filter —
    category, subtype, deal status and, for a Telecaller, the quoted price.
    For an Agent, ``commission_status`` and ``amount_min/max`` (rupees) select
    commissions, and the leads are narrowed to those with such a commission.
    """

    business_line: str | None = None
    call_status: str | None = None
    interest: str | None = None
    loan_status: str | None = None
    lead_source: LeadSource | None = None
    lead_status: str | None = None
    task_type: str | None = None
    # Product and property filters (CS-023).
    loan_type_id: UUID | None = None
    bank_id: UUID | None = None
    deal_status: str | None = None
    property_category: str | None = None
    property_subtype: str | None = None
    commission_status: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    # Sub Admin content filters.
    content_type: Literal["banners", "offers"] | None = None
    content_status: str | None = None
    placement: str | None = None
    banner_type: str | None = None
    discount_type: str | None = None

    @property
    def loan_filtered(self) -> bool:
        return any((self.loan_type_id, self.bank_id, self.loan_status))

    @property
    def deal_filtered(self) -> bool:
        return any((self.deal_status, self.property_category, self.property_subtype))

    @property
    def amount_filtered(self) -> bool:
        return self.amount_min is not None or self.amount_max is not None

    def amount_matches(self, amount: Decimal | None) -> bool:
        if not self.amount_filtered:
            return True
        if amount is None:
            return False
        if self.amount_min is not None and amount < self.amount_min:
            return False
        return not (self.amount_max is not None and amount > self.amount_max)


NO_FILTERS = StaffAnalyticsFilters()

# Filter families (CS-023). Loan filters exist on the loans line and property
# filters on the real estate line; a role offers a filter only where it has
# the data behind it.
LOAN_FILTERS = frozenset({"loan_type_id", "bank_id", "loan_status"})
PROPERTY_FILTERS = frozenset({"deal_status", "property_category", "property_subtype"})
AMOUNT_FILTERS = frozenset({"amount_min", "amount_max"})
_LINE_FILTERS = {"loans": LOAN_FILTERS, "real_estate": PROPERTY_FILTERS}

ROLE_FILTERS: dict[str, frozenset[str]] = {
    # Amount: the lead's requested loan amount or quoted property price.
    "telecaller": frozenset(
        {"call_status", "interest", "lead_source"} | LOAN_FILTERS | PROPERTY_FILTERS
    )
    | AMOUNT_FILTERS,
    # Employees see no application or deal amounts, so no amount filter.
    "employee": frozenset({"task_type"}) | LOAN_FILTERS | PROPERTY_FILTERS,
    # Amount: the agreed commission (the Agent's earning).
    "agent": frozenset({"lead_status", "commission_status"})
    | LOAN_FILTERS
    | PROPERTY_FILTERS
    | AMOUNT_FILTERS,
    "sub_admin": frozenset(
        {"content_type", "content_status", "placement", "banner_type", "discount_type"}
    ),
}

# Rupees; the bound only keeps an amount filter a sane number.
AMOUNT_LIMIT = Decimal("1000000000000")

# The Admin's Telecaller field rule behind the amount filter, per line.
_AMOUNT_RULE = {
    "loans": ("loan_application", "amount_requested"),
    "real_estate": ("property_deal", "price_quoted"),
}


class InvalidAnalyticsFilter(ValueError):
    """A filter the caller cannot use; the message is user-facing."""


def requested_filters(filters: StaffAnalyticsFilters) -> set[str]:
    return {
        name
        for name, value in vars(filters).items()
        if name != "business_line" and value is not None
    }


async def hidden_filters(db: AsyncSession, role: str, line: str | None) -> list[str]:
    """Filters of ``role`` the Admin's field rules rule out (the amount range
    of a Telecaller who may not see the amount on this line)."""
    if role != "telecaller":
        return []
    modes = await effective_modes(db, FieldTargetRole.TELECALLER)
    rules = [_AMOUNT_RULE[line]] if line in _AMOUNT_RULE else list(_AMOUNT_RULE.values())
    if any(
        modes.get(rule, FieldVisibilityMode.DENY) != FieldVisibilityMode.ALLOW for rule in rules
    ):
        return sorted(AMOUNT_FILTERS)
    return []


async def validate_filters(
    db: AsyncSession,
    role: str,
    line: str | None,
    filters: StaffAnalyticsFilters,
    *,
    subject: str = "role",
) -> None:
    """Reject, never ignore, a filter the role, line or field rules rule out.

    ``line`` is the request's (or team's) business line, or None for a caller
    without one, who may use either family but not both at once. A Telecaller
    may filter by amount only while the Admin shows them that amount."""
    requested = requested_filters(filters)
    unsupported = requested - ROLE_FILTERS.get(role, frozenset())
    if unsupported:
        raise InvalidAnalyticsFilter(
            f"Filter not available for this {subject}: {', '.join(sorted(unsupported))}."
        )
    other_line = {
        name
        for other, names in _LINE_FILTERS.items()
        if line is not None and other != line
        for name in names & requested
    }
    if other_line:
        raise InvalidAnalyticsFilter(
            f"Filter not available on this business line: {', '.join(sorted(other_line))}."
        )
    if requested & LOAN_FILTERS and requested & PROPERTY_FILTERS:
        raise InvalidAnalyticsFilter("Choose loan filters or property filters, not both.")
    if (
        filters.amount_min is not None
        and filters.amount_max is not None
        and filters.amount_min > filters.amount_max
    ):
        raise InvalidAnalyticsFilter("amount_min must not be more than amount_max.")
    if requested & AMOUNT_FILTERS and set(await hidden_filters(db, role, line)) & requested:
        raise InvalidAnalyticsFilter(
            f"Filter not available for this {subject}: amount (hidden by the Admin)."
        )


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


def _loan_matches(item: LoanItem, filters: StaffAnalyticsFilters, *, amount: bool) -> bool:
    return (
        (filters.loan_type_id is None or item.loan_type_id == filters.loan_type_id)
        and (filters.bank_id is None or item.bank_id == filters.bank_id)
        and (filters.loan_status is None or item.status == filters.loan_status)
        and (not amount or filters.amount_matches(item.amount))
    )


def _deal_matches(item: DealItem, filters: StaffAnalyticsFilters, *, amount: bool) -> bool:
    return (
        (filters.deal_status is None or item.status == filters.deal_status)
        and (filters.property_category is None or item.category == filters.property_category)
        and (filters.property_subtype is None or item.subtype == filters.property_subtype)
        and (not amount or filters.amount_matches(item.amount))
    )


def _signal_matches(
    signal: LeadSignals, filters: StaffAnalyticsFilters, *, lead_amount: bool
) -> bool:
    """One application (or deal) must match every loan (or property) filter;
    with ``lead_amount`` the amount range applies to that same application or
    deal (requested amount / quoted price)."""
    amount = lead_amount and filters.amount_filtered
    if filters.loan_filtered and not any(
        _loan_matches(item, filters, amount=amount) for item in signal.loans
    ):
        return False
    if filters.deal_filtered and not any(
        _deal_matches(item, filters, amount=amount) for item in signal.deals
    ):
        return False
    if (
        amount
        and not filters.loan_filtered
        and not filters.deal_filtered
        and not any(filters.amount_matches(item.amount) for item in (*signal.loans, *signal.deals))
    ):
        return False
    if filters.lead_source:
        source = signal.referrer.kind if signal.referrer else "direct"
        if source != filters.lead_source:
            return False
    return True


def _lead_filtered(filters: StaffAnalyticsFilters, *, lead_amount: bool) -> bool:
    return bool(
        filters.loan_filtered
        or filters.deal_filtered
        or filters.lead_source
        or (lead_amount and filters.amount_filtered)
    )


async def _signals_for(
    db: AsyncSession, leads: list[Lead], *, for_manager: bool
) -> dict[UUID, LeadSignals]:
    # A manager reads through team_lead_signals (their live team reach);
    # lead_list_signals answers only the lead's own Telecaller, Employee or Agent.
    if for_manager:
        return await team_lead_signals_for_ids(db, [lead.id for lead in leads])
    return await lead_signals(db, leads)


async def _lead_subset(
    db: AsyncSession,
    leads: list[Lead],
    filters: StaffAnalyticsFilters,
    *,
    for_manager: bool = False,
    lead_amount: bool = False,
) -> set[UUID] | None:
    """Lead ids matching the lead-level filters, or None when unfiltered."""
    if not _lead_filtered(filters, lead_amount=lead_amount):
        return None
    if not leads:
        return set()
    signals = await _signals_for(db, leads, for_manager=for_manager)
    return {
        lead.id
        for lead in leads
        if _signal_matches(signals.get(lead.id, EMPTY_SIGNALS), filters, lead_amount=lead_amount)
    }


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

    subset = await _lead_subset(db, leads, filters, for_manager=for_manager, lead_amount=True)
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
    if (filters.loan_filtered or filters.deal_filtered) and tasks:
        lead_ids = list(dict.fromkeys(task.lead_uuid for task in tasks))
        signals = (
            await team_lead_signals_for_ids(db, lead_ids)
            if for_manager
            else await lead_signals_for_ids(db, lead_ids)
        )
        tasks = [
            task
            for task in tasks
            if _signal_matches(
                signals.get(task.lead_uuid, EMPTY_SIGNALS), filters, lead_amount=False
            )
        ]
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


async def _agent_subset(
    db: AsyncSession,
    leads: list[Lead],
    commissions: list[Commission],
    filters: StaffAnalyticsFilters,
) -> tuple[list[Lead], list[Commission]]:
    """Every filter narrows both the leads and the commissions, so the page
    describes one subset: lead filters keep the commissions earned on the
    matching leads (and, for product/property filters, on the matching
    application or deal); commission filters keep the leads that have such a
    commission."""
    if filters.lead_status or filters.loan_filtered or filters.deal_filtered:
        if filters.loan_filtered or filters.deal_filtered:
            signals = await lead_signals(db, leads)
            leads = [
                lead
                for lead in leads
                if _signal_matches(signals.get(lead.id, EMPTY_SIGNALS), filters, lead_amount=False)
            ]
            loans = {
                item.id
                for signal in signals.values()
                for item in signal.loans
                if _loan_matches(item, filters, amount=False)
            }
            deals = {
                item.id
                for signal in signals.values()
                for item in signal.deals
                if _deal_matches(item, filters, amount=False)
            }
            commissions = [
                c
                for c in commissions
                if (not filters.loan_filtered or c.loan_application_uuid in loans)
                and (not filters.deal_filtered or c.property_deal_uuid in deals)
            ]
        lead_ids = {lead.id for lead in leads}
        commissions = [c for c in commissions if c.lead_uuid in lead_ids]
    if filters.amount_filtered:
        commissions = [
            c for c in commissions if filters.amount_matches(Decimal(c.agreed_amount_paise) / 100)
        ]
    if filters.commission_status or filters.amount_filtered:
        with_commission = {c.lead_uuid for c in commissions}
        leads = [lead for lead in leads if lead.id in with_commission]
    return leads, commissions


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
    if filters.commission_status:
        commission_stmt = commission_stmt.where(
            Commission.status == CommissionStatus(filters.commission_status)
        )
    leads = list(await db.scalars(lead_stmt))
    commissions = list(await db.scalars(commission_stmt))
    leads, commissions = await _agent_subset(db, leads, commissions, filters)
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
    # CS-021: the breakdown shows money still owed or already paid; cancelled
    # commissions stay in the Agent's commission history but not here.
    commission_by_status: Counter[str] = Counter()
    for commission in commissions:
        if commission.status == CommissionStatus.CANCELLED:
            continue
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
