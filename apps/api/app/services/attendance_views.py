"""Attendance queries use the caller's request session and RLS."""

from calendar import monthrange
from datetime import date
from uuid import UUID

from sqlalchemy import String, Uuid, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceDay,
    AttendanceEmployment,
    AttendanceHoliday,
    AttendanceLineHoliday,
    AttendanceRequest,
)
from app.schemas.attendance import (
    AttendanceDayRead,
    AttendanceInboxRead,
    AttendanceLeaveCode,
    AttendanceRosterRead,
    MyAttendanceRead,
)
from app.services import attendance as clock
from app.services.attendance_requests import balances

_LEAVE_CODES: dict[str, AttendanceLeaveCode] = {
    "casual": "CL",
    "casual_leave": "CL",
    "cl": "CL",
    "sick": "SL",
    "sick_leave": "SL",
    "sl": "SL",
}


async def _day_reads(
    db: AsyncSession, days: list[AttendanceDay]
) -> dict[tuple[UUID, date], AttendanceDayRead]:
    reads = {}
    owners = {}
    request_ids = set()
    for row in days:
        key = (row.staff_profile_id, row.day)
        reads[key] = AttendanceDayRead.model_validate(row)
        ids = {UUID(owner) for owner in row.leave_sessions.values()}
        if row.leave_request_id is not None:
            ids.add(row.leave_request_id)
        if ids:
            request_ids.update(ids)
            owners[key] = ids
    if request_ids:
        approved = await db.execute(
            select(
                AttendanceRequest.id,
                AttendanceRequest.staff_profile_id,
                AttendanceRequest.leave_type,
            ).where(
                AttendanceRequest.id.in_(request_ids),
                AttendanceRequest.kind == "leave",
                AttendanceRequest.status == "approved",
                AttendanceRequest.leave_type.in_(_LEAVE_CODES),
            )
        )
        codes = {
            (staff_id, request_id): _LEAVE_CODES[kind] for request_id, staff_id, kind in approved
        }
        for key, ids in owners.items():
            staff_id, _ = key
            reads[key].leave_codes = sorted(
                {
                    codes[staff_id, request_id]
                    for request_id in ids
                    if (staff_id, request_id) in codes
                }
            )
    return reads


def validate_period(start: date, end: date) -> None:
    if not 0 <= (end - start).days <= 30:
        raise clock.AttendanceInvalid("Choose a date range of one to 31 days.")


async def holidays(db: AsyncSession, start: date, end: date, business_line: str | None = None):
    if business_line is not None:
        return list(
            await db.scalars(
                select(AttendanceLineHoliday)
                .where(
                    AttendanceLineHoliday.business_line == business_line,
                    AttendanceLineHoliday.day.between(start, end),
                )
                .order_by(AttendanceLineHoliday.day)
            )
        )
    return list(
        await db.scalars(
            select(AttendanceHoliday)
            .where(AttendanceHoliday.day.between(start, end))
            .order_by(AttendanceHoliday.day)
        )
    )


async def personal(
    db: AsyncSession,
    staff_id: UUID,
    role: str,
    year: int | None,
    month: int | None,
    business_line: str | None,
):
    now = clock.utc_now()
    today = clock.work_date(now)
    year, month = year or today.year, month or today.month
    start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    policy = await clock.policy_for(db, today)
    employment = await db.get(AttendanceEmployment, staff_id)
    line = (
        employment.business_line
        if employment
        else (business_line if policy and policy.session_clock else None)
    )
    calendar = {row.day: row for row in await holidays(db, start, end)}
    if line is not None:
        calendar.update({row.day: row for row in await holidays(db, start, end, line)})
    active = await clock.open_day(db, staff_id)
    if active is not None and now >= clock.midnight_after(active.day):
        active = None
    if active is None:
        active = await db.get(AttendanceDay, (staff_id, today))
    days = list(
        await db.scalars(
            select(AttendanceDay)
            .where(
                AttendanceDay.staff_profile_id == staff_id, AttendanceDay.day.between(start, end)
            )
            .order_by(AttendanceDay.day)
        )
    )
    reads = await _day_reads(db, [*days, active] if active is not None else days)
    return MyAttendanceRead(
        policy=policy if clock.allows_personal_attendance(role, policy) else None,
        server_time=now,
        work_day=active.day if active else today,
        today=reads[staff_id, active.day] if active is not None else None,
        days=[reads[staff_id, row.day] for row in days],
        holidays=[calendar[day] for day in sorted(calendar)],
        employment_start=employment.start_day if employment else None,
        employment_end=employment.end_day if employment else None,
        requests=list(
            await db.scalars(
                select(AttendanceRequest)
                .where(
                    AttendanceRequest.staff_profile_id == staff_id,
                    AttendanceRequest.start_day <= end,
                    AttendanceRequest.end_day >= start,
                )
                .order_by(AttendanceRequest.created_at.desc())
                .limit(200)
            )
        ),
        balance_year=year,
        balances=await balances(db, staff_id, min(end, today) if year == today.year else end)
        if clock.allows_personal_attendance(role, policy)
        else [],
    )


_ROSTER = (
    text("SELECT * FROM attendance_reporting_roster(:team_id)")
    .columns(
        staff_profile_id=Uuid(),
        name=String(),
        staff_code=String(),
        role=String(),
    )
    .subquery()
)


async def roster(
    db: AsyncSession,
    *,
    start: date,
    end: date,
    team_id: UUID | None,
    staff_id: UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> AttendanceRosterRead:
    validate_period(start, end)
    filters = [] if staff_id is None else [_ROSTER.c.staff_profile_id == staff_id]
    if status is not None:
        filters.append(
            _ROSTER.c.staff_profile_id.in_(
                select(AttendanceDay.staff_profile_id).where(
                    AttendanceDay.day.between(start, end), AttendanceDay.status == status
                )
            )
        )
    parameters = {"team_id": team_id}
    count = await db.scalar(select(func.count()).select_from(_ROSTER).where(*filters), parameters)
    members = (
        (
            await db.execute(
                select(_ROSTER)
                .where(*filters)
                .order_by(_ROSTER.c.name, _ROSTER.c.staff_profile_id)
                .limit(limit)
                .offset(offset),
                parameters,
            )
        )
        .mappings()
        .all()
    )
    days = list(
        await db.scalars(
            select(AttendanceDay)
            .where(
                AttendanceDay.staff_profile_id.in_(
                    [member["staff_profile_id"] for member in members]
                ),
                AttendanceDay.day.between(start, end),
            )
            .order_by(AttendanceDay.day, AttendanceDay.staff_profile_id)
        )
    )
    return AttendanceRosterRead(
        configured=(await clock.policy_for(db, clock.work_date(clock.utc_now()))) is not None,
        members=members,
        days=list((await _day_reads(db, days)).values()),
        total=count or 0,
    )


async def inbox(
    db: AsyncSession,
    *,
    status: str | None,
    team_id: UUID | None,
    staff_id: UUID | None,
    start: date | None,
    end: date | None,
    limit: int,
    offset: int,
) -> AttendanceInboxRead:
    filters = [AttendanceRequest.staff_profile_id.in_(select(_ROSTER.c.staff_profile_id))]
    if status is not None:
        filters.append(AttendanceRequest.status == status)
    if staff_id is not None:
        filters.append(AttendanceRequest.staff_profile_id == staff_id)
    if start is not None:
        filters.append(AttendanceRequest.end_day >= start)
    if end is not None:
        filters.append(AttendanceRequest.start_day <= end)
    parameters = {"team_id": team_id}
    count = await db.scalar(
        select(func.count()).select_from(AttendanceRequest).where(*filters), parameters
    )
    rows = await db.scalars(
        select(AttendanceRequest)
        .where(*filters)
        .order_by(AttendanceRequest.created_at.desc(), AttendanceRequest.id.desc())
        .limit(limit)
        .offset(offset),
        parameters,
    )
    return AttendanceInboxRead(requests=list(rows), total=count or 0)
