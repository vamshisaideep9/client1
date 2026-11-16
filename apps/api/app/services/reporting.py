"""Admin analytics & reporting engine (FR-16.1-16.3, feature-status.md §3 #2).

Runs entirely on the request-scoped `db` session -- no `AsyncSessionLocal`
import here, so no `conftest._patch_db_null_pool` entry is needed (same
posture as `services/loan_config.py` and `services/loan_applications.py`).

Conversion means a different thing per entity and the three counters are
never merged into one "conversion rate":
  - leads:  LeadStatus.CONVERTED           (manually set by a telecaller)
  - loans:  LoanStatus.DISBURSED           (terminal-success event, see
            services/loan_applications.py)
  - deals:  PropertyDealStatus.CLOSED      (terminal-success event, see
            services/property_deals.py)

Timezone. All time columns are timestamptz; the business is IST (UTC+5:30).
The WHERE bound is computed in Python as a UTC range from IST calendar dates
(`_utc_bounds`) so the raw column is filtered with no function wrapper --
sargable, and able to use ix_leads_created_at / ix_loan_applications_opened_at
/ ix_property_deals_opened_at. The GROUP BY bucket (`_bucket_col`) runs only
over the already-filtered set and buckets in IST wall-clock time: a row at
2026-07-26T19:00:00Z is Sunday in UTC but 00:30 Monday in IST, and must land
in the Monday-starting IST week, not the Sunday UTC one.

Agent attribution. The only agent FK in the schema is
Lead.origin_agent_profile_uuid (NULL unless origin == AGENT).
loan_applications and property_deals have no agent column of their own --
attribution is reached only by joining through lead_uuid. A lead/loan/deal
row with no agent is excluded from an agent-filtered query and from the
agents report's per-agent totals; it is never surfaced as a NULL bucket.

Agents-report fan-out trap. One agent can own many leads, each of which
owns at most one loan_application and one property_deal, but a single join
across all four tables would still multiply loan rows by deal rows for the
same agent. get_agents_report avoids this with three independent
GROUP BY origin_agent_profile_uuid subqueries, LEFT OUTER JOINed onto
agent_profiles, each COALESCEd to 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.lead_activity import LeadActivity
from app.models.loan import LoanApplication, LoanStatus
from app.models.profile import AgentProfile, ClientProfile
from app.models.property import Property
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.referral import Referral
from app.models.user import User, UserStatus
from app.services import audit_log

IST = ZoneInfo("Asia/Kolkata")

ReportBucketValue = Literal["week", "month"]
BusinessLineValue = Literal["loans", "real_estate"]
LeadSourceValue = Literal["direct", "agent", "client"]


@dataclass(frozen=True)
class ReportFilters:
    """Optional narrowing beyond date range, business line and agents.

    Lead-level filters (telecaller, source, lead status, latest call outcome
    and interest) apply to the leads report directly and to the loans/deals
    reports through their lead. Loan- and deal-level filters apply only to
    their own report. Every value is a whitelisted enum, UUID or a bounded
    plain string compared as a bound parameter, never interpolated.
    """

    telecaller_profile_uuids: tuple[UUID, ...] = ()
    lead_source: LeadSourceValue | None = None
    lead_status: str | None = None
    call_status: str | None = None
    interest: str | None = None
    loan_status: str | None = None
    loan_type_id: UUID | None = None
    bank_id: UUID | None = None
    deal_status: str | None = None
    property_city: str | None = None
    property_category: str | None = None

    @property
    def needs_lead(self) -> bool:
        return bool(
            self.telecaller_profile_uuids
            or self.lead_source
            or self.lead_status
            or self.call_status
            or self.interest
        )


NO_FILTERS = ReportFilters()


def _client_referred() -> ColumnElement:
    """The lead signed up through a client's referral code (see lead_list_signals)."""
    return exists().where(
        or_(Referral.referred_lead_uuid == Lead.id, Referral.referred_mobile == Lead.mobile)
    )


def _latest_call(column: ColumnElement) -> Any:
    return (
        select(column)
        .where(LeadActivity.lead_uuid == Lead.id)
        .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _lead_level_filters(filters: ReportFilters) -> list[ColumnElement]:
    """Predicates over ``Lead`` columns; the caller must have Lead in FROM."""
    out: list[ColumnElement] = []
    if filters.telecaller_profile_uuids:
        out.append(Lead.assigned_telecaller_profile_uuid.in_(filters.telecaller_profile_uuids))
    if filters.lead_source == "agent":
        out.append(Lead.origin == LeadOrigin.AGENT)
    elif filters.lead_source == "client":
        out.append(and_(Lead.origin == LeadOrigin.DIRECT, _client_referred()))
    elif filters.lead_source == "direct":
        out.append(and_(Lead.origin == LeadOrigin.DIRECT, not_(_client_referred())))
    if filters.lead_status:
        out.append(Lead.status == LeadStatus(filters.lead_status))
    if filters.call_status:
        out.append(_latest_call(LeadActivity.disposition) == filters.call_status)
    if filters.interest:
        out.append(_latest_call(LeadActivity.interest_level) == filters.interest)
    return out


# 50,000 rows is generous for anything FR-16 asks for and cheap to hold in a
# worker's memory; nothing in the spec caps export size, but an all-time
# range on a growing table would otherwise risk OOM-ing a worker.
EXPORT_ROW_CAP = 50_000


class InvalidSortField(ValueError):
    """Raised when a caller's sort_by isn't in the report's column whitelist.
    Never interpolate an unwhitelisted name into ORDER BY."""


def _utc_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC bound covering every IST calendar day from
    date_from through date_to, inclusive."""
    start = datetime.combine(date_from, time.min, tzinfo=IST).astimezone(UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=IST).astimezone(UTC)
    return start, end


def _bucket_col(column: ColumnElement, bucket: ReportBucketValue) -> ColumnElement:
    """Build once, reuse the same object in both the SELECT list and
    .group_by() -- date_trunc('week', ...) is ISO, Monday-start."""
    ist_wall_clock = func.timezone("Asia/Kolkata", column)
    truncated = func.date_trunc(bucket, ist_wall_clock)
    return func.timezone("Asia/Kolkata", truncated)


def _apply_sort(
    col_map: dict[str, ColumnElement], sort_by: str | None, *, default: str
) -> ColumnElement:
    key = sort_by or default
    if key not in col_map:
        raise InvalidSortField(key)
    return col_map[key]


def _order(col: ColumnElement, sort_dir: Literal["asc", "desc"]) -> ColumnElement:
    return col.desc() if sort_dir == "desc" else col.asc()


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


def _leads_filters(
    *,
    start: datetime,
    end: datetime,
    business_line: BusinessLineValue | None,
    agent_profile_uuids: list[UUID] | None,
    report_filters: ReportFilters = NO_FILTERS,
) -> list[ColumnElement]:
    filters: list[ColumnElement] = [Lead.created_at >= start, Lead.created_at < end]
    if business_line is not None:
        filters.append(Lead.business_line == business_line)
    if agent_profile_uuids:
        filters.append(Lead.origin_agent_profile_uuid.in_(agent_profile_uuids))
    filters.extend(_lead_level_filters(report_filters))
    return filters


async def get_leads_report(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    bucket: ReportBucketValue,
    business_line: BusinessLineValue | None = None,
    agent_profile_uuids: list[UUID] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
    report_filters: ReportFilters = NO_FILTERS,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    start, end = _utc_bounds(date_from, date_to)
    filters = _leads_filters(
        start=start,
        end=end,
        business_line=business_line,
        agent_profile_uuids=agent_profile_uuids,
        report_filters=report_filters,
    )

    bucket_col = _bucket_col(Lead.created_at, bucket).label("bucket_start")
    line_col = Lead.business_line.label("business_line")

    grouped = (
        select(
            bucket_col,
            line_col,
            func.count().label("total"),
            func.count().filter(Lead.status == LeadStatus.CONVERTED).label("converted"),
        )
        .where(*filters)
        .group_by(bucket_col, line_col)
    ).subquery()

    total_groups = await db.scalar(select(func.count()).select_from(grouped)) or 0

    col_map = {
        "bucket_start": grouped.c.bucket_start,
        "business_line": grouped.c.business_line,
        "total": grouped.c.total,
        "converted": grouped.c.converted,
    }
    sort_col = _apply_sort(col_map, sort_by, default="bucket_start")

    rows = (
        await db.execute(
            select(grouped)
            .order_by(_order(sort_col, sort_dir), grouped.c.bucket_start.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    summary_row = (
        await db.execute(
            select(
                func.count().label("total_count"),
                func.count().filter(Lead.status == LeadStatus.CONVERTED).label("converted_count"),
            ).where(*filters)
        )
    ).one()

    return (
        [dict(r._mapping) for r in rows],
        total_groups,
        {"total_count": summary_row.total_count, "converted_count": summary_row.converted_count},
    )


# ---------------------------------------------------------------------------
# Loans / Deals -- structurally identical, parameterized over the model
# ---------------------------------------------------------------------------


async def _get_journey_report(
    db: AsyncSession,
    *,
    model: type[LoanApplication] | type[PropertyDeal],
    time_col: ColumnElement,
    terminal_status: LoanStatus | PropertyDealStatus,
    date_from: date,
    date_to: date,
    bucket: ReportBucketValue,
    business_line: BusinessLineValue | None,
    agent_profile_uuids: list[UUID] | None,
    sort_by: str | None,
    sort_dir: Literal["asc", "desc"],
    limit: int,
    offset: int,
    report_filters: ReportFilters = NO_FILTERS,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    start, end = _utc_bounds(date_from, date_to)
    filters: list[ColumnElement] = [time_col >= start, time_col < end]
    if business_line is not None:
        filters.append(model.business_line == business_line)

    base_from: Any = model.__table__
    if agent_profile_uuids or report_filters.needs_lead:
        # One lead per application/deal, so this join never fans out.
        base_from = model.__table__.join(Lead.__table__, Lead.id == model.lead_uuid)
        if agent_profile_uuids:
            filters.append(Lead.origin_agent_profile_uuid.in_(agent_profile_uuids))
        filters.extend(_lead_level_filters(report_filters))

    if model is LoanApplication:
        if report_filters.loan_status:
            filters.append(LoanApplication.status == LoanStatus(report_filters.loan_status))
        if report_filters.loan_type_id:
            filters.append(LoanApplication.loan_type_id == report_filters.loan_type_id)
        if report_filters.bank_id:
            filters.append(LoanApplication.bank_id == report_filters.bank_id)
    else:
        if report_filters.deal_status:
            filters.append(PropertyDeal.status == PropertyDealStatus(report_filters.deal_status))
        if report_filters.property_city or report_filters.property_category:
            # Each deal has exactly one property: no fan-out.
            base_from = base_from.join(Property.__table__, Property.id == PropertyDeal.property_id)
            if report_filters.property_city:
                filters.append(
                    func.lower(Property.city) == report_filters.property_city.strip().lower()
                )
            if report_filters.property_category:
                filters.append(Property.category == report_filters.property_category)

    bucket_col = _bucket_col(time_col, bucket).label("bucket_start")
    line_col = model.business_line.label("business_line")

    grouped = (
        select(
            bucket_col,
            line_col,
            func.count().label("total"),
            func.count().filter(model.status == terminal_status).label("converted"),
        )
        .select_from(base_from)
        .where(*filters)
        .group_by(bucket_col, line_col)
    ).subquery()

    total_groups = await db.scalar(select(func.count()).select_from(grouped)) or 0

    col_map = {
        "bucket_start": grouped.c.bucket_start,
        "business_line": grouped.c.business_line,
        "total": grouped.c.total,
        "converted": grouped.c.converted,
    }
    sort_col = _apply_sort(col_map, sort_by, default="bucket_start")

    rows = (
        await db.execute(
            select(grouped)
            .order_by(_order(sort_col, sort_dir), grouped.c.bucket_start.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    summary_row = (
        await db.execute(
            select(
                func.count().label("total_count"),
                func.count().filter(model.status == terminal_status).label("converted_count"),
            )
            .select_from(base_from)
            .where(*filters)
        )
    ).one()

    return (
        [dict(r._mapping) for r in rows],
        total_groups,
        {"total_count": summary_row.total_count, "converted_count": summary_row.converted_count},
    )


async def get_loans_report(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    bucket: ReportBucketValue,
    business_line: BusinessLineValue | None = None,
    agent_profile_uuids: list[UUID] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
    report_filters: ReportFilters = NO_FILTERS,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    return await _get_journey_report(
        db,
        model=LoanApplication,
        time_col=LoanApplication.opened_at,
        terminal_status=LoanStatus.DISBURSED,
        date_from=date_from,
        date_to=date_to,
        bucket=bucket,
        business_line=business_line,
        agent_profile_uuids=agent_profile_uuids,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        report_filters=report_filters,
    )


async def get_deals_report(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    bucket: ReportBucketValue,
    business_line: BusinessLineValue | None = None,
    agent_profile_uuids: list[UUID] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
    report_filters: ReportFilters = NO_FILTERS,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    return await _get_journey_report(
        db,
        model=PropertyDeal,
        time_col=PropertyDeal.opened_at,
        terminal_status=PropertyDealStatus.CLOSED,
        date_from=date_from,
        date_to=date_to,
        bucket=bucket,
        business_line=business_line,
        agent_profile_uuids=agent_profile_uuids,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        report_filters=report_filters,
    )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


def _agent_activity_subquery(
    *,
    model: type[LoanApplication] | type[PropertyDeal] | type[Lead],
    time_col: ColumnElement,
    agent_col: ColumnElement,
    terminal_status: LeadStatus | LoanStatus | PropertyDealStatus | None,
    start: datetime,
    end: datetime,
    total_label: str,
    converted_label: str,
    join_leads: bool,
):
    filters: list[ColumnElement] = [agent_col.is_not(None), time_col >= start, time_col < end]
    base_from: Any = model.__table__
    if join_leads:
        base_from = model.__table__.join(Lead.__table__, Lead.id == model.lead_uuid)

    status_col = model.status if hasattr(model, "status") else None
    converted_expr = (
        func.count().filter(status_col == terminal_status)
        if status_col is not None and terminal_status is not None
        else func.count()
    )

    return (
        select(
            agent_col.label("agent_id"),
            func.count().label(total_label),
            converted_expr.label(converted_label),
        )
        .select_from(base_from)
        .where(*filters)
        .group_by(agent_col)
        .subquery()
    )


async def get_agents_report(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    business_line: BusinessLineValue | None = None,
    agent_profile_uuids: list[UUID] | None = None,
    sort_by: str | None = None,
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, dict[str, int], list[dict[str, Any]]]:
    start, end = _utc_bounds(date_from, date_to)

    leads_sub = _agent_activity_subquery(
        model=Lead,
        time_col=Lead.created_at,
        agent_col=Lead.origin_agent_profile_uuid,
        terminal_status=LeadStatus.CONVERTED,
        start=start,
        end=end,
        total_label="leads_total",
        converted_label="leads_converted",
        join_leads=False,
    )
    loans_sub = _agent_activity_subquery(
        model=LoanApplication,
        time_col=LoanApplication.opened_at,
        agent_col=Lead.origin_agent_profile_uuid,
        terminal_status=LoanStatus.DISBURSED,
        start=start,
        end=end,
        total_label="loans_total",
        converted_label="loans_converted",
        join_leads=True,
    )
    deals_sub = _agent_activity_subquery(
        model=PropertyDeal,
        time_col=PropertyDeal.opened_at,
        agent_col=Lead.origin_agent_profile_uuid,
        terminal_status=PropertyDealStatus.CLOSED,
        start=start,
        end=end,
        total_label="deals_total",
        converted_label="deals_converted",
        join_leads=True,
    )

    base = (
        select(
            AgentProfile.id.label("agent_profile_uuid"),
            AgentProfile.agent_code.label("agent_code"),
            AgentProfile.business_line.label("business_line"),
            User.first_name.label("first_name"),
            User.last_name.label("last_name"),
            func.coalesce(leads_sub.c.leads_total, 0).label("leads_total"),
            func.coalesce(leads_sub.c.leads_converted, 0).label("leads_converted"),
            func.coalesce(loans_sub.c.loans_total, 0).label("loans_total"),
            func.coalesce(loans_sub.c.loans_converted, 0).label("loans_converted"),
            func.coalesce(deals_sub.c.deals_total, 0).label("deals_total"),
            func.coalesce(deals_sub.c.deals_converted, 0).label("deals_converted"),
        )
        .select_from(AgentProfile)
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .outerjoin(leads_sub, leads_sub.c.agent_id == AgentProfile.id)
        .outerjoin(loans_sub, loans_sub.c.agent_id == AgentProfile.id)
        .outerjoin(deals_sub, deals_sub.c.agent_id == AgentProfile.id)
    )
    if business_line is not None:
        base = base.where(AgentProfile.business_line == business_line)
    if agent_profile_uuids:
        base = base.where(AgentProfile.id.in_(agent_profile_uuids))

    base_subq = base.subquery()

    total_agents = await db.scalar(select(func.count()).select_from(base_subq)) or 0

    summary_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(base_subq.c.leads_total), 0).label("leads_total"),
                func.coalesce(func.sum(base_subq.c.leads_converted), 0).label("leads_converted"),
                func.coalesce(func.sum(base_subq.c.loans_total), 0).label("loans_total"),
                func.coalesce(func.sum(base_subq.c.loans_converted), 0).label("loans_converted"),
                func.coalesce(func.sum(base_subq.c.deals_total), 0).label("deals_total"),
                func.coalesce(func.sum(base_subq.c.deals_converted), 0).label("deals_converted"),
            )
        )
    ).one()

    col_map = {
        "agent_code": base_subq.c.agent_code,
        "business_line": base_subq.c.business_line,
        "leads_total": base_subq.c.leads_total,
        "leads_converted": base_subq.c.leads_converted,
        "loans_total": base_subq.c.loans_total,
        "loans_converted": base_subq.c.loans_converted,
        "deals_total": base_subq.c.deals_total,
        "deals_converted": base_subq.c.deals_converted,
    }
    sort_col = _apply_sort(col_map, sort_by, default="leads_total")

    rows = (
        await db.execute(
            select(base_subq)
            .order_by(_order(sort_col, sort_dir), base_subq.c.agent_code.asc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    result_rows = [
        {
            "agent_profile_uuid": r.agent_profile_uuid,
            "agent_code": r.agent_code,
            "agent_name": f"{r.first_name} {r.last_name}".strip(),
            "business_line": r.business_line,
            "leads_total": r.leads_total,
            "leads_converted": r.leads_converted,
            "loans_total": r.loans_total,
            "loans_converted": r.loans_converted,
            "deals_total": r.deals_total,
            "deals_converted": r.deals_converted,
        }
        for r in rows
    ]

    summary = {"agent_count": total_agents, **dict(summary_row._mapping)}

    # Agents are line-scoped in the canonical profile model. The two business
    # lines are therefore the only approved team dimension; do not infer a
    # mutable team or membership model that does not exist in the database.
    team_rows = (
        await db.execute(
            select(
                base_subq.c.business_line,
                func.count().label("agent_count"),
                func.coalesce(func.sum(base_subq.c.leads_total), 0).label("leads_total"),
                func.coalesce(func.sum(base_subq.c.leads_converted), 0).label("leads_converted"),
                func.coalesce(func.sum(base_subq.c.loans_total), 0).label("loans_total"),
                func.coalesce(func.sum(base_subq.c.loans_converted), 0).label("loans_converted"),
                func.coalesce(func.sum(base_subq.c.deals_total), 0).label("deals_total"),
                func.coalesce(func.sum(base_subq.c.deals_converted), 0).label("deals_converted"),
            )
            .group_by(base_subq.c.business_line)
            .order_by(base_subq.c.business_line.asc())
        )
    ).all()

    return result_rows, total_agents, summary, [dict(r._mapping) for r in team_rows]


# ---------------------------------------------------------------------------
# Export -- fetch-then-format, all DB work happens before StreamingResponse
# is constructed (see api/v1/reporting.py's module docstring for why).
# ---------------------------------------------------------------------------

ReportKind = Literal["leads", "loans", "deals", "agents"]

_JOURNEY_HEADER = ["bucket_start", "business_line", "total", "converted"]
_AGENTS_HEADER = [
    "agent_code",
    "agent_name",
    "business_line",
    "leads_total",
    "leads_converted",
    "loans_total",
    "loans_converted",
    "deals_total",
    "deals_converted",
]


@dataclass(frozen=True)
class ExportParams:
    date_from: date
    date_to: date
    bucket: ReportBucketValue
    business_line: str | None
    agent_profile_uuids: list[UUID] | None
    report_filters: ReportFilters = NO_FILTERS


async def export_report_rows(
    db: AsyncSession, kind: ReportKind, params: ExportParams
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Fetch every row matching the filters (capped at EXPORT_ROW_CAP + 1 so
    truncation can be detected), independent of the JSON endpoint's
    limit/offset. Returns (rows, header, truncated)."""
    fetch_limit = EXPORT_ROW_CAP + 1

    if kind == "leads":
        rows, _total, _summary = await get_leads_report(
            db,
            date_from=params.date_from,
            date_to=params.date_to,
            bucket=params.bucket,
            business_line=params.business_line,  # type: ignore[arg-type]
            agent_profile_uuids=params.agent_profile_uuids,
            sort_by="bucket_start",
            sort_dir="asc",
            limit=fetch_limit,
            offset=0,
            report_filters=params.report_filters,
        )
        header = _JOURNEY_HEADER
    elif kind == "loans":
        rows, _total, _summary = await get_loans_report(
            db,
            date_from=params.date_from,
            date_to=params.date_to,
            bucket=params.bucket,
            business_line=params.business_line,  # type: ignore[arg-type]
            agent_profile_uuids=params.agent_profile_uuids,
            sort_by="bucket_start",
            sort_dir="asc",
            limit=fetch_limit,
            offset=0,
            report_filters=params.report_filters,
        )
        header = _JOURNEY_HEADER
    elif kind == "deals":
        rows, _total, _summary = await get_deals_report(
            db,
            date_from=params.date_from,
            date_to=params.date_to,
            bucket=params.bucket,
            business_line=params.business_line,  # type: ignore[arg-type]
            agent_profile_uuids=params.agent_profile_uuids,
            sort_by="bucket_start",
            sort_dir="asc",
            limit=fetch_limit,
            offset=0,
            report_filters=params.report_filters,
        )
        header = _JOURNEY_HEADER
    else:
        rows, _total, _summary, _team_summaries = await get_agents_report(
            db,
            date_from=params.date_from,
            date_to=params.date_to,
            business_line=params.business_line,  # type: ignore[arg-type]
            agent_profile_uuids=params.agent_profile_uuids,
            sort_by="leads_total",
            sort_dir="desc",
            limit=fetch_limit,
            offset=0,
        )
        header = _AGENTS_HEADER

    truncated = len(rows) > EXPORT_ROW_CAP
    if truncated:
        rows = rows[:EXPORT_ROW_CAP]
    return rows, header, truncated


async def list_telecaller_options(
    db: AsyncSession, business_line: BusinessLineValue | None = None
) -> list[dict[str, Any]]:
    """Telecaller staff profiles for the report filter, ordered by staff code."""
    from app.models.profile import StaffProfile, StaffRole

    stmt = (
        select(
            StaffProfile.id.label("staff_profile_uuid"),
            StaffProfile.staff_code,
            StaffProfile.business_line,
            User.first_name,
            User.last_name,
        )
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(StaffProfile.role == StaffRole.TELECALLER)
        .order_by(StaffProfile.staff_code)
        .limit(500)
    )
    if business_line is not None:
        stmt = stmt.where(StaffProfile.business_line.in_((business_line, "both")))
    rows = (await db.execute(stmt)).all()
    return [
        {
            "staff_profile_uuid": row.staff_profile_uuid,
            "staff_code": row.staff_code,
            "business_line": row.business_line,
            "name": f"{row.first_name} {row.last_name}".strip(),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Client-roster export (admin-only, bulk client PII)
# ---------------------------------------------------------------------------
#
# Distinct from the aggregate leads/loans/deals/agents exports above: those
# stream *counts* per time bucket and write no audit row (reads of derived
# numbers). This one streams row-level client contact data -- every client's
# name and mobile across both business lines -- so it is a bulk-PII export and
# records an audit entry (security-review decision, feature-status.md §3 #2).
#
# Columns are deliberately limited to id / name / phone / created_at /
# updated_at. password_hash is NEVER selected or emitted: it is a one-way
# credential hash whose export is forbidden by SECURITY.md, and there is no
# cleartext password column to export even if one were asked for.
#
# "CLIENT user" == an auth_users row that owns at least one client_profiles
# row. A user is returned at most once even if they hold a client profile in
# both lines (IN-subquery, not a join, so no fan-out). Soft-deleted (tombstoned)
# accounts are excluded: their PII is on its way to a retention purge and must
# not be re-surfaced in a bulk download -- the same posture get_current_user and
# audit_log._resolve_actors already take toward SOFT_DELETED.
#
# Runs on the request-scoped `db` session, so the caller's RLS context applies:
# only a platform Admin (role='admin' AND platform_scope='true') bypasses the
# auth_users_rls / client_profiles_rls line predicates and sees both lines; the
# router's require_platform_admin is the access gate in front of that wall.

_CLIENTS_HEADER = ["id", "name", "phone", "created_at", "updated_at"]


def _fmt_dt(value: datetime | None) -> str:
    """IST (business timezone) ISO-8601, e.g. 2026-11-16T14:30:00+05:30 -- date
    and time, unambiguous and round-trippable, matching this module's IST-first
    convention for every other time column."""
    if value is None:
        return ""
    return value.astimezone(IST).isoformat()


async def export_client_rows(
    db: AsyncSession,
    *,
    actor_uuid: UUID,
    actor_role: str | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Fetch every client account (capped at EXPORT_ROW_CAP + 1 to detect
    truncation) and record the bulk-PII download in the audit log on the same
    session. Does not commit -- the router owns the commit, matching this
    codebase's service/router boundary. Returns (rows, header, truncated)."""
    fetch_limit = EXPORT_ROW_CAP + 1

    client_user_ids = select(ClientProfile.auth_user_uuid)
    result = (
        await db.execute(
            select(
                User.id,
                User.first_name,
                User.last_name,
                User.mobile,
                User.created_at,
                User.updated_at,
            )
            .where(User.id.in_(client_user_ids))
            .where(User.status != UserStatus.SOFT_DELETED)
            .order_by(User.created_at.asc(), User.id.asc())
            .limit(fetch_limit)
        )
    ).all()

    truncated = len(result) > EXPORT_ROW_CAP
    if truncated:
        result = result[:EXPORT_ROW_CAP]

    rows: list[dict[str, Any]] = [
        {
            "id": str(r.id),
            "name": f"{r.first_name} {r.last_name}".strip(),
            "phone": r.mobile,
            "created_at": _fmt_dt(r.created_at),
            "updated_at": _fmt_dt(r.updated_at),
        }
        for r in result
    ]

    await audit_log.record(
        db,
        action=AuditAction.CLIENT_EXPORT_DOWNLOADED,
        entity_type="client_export",
        entity_uuid=None,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=None,
        detail={"exported_client_count": len(rows), "format": "csv", "truncated": truncated},
    )

    return rows, _CLIENTS_HEADER, truncated
