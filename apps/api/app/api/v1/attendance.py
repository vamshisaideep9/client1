"""Staff attendance and review, with platform Admin policy and export."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brand import branded_filename
from app.core.deps import (
    CurrentUser,
    get_active_user,
    require_platform_admin,
    require_sub_admin_or_platform_admin,
)
from app.db.session import get_db
from app.models.audit_log import AuditAction
from app.schemas.attendance import (
    AttendanceCorrectionInput,
    AttendanceDayRead,
    AttendanceDecisionInput,
    AttendanceHolidayInput,
    AttendanceHolidayRead,
    AttendanceInboxRead,
    AttendanceLeaveInput,
    AttendancePolicyInput,
    AttendancePolicyState,
    AttendanceRequestRead,
    AttendanceRosterRead,
    AttendanceStatus,
    MyAttendanceRead,
    RequestStatus,
)
from app.services import attendance, attendance_requests, attendance_views
from app.services.audit_log import record
from app.services.csv_export import csv_chunks


class AttendanceRoute(APIRoute):
    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle(request):
            try:
                return await route_handler(request)
            except attendance.AttendanceError as exc:
                raise HTTPException(exc.status, detail=str(exc)) from exc

        return handle


router = APIRouter(route_class=AttendanceRoute)


async def require_attendance_staff(user: CurrentUser = Depends(get_active_user)) -> CurrentUser:
    if user.role not in attendance.STAFF_ROLES or user.staff_profile_uuid is None:
        raise HTTPException(
            403, detail="Only Telecallers and Employees can use the attendance clock."
        )
    return user


Staff = Annotated[CurrentUser, Depends(require_attendance_staff)]
Reviewer = Annotated[CurrentUser, Depends(require_sub_admin_or_platform_admin)]
Admin = Annotated[CurrentUser, Depends(require_platform_admin)]
DB = Annotated[AsyncSession, Depends(get_db)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/me", response_model=MyAttendanceRead)
async def my_attendance(
    user: Staff,
    db: DB,
    year: Annotated[int | None, Query(ge=2000, le=9998)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
):
    return await attendance_views.personal(db, user.staff_profile_uuid, year, month)


@router.post("/check-in", response_model=AttendanceDayRead)
async def check_in(user: Staff):
    return await attendance.check_clock(user, checking_in=True)


@router.post("/check-out", response_model=AttendanceDayRead)
async def check_out(user: Staff):
    return await attendance.check_clock(user, checking_in=False)


@router.post("/corrections", response_model=AttendanceRequestRead, status_code=201)
async def request_correction(payload: AttendanceCorrectionInput, user: Staff):
    return await attendance_requests.submit(user, payload)


@router.post("/leave", response_model=AttendanceRequestRead, status_code=201)
async def request_leave(payload: AttendanceLeaveInput, user: Staff):
    return await attendance_requests.submit(user, payload)


@router.post("/requests/{request_id}/cancel", response_model=AttendanceRequestRead)
async def cancel_request(request_id: UUID, user: Staff):
    return await attendance_requests.cancel(user, request_id)


@router.get("/roster", response_model=AttendanceRosterRead)
async def get_roster(
    _: Reviewer,
    db: DB,
    start: date,
    end: date,
    team_id: UUID | None = None,
    staff_id: UUID | None = None,
    status: AttendanceStatus | None = None,
    limit: PageSize = 50,
    offset: Offset = 0,
):
    return await attendance_views.roster(
        db,
        start=start,
        end=end,
        team_id=team_id,
        staff_id=staff_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/requests", response_model=AttendanceInboxRead)
async def get_requests(
    _: Reviewer,
    db: DB,
    status: RequestStatus | None = "pending",
    team_id: UUID | None = None,
    staff_id: UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: PageSize = 50,
    offset: Offset = 0,
):
    if start is not None and end is not None:
        attendance_views.validate_period(start, end)
    return await attendance_views.inbox(
        db,
        status=status,
        team_id=team_id,
        staff_id=staff_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


@router.post("/requests/{request_id}/decision", response_model=AttendanceRequestRead)
async def decide_request(request_id: UUID, payload: AttendanceDecisionInput, user: Reviewer):
    return await attendance_requests.decide(user, request_id, payload)


@router.get("/policy", response_model=AttendancePolicyState)
async def get_policy(_: Admin, db: DB):
    return await attendance.policy_state(db)


@router.put("/policy", response_model=AttendancePolicyState)
async def put_policy(payload: AttendancePolicyInput, user: Admin):
    return await attendance.configure_policy(user, payload)


@router.get("/holidays", response_model=list[AttendanceHolidayRead])
async def get_holidays(_: Admin, db: DB, start: date, end: date):
    attendance_views.validate_period(start, end)
    return await attendance_views.holidays(db, start, end)


@router.put("/holidays/{day}", status_code=204)
async def put_holiday(day: date, payload: AttendanceHolidayInput, user: Admin):
    await attendance.configure_holiday(user, day, payload.name)
    return Response(status_code=204)


@router.delete("/holidays/{day}", status_code=204)
async def delete_holiday(day: date, user: Admin):
    await attendance.configure_holiday(user, day, None)
    return Response(status_code=204)


@router.get("/export", response_class=StreamingResponse)
async def export_attendance(
    user: Admin,
    db: DB,
    start: date,
    end: date,
    team_id: UUID | None = None,
    staff_id: UUID | None = None,
    status: AttendanceStatus | None = None,
):
    await attendance.require_policy(db, attendance.work_date(attendance.utc_now()))
    report = await attendance_views.roster(
        db,
        start=start,
        end=end,
        team_id=team_id,
        staff_id=staff_id,
        status=status,
        limit=500,
        offset=0,
    )
    members = {member.staff_profile_id: member for member in report.members}
    header = [
        "staff_code",
        "name",
        "role",
        "date",
        "status",
        "check_in_ist",
        "check_out_ist",
        "worked_minutes",
        "late",
        "leave_half_days",
    ]
    rows = [
        dict(
            zip(
                header,
                [
                    members[row.staff_profile_id].staff_code,
                    members[row.staff_profile_id].name,
                    members[row.staff_profile_id].role,
                    row.day,
                    row.status,
                    row.check_in.astimezone(attendance.IST).isoformat() if row.check_in else "",
                    row.check_out.astimezone(attendance.IST).isoformat() if row.check_out else "",
                    row.worked_minutes,
                    row.late,
                    row.leave_units,
                ],
                strict=True,
            )
        )
        for row in report.days
        if status is None or row.status == status
    ]
    await record(
        db,
        action=AuditAction.ATTENDANCE_EXPORTED,
        entity_type="staff_attendance",
        entity_uuid=None,
        actor_uuid=user.id,
        actor_role=user.role,
        detail={"start": str(start), "end": str(end), "rows": len(rows)},
    )
    await db.commit()
    name = branded_filename(f"attendance-{start}_{end}.csv")
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    if report.total > len(report.members):
        headers["X-Report-Truncated"] = "true"
    return StreamingResponse(csv_chunks(rows, header), media_type="text/csv", headers=headers)
