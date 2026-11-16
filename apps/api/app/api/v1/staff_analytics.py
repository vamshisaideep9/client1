"""GET /api/v1/me/analytics — the caller's own analytics (see the service).

The role and the profile used for every filter come from the verified token
(CurrentUser), never from the request. Admin keeps its platform reports in
api/v1/reporting.py; Clients have no analytics.

Period: either ``date_from`` + ``date_to`` (inclusive IST calendar dates, at
most 366 days, not in the future) or the legacy ``days`` (snapped to 7/30/90
and ending today). Business line: always the request's effective line (the
dashboard line switcher's X-Business-Line header, validated against the
token), so analytics never disagree with the line-scoped RLS of the same
request. Every other filter only narrows the caller's own rows, and a filter
that does not apply to the caller's role is rejected rather than ignored.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user
from app.db.session import get_db
from app.schemas.staff_analytics import StaffAnalyticsResponse
from app.services.staff_analytics import (
    AnalyticsWindow,
    InvalidAnalyticsWindow,
    StaffAnalyticsFilters,
    agent_analytics,
    employee_analytics,
    resolve_analytics_window,
    sub_admin_analytics,
    telecaller_analytics,
)

router = APIRouter()

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
_LeadStatus = Literal["new", "assigned", "working", "converted", "closed", "released"]
_TaskType = Literal["document_collection", "property_visit", "background_check"]
_ContentStatus = Literal["draft", "pending_approval", "approved", "live", "rejected", "archived"]
_Placement = Literal["homepage", "financial_services", "properties", "dashboard", "homepage_ad"]

# Which optional filters each role's analytics understand.
_ROLE_FILTERS: dict[str, set[str]] = {
    "telecaller": {"call_status", "interest", "loan_status", "lead_source"},
    "employee": {"task_type"},
    "agent": {"lead_status"},
    "sub_admin": {"content_type", "content_status", "placement", "banner_type", "discount_type"},
}


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _window(
    date_from: date | None, date_to: date | None, days: int, now: datetime
) -> AnalyticsWindow:
    try:
        return resolve_analytics_window(date_from, date_to, days, now)
    except InvalidAnalyticsWindow as exc:
        raise _unprocessable(str(exc)) from exc


@router.get("/analytics", response_model=StaffAnalyticsResponse)
async def my_analytics(
    response: Response,
    days: int = Query(30, ge=1, le=365, description="Legacy period in days (7, 30 or 90)."),
    date_from: date | None = Query(None, description="First IST day of the period, inclusive."),
    date_to: date | None = Query(None, description="Last IST day of the period, inclusive."),
    call_status: _CallStatus | None = Query(None, description="Telecaller: calls with outcome."),
    interest: Literal["hot", "warm", "cold"] | None = Query(
        None, description="Telecaller: calls with this interest level."
    ),
    loan_status: _LoanStatus | None = Query(
        None, description="Telecaller: leads with a loan application in this status."
    ),
    lead_source: Literal["direct", "agent", "client"] | None = Query(
        None, description="Telecaller: leads from this referral source."
    ),
    lead_status: _LeadStatus | None = Query(None, description="Agent: leads in this status."),
    task_type: _TaskType | None = Query(None, description="Employee: tasks of this type."),
    content_type: Literal["banners", "offers"] | None = Query(
        None, description="Sub Admin: only banners or only offers."
    ),
    content_status: _ContentStatus | None = Query(
        None,
        description=(
            "Sub Admin: content in this review status. For offers, approved includes "
            "scheduled, live means active and archived includes expired."
        ),
    ),
    placement: _Placement | None = Query(
        None, description="Sub Admin: banners in this placement (leaves offers out)."
    ),
    banner_type: Literal["default", "personalized", "action"] | None = Query(
        None, description="Sub Admin: banners of this type (leaves offers out)."
    ),
    discount_type: Literal["percentage", "flat", "cashback-tie"] | None = Query(
        None, description="Sub Admin: offers with this discount type (leaves banners out)."
    ),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> StaffAnalyticsResponse:
    response.headers["Cache-Control"] = "private, no-store"
    now = datetime.now(UTC)
    role = current_user.role
    window = _window(date_from, date_to, days, now)

    requested = {
        name
        for name, value in (
            ("call_status", call_status),
            ("interest", interest),
            ("loan_status", loan_status),
            ("lead_source", lead_source),
            ("lead_status", lead_status),
            ("task_type", task_type),
            ("content_type", content_type),
            ("content_status", content_status),
            ("placement", placement),
            ("banner_type", banner_type),
            ("discount_type", discount_type),
        )
        if value is not None
    }
    unsupported = requested - _ROLE_FILTERS.get(role, set())
    if role in _ROLE_FILTERS and unsupported:
        raise _unprocessable(
            f"Filter not available for this role: {', '.join(sorted(unsupported))}."
        )

    line = current_user.business_line
    filters = StaffAnalyticsFilters(
        business_line=line if line in ("loans", "real_estate") else None,
        call_status=call_status,
        interest=interest,
        loan_status=loan_status,
        lead_source=lead_source,
        lead_status=lead_status,
        task_type=task_type,
        content_type=content_type,
        content_status=content_status,
        placement=placement,
        banner_type=banner_type,
        discount_type=discount_type,
    )

    if role in ("telecaller", "employee"):
        if current_user.staff_profile_uuid is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No staff profile on this account.")
        builder = telecaller_analytics if role == "telecaller" else employee_analytics
        return await builder(db, current_user.staff_profile_uuid, window, now, filters)
    if role == "agent":
        if current_user.agent_profile_uuid is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No agent profile on this account.")
        return await agent_analytics(
            db, current_user.agent_profile_uuid, current_user.id, window, now, filters
        )
    if role == "sub_admin":
        return await sub_admin_analytics(db, current_user.id, window, now, filters)
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Personal analytics are for staff and agent accounts."
    )
