"""/api/v1/products — one dashboard per financial product (2026-11-26).

Platform Admin reads every product with platform scope. A Team Manager Sub
Admin with a ``team_manager`` ``view`` grant on ``loans`` reads the same shape
limited to the members of their own active Loans teams and those members'
work; the ``team_manager_reaches`` RLS policies enforce that reach again in
the database. Everyone else gets 403. The scope is always derived from the
verified token, never from the request.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    check_assignment_line,
    is_platform_admin,
    require_assignment,
)
from app.db.session import get_db
from app.schemas.product_dashboards import ProductDashboardResponse
from app.services.product_dashboard import (
    PLATFORM_SCOPE,
    DashboardScope,
    ProductNotFound,
    product_dashboard,
    team_scope,
)
from app.services.staff_analytics import (
    AnalyticsWindow,
    InvalidAnalyticsWindow,
    resolve_analytics_window,
)
from app.services.team_manager import list_my_teams

router = APIRouter()

_viewer = require_assignment("team_manager", "view", include_admin=True)
_OUTSIDE_LINES = "This operation is outside your assigned business lines."


async def dashboard_scope(
    user: CurrentUser = Depends(_viewer),
    db: AsyncSession = Depends(get_db),
) -> DashboardScope:
    """Platform scope for platform Admin; otherwise the caller's own Loans teams.

    A Sub Admin needs Team Manager view access on the loans line and at least
    one active Loans team they manage.
    """
    if is_platform_admin(user):
        return PLATFORM_SCOPE
    check_assignment_line(user, "team_manager", "view", "loans")
    if user.staff_profile_uuid is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No staff profile on this account.")
    teams = [
        team
        for team in await list_my_teams(db, user.staff_profile_uuid)
        if team.business_line == "loans"
    ]
    if not teams:
        raise HTTPException(status.HTTP_403_FORBIDDEN, _OUTSIDE_LINES)
    return team_scope(teams)


def _window(
    days: int = Query(30, ge=1, le=365, description="Period in days (7, 30 or 90)."),
    date_from: date | None = Query(None, description="First IST day of the period, inclusive."),
    date_to: date | None = Query(None, description="Last IST day of the period, inclusive."),
) -> AnalyticsWindow:
    try:
        return resolve_analytics_window(date_from, date_to, days, datetime.now(UTC))
    except InvalidAnalyticsWindow as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/{product_id}/dashboard", response_model=ProductDashboardResponse)
async def get_product_dashboard(
    product_id: UUID,
    response: Response,
    window: AnalyticsWindow = Depends(_window),
    scope: DashboardScope = Depends(dashboard_scope),
    db: AsyncSession = Depends(get_db),
) -> ProductDashboardResponse:
    """KPIs, requests by status, a weekly trend and the staff table for one
    product. The default period is the last 30 IST days."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await product_dashboard(db, product_id, window, scope)
    except ProductNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from exc
