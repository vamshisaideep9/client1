"""Personal analytics for Telecallers, Employees, Agents and Sub Admins.

One generic shape for every role so the web renders all of them with the same
chart components: headline KPIs, one day-by-day trend, a few category
breakdowns and an optional funnel. Every number is computed server-side from
the caller's own scope (assigned leads, own calls, own tasks, own leads
introduced, own content); nothing is selected by a client-supplied id.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

AnalyticsRole = Literal["telecaller", "employee", "agent", "sub_admin"]
KpiUnit = Literal["count", "percent", "hours", "rupees"]


class AnalyticsKpi(BaseModel):
    key: str
    label: str
    value: float | None
    unit: KpiUnit
    hint: str | None = None


class TrendSeries(BaseModel):
    key: str
    label: str


class TrendPoint(BaseModel):
    day: date
    values: dict[str, int]


class AnalyticsTrend(BaseModel):
    title: str
    description: str
    series: list[TrendSeries]
    points: list[TrendPoint]


class BreakdownItem(BaseModel):
    key: str
    label: str
    value: float


class AnalyticsBreakdown(BaseModel):
    key: str
    title: str
    description: str
    kind: Literal["share", "ranked"]
    unit: KpiUnit = "count"
    items: list[BreakdownItem]


class FunnelStep(BaseModel):
    key: str
    label: str
    value: int


class AnalyticsFunnel(BaseModel):
    title: str
    description: str
    steps: list[FunnelStep]


class StaffAnalyticsResponse(BaseModel):
    role: AnalyticsRole
    range_days: int
    # Inclusive India Standard Time calendar dates covered by the period.
    date_from: date
    date_to: date
    # Trend points are per day up to 92 days, then per Monday-start week
    # (a point's ``day`` is then the first day of that week in the period).
    bucket: Literal["day", "week"] = "day"
    kpis: list[AnalyticsKpi]
    trend: AnalyticsTrend
    breakdowns: list[AnalyticsBreakdown]
    funnel: AnalyticsFunnel | None = None
    # Filters of this role the caller cannot use because the Admin hides the
    # field behind them (CS-023: a Telecaller's amount range); the API refuses
    # them with 422, so the page leaves them out.
    hidden_filters: list[str] = Field(default_factory=list)
