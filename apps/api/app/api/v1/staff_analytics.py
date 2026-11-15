"""GET /api/v1/me/analytics — the caller's own analytics (see the service).

The role and the profile used for every filter come from the verified token
(CurrentUser), never from the request. Admin keeps its platform reports in
api/v1/reporting.py; Clients have no analytics.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_active_user
from app.db.session import get_db
from app.schemas.staff_analytics import StaffAnalyticsResponse
from app.services.staff_analytics import (
    agent_analytics,
    clamp_range,
    employee_analytics,
    sub_admin_analytics,
    telecaller_analytics,
)

router = APIRouter()


@router.get("/analytics", response_model=StaffAnalyticsResponse)
async def my_analytics(
    response: Response,
    days: int = Query(30, ge=1, le=365, description="Period in days (7, 30 or 90)."),
    current_user: CurrentUser = Depends(get_active_user),
    db: AsyncSession = Depends(get_db),
) -> StaffAnalyticsResponse:
    response.headers["Cache-Control"] = "private, no-store"
    period = clamp_range(days)
    now = datetime.now(UTC)
    role = current_user.role

    if role in ("telecaller", "employee"):
        if current_user.staff_profile_uuid is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No staff profile on this account.")
        builder = telecaller_analytics if role == "telecaller" else employee_analytics
        return await builder(db, current_user.staff_profile_uuid, period, now)
    if role == "agent":
        if current_user.agent_profile_uuid is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No agent profile on this account.")
        return await agent_analytics(
            db, current_user.agent_profile_uuid, current_user.id, period, now
        )
    if role == "sub_admin":
        return await sub_admin_analytics(db, current_user.id, period, now)
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Personal analytics are for staff and agent accounts."
    )
