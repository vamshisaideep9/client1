"""Staff attendance and review, with platform Admin policy and export."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_keys import RedisCache
from app.core.brand import branded_filename
from app.core.deps import (
    CurrentUser,
    get_cache,
    get_personal_user,
    require_assignment,
    require_platform_admin,
)
from app.db.session import get_db
from app.models.attendance import AttendanceEmployment
from app.models.audit_log import AuditAction
from app.models.profile import StaffProfile, StaffRole
from app.models.staff_team import StaffTeam
from app.schemas.attendance import (
    AttendanceAdjustmentInput,
    AttendanceCorrectionInput,
    AttendanceDayRead,
    AttendanceDecisionInput,
    AttendanceEmploymentInput,
    AttendanceEmploymentRead,
    AttendanceHolidayInput,
    AttendanceHolidayRead,
    AttendanceInboxRead,
    AttendanceLeaveInput,
    AttendanceLine,
    AttendancePolicyInput,
    AttendancePolicyState,
    AttendanceRequestRead,
    AttendanceRosterMember,
    AttendanceRosterRead,
    AttendanceStatus,
    MyAttendanceRead,
    RequestStatus,
)
from app.services import (
    attendance,
    attendance_certificates,
    attendance_employment,
    attendance_requests,
    attendance_views,
)
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


async def require_attendance_staff(user: CurrentUser = Depends(get_personal_user)) -> CurrentUser:
    if user.sub_admin_access is not None and user.sub_admin_access.status != "active":
        raise HTTPException(403, detail="Attendance is available once access is activated.")
    if user.role not in attendance.STAFF_ROLES or user.staff_profile_uuid is None:
        raise HTTPException(
            403, detail="Only Telecallers, Officers, and Sub Admins can use the attendance clock."
        )
    return user


Staff = Annotated[CurrentUser, Depends(require_attendance_staff)]
Reviewer = Annotated[
    CurrentUser, Depends(require_assignment("team_manager", "review", include_admin=True))
]
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
    return await attendance_views.personal(
        db, user.staff_profile_uuid, user.role, year, month, user.business_line
    )


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


@router.post("/regularizations", response_model=AttendanceRequestRead, status_code=201)
async def request_regularization(payload: AttendanceAdjustmentInput, user: Staff):
    return await attendance_requests.submit(user, payload)


@router.post("/requests/{request_id}/cancel", response_model=AttendanceRequestRead)
async def cancel_request(request_id: UUID, user: Staff):
    return await attendance_requests.cancel(user, request_id)


@router.post("/requests/{request_id}/certificate", status_code=204)
async def attach_certificate(
    request_id: UUID,
    user: Staff,
    file: Annotated[UploadFile, File()],
    cache: Annotated[RedisCache, Depends(get_cache)],
):
    await attendance_certificates.upload(user, request_id, file, cache)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.get("/requests/{request_id}/certificate", response_class=Response)
async def download_certificate(
    request_id: UUID, user: Annotated[CurrentUser, Depends(get_personal_user)], db: DB
):
    content, media_type, extension = await attendance_certificates.download(db, user, request_id)
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="medical-certificate.{extension}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _check_team_review(db: DB, user: CurrentUser, team_id: UUID | None) -> None:
    if user.role == StaffRole.SUB_ADMIN:
        await db.execute(text("SELECT set_config('app.team_review', 'true', true)"))
    if user.sub_admin_access is None:
        return
    if team_id is None:
        return
    line = await db.scalar(
        select(StaffTeam.business_line).where(
            StaffTeam.id == team_id,
            StaffTeam.manager_staff_profile_uuid == user.staff_profile_uuid,
        )
    )
    if line not in user.sub_admin_access.lines_for("team_manager", "review"):
        raise HTTPException(404, detail="Team not found.")


@router.get("/roster", response_model=AttendanceRosterRead)
async def get_roster(
    user: Reviewer,
    db: DB,
    start: date,
    end: date,
    team_id: UUID | None = None,
    staff_id: UUID | None = None,
    status: AttendanceStatus | None = None,
    limit: PageSize = 50,
    offset: Offset = 0,
):
    await _check_team_review(db, user, team_id)
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
    user: Reviewer,
    db: DB,
    status: RequestStatus | None = "pending",
    team_id: UUID | None = None,
    staff_id: UUID | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: PageSize = 50,
    offset: Offset = 0,
):
    await _check_team_review(db, user, team_id)
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
    if user.sub_admin_access is not None and payload.stage != "recommendation":
        raise HTTPException(403, detail="Only a platform Admin can make a final decision.")
    return await attendance_requests.decide(user, request_id, payload)


@router.get("/policy", response_model=AttendancePolicyState)
async def get_policy(user: Admin, db: DB):
    primary = await db.scalar(
        select(StaffProfile.is_primary_admin).where(
            StaffProfile.id == user.staff_profile_uuid,
            StaffProfile.auth_user_uuid == user.id,
        )
    )
    return await attendance.policy_state(db, can_configure_leave_rules=bool(primary))


@router.put("/policy", response_model=AttendancePolicyState)
async def put_policy(payload: AttendancePolicyInput, user: Admin):
    return await attendance.configure_policy(user, payload)


@router.get("/holidays", response_model=list[AttendanceHolidayRead])
async def get_holidays(
    _: Admin, db: DB, start: date, end: date, business_line: AttendanceLine | None = None
):
    attendance_views.validate_period(start, end)
    return await attendance_views.holidays(db, start, end, business_line)


@router.put("/holidays/{day}", status_code=204)
async def put_holiday(
    day: date,
    payload: AttendanceHolidayInput,
    user: Admin,
    business_line: AttendanceLine | None = None,
):
    await attendance.configure_holiday(user, day, payload.name, business_line)
    return Response(status_code=204)


@router.delete("/holidays/{day}", status_code=204)
async def delete_holiday(day: date, user: Admin, business_line: AttendanceLine | None = None):
    await attendance.configure_holiday(user, day, None, business_line)
    return Response(status_code=204)


@router.get("/employment/reviewers", response_model=list[AttendanceRosterMember])
async def get_employment_reviewers(_: Admin, business_line: AttendanceLine):
    return await attendance_employment.reviewers(business_line)


@router.get("/employment/{staff_id}", response_model=AttendanceEmploymentRead | None)
async def get_employment(staff_id: UUID, _: Admin, db: DB):
    return await db.get(AttendanceEmployment, staff_id)


@router.put("/employment/{staff_id}", response_model=AttendanceEmploymentRead)
async def put_employment(staff_id: UUID, payload: AttendanceEmploymentInput, user: Admin):
    return await attendance_employment.save(user, staff_id, payload)


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
        "system_check_out_ist",
        "leave_sessions",
        "lop_days",
        "regularizations",
    ]
    rows = [
        dict(
            zip(
                header,
                [
                    members[row.staff_profile_id].staff_code,
                    members[row.staff_profile_id].name,
                    "Officer"
                    if members[row.staff_profile_id].role == "employee"
                    else members[row.staff_profile_id].role.replace("_", " ").title(),
                    row.day,
                    row.status,
                    row.check_in.astimezone(attendance.IST).isoformat() if row.check_in else "",
                    row.check_out.astimezone(attendance.IST).isoformat() if row.check_out else "",
                    row.worked_minutes,
                    row.late,
                    row.leave_units,
                    row.system_check_out.astimezone(attendance.IST).isoformat()
                    if row.system_check_out
                    else "",
                    ", ".join(row.leave_sessions),
                    row.lop_units / 4 if row.lop_units is not None else "",
                    ", ".join(row.adjustments),
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
