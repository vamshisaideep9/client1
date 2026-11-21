"""Attendance queries use the caller's request session and RLS."""

from calendar import monthrange
from datetime import date
from uuid import UUID

from sqlalchemy import String, Uuid, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceDay,
    AttendanceHoliday,
    AttendancePolicy,
    AttendanceRequest,
)
from app.schemas.attendance import AttendanceInboxRead, AttendanceRosterRead, MyAttendanceRead
from app.services import attendance as clock
from app.services.attendance_requests import balances


def validate_period(start: date, end: date) -> None:
    if not 0 <= (end - start).days <= 30:
        raise clock.AttendanceInvalid("Choose a date range of one to 31 days.")


async def holidays(db: AsyncSession, start: date, end: date) -> list[AttendanceHoliday]:
    return list(
        await db.scalars(
            select(AttendanceHoliday)
            .where(AttendanceHoliday.day.between(start, end))
            .order_by(AttendanceHoliday.day)
        )
    )


async def personal(db: AsyncSession, staff_id: UUID, year: int | None, month: int | None):
    now = clock.utc_now()
    today = clock.work_date(now)
    year, month = year or today.year, month or today.month
    start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    policy = await clock.policy_for(db, today)
    active = await clock.open_day(db, staff_id)
    if active is not None:
        day_policy = await db.get(AttendancePolicy, active.policy_version)
        if now >= clock.shift_cutoff(active.day, day_policy):
            active = None
    if active is None:
        active = await db.get(AttendanceDay, (staff_id, today))
    return MyAttendanceRead(
        policy=policy,
        server_time=now,
        work_day=active.day if active else today,
        today=active,
        days=list(
            await db.scalars(
                select(AttendanceDay)
                .where(
                    AttendanceDay.staff_profile_id == staff_id,
                    AttendanceDay.day.between(start, end),
                )
                .order_by(AttendanceDay.day)
            )
        ),
        holidays=await holidays(db, start, end),
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
        balances=await balances(db, staff_id, min(end, today) if year == today.year else end),
    )


_ROSTER = (
    text("SELECT * FROM attendance_roster(:team_id)")
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
        days=days,
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
