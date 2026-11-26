"""Attendance queries use the caller's request session and RLS."""

from calendar import isleap, monthrange
from datetime import date
from uuid import UUID

from sqlalchemy import ARRAY, String, Uuid, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceDay,
    AttendanceEmployment,
    AttendanceHoliday,
    AttendanceLineHoliday,
    AttendanceRecurringHoliday,
    AttendanceRequest,
)
from app.schemas.attendance import (
    AttendanceDayRead,
    AttendanceHolidayRead,
    AttendanceInboxRead,
    AttendanceLeaveBadge,
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


_KNOWN_BADGES: dict[AttendanceLeaveCode, str] = {"CL": "Casual leave", "SL": "Sick leave"}


def leave_badge(leave_type: str) -> AttendanceLeaveBadge:
    """CL and SL as before; any other leave type gets a code of at most three
    letters (one word: its initial and "L", as in EL; several words: their
    initials, as in WFH) and its full label."""
    known = _LEAVE_CODES.get(leave_type)
    if known is not None:
        return AttendanceLeaveBadge(code=known, label=_KNOWN_BADGES[known])
    words = [word for word in leave_type.split("_") if word]
    meaningful = [word for word in words if word != "leave"] or words or ["leave"]
    if len(meaningful) == 1:
        code = f"{meaningful[0][0]}L"
        label = f"{meaningful[0].capitalize()} leave"
    else:
        code = "".join(word[0] for word in meaningful[:3])
        label = " ".join(meaningful).capitalize()
    return AttendanceLeaveBadge(code=code.upper()[:3], label=label)


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
        approved = (
            await db.execute(
                select(
                    AttendanceRequest.id,
                    AttendanceRequest.staff_profile_id,
                    AttendanceRequest.leave_type,
                ).where(
                    AttendanceRequest.id.in_(request_ids),
                    AttendanceRequest.kind == "leave",
                    AttendanceRequest.status == "approved",
                    AttendanceRequest.leave_type.is_not(None),
                )
            )
        ).all()
        kinds = {(staff_id, request_id): kind for request_id, staff_id, kind in approved}
        for key, ids in owners.items():
            staff_id, _ = key
            types = {
                kinds[staff_id, request_id] for request_id in ids if (staff_id, request_id) in kinds
            }
            reads[key].leave_codes = sorted(
                {_LEAVE_CODES[kind] for kind in types if kind in _LEAVE_CODES}
            )
            badges = {badge.code: badge for badge in map(leave_badge, sorted(types))}
            reads[key].leave_badges = [badges[code] for code in sorted(badges)]
    return reads


def validate_period(start: date, end: date) -> None:
    if not 0 <= (end - start).days <= 30:
        raise clock.AttendanceInvalid("Choose a date range of one to 31 days.")


def occurrences(series: AttendanceRecurringHoliday, start: date, end: date) -> list[date]:
    """Dates of a yearly series inside ``[start, end]`` and its own period.
    29 February only occurs in leap years."""
    first = max(start, series.starts_on)
    last = min(end, series.ends_on) if series.ends_on is not None else end
    dates = []
    for year in range(first.year, last.year + 1):
        if series.month == 2 and series.day == 29 and not isleap(year):
            continue
        day = date(year, series.month, series.day)
        if first <= day <= last:
            dates.append(day)
    return dates


async def recurring_holidays(
    db: AsyncSession, start: date, end: date, business_line: str | None
) -> list[AttendanceHolidayRead]:
    """Occurrences of yearly series for one line (``business_line``) or for
    every line (None), in date order."""
    line = (
        AttendanceRecurringHoliday.business_line.is_(None)
        if business_line is None
        else AttendanceRecurringHoliday.business_line == business_line
    )
    rows = await db.scalars(
        select(AttendanceRecurringHoliday).where(
            line,
            AttendanceRecurringHoliday.starts_on <= end,
            or_(
                AttendanceRecurringHoliday.ends_on.is_(None),
                AttendanceRecurringHoliday.ends_on >= start,
            ),
        )
    )
    return sorted(
        (
            AttendanceHolidayRead(
                day=day,
                name=series.name,
                business_line=series.business_line,
                recurring_id=series.id,
                repeats_yearly=True,
                starts_on=series.starts_on,
                ends_on=series.ends_on,
            )
            for series in rows
            for day in occurrences(series, start, end)
        ),
        key=lambda holiday: holiday.day,
    )


async def holidays(
    db: AsyncSession, start: date, end: date, business_line: str | None = None
) -> list[AttendanceHolidayRead]:
    """One-off holidays and yearly occurrences in ``[start, end]`` for one
    line, or for every line when ``business_line`` is None."""
    if business_line is not None:
        one_off = await db.scalars(
            select(AttendanceLineHoliday)
            .where(
                AttendanceLineHoliday.business_line == business_line,
                AttendanceLineHoliday.day.between(start, end),
            )
            .order_by(AttendanceLineHoliday.day)
        )
    else:
        one_off = await db.scalars(
            select(AttendanceHoliday)
            .where(AttendanceHoliday.day.between(start, end))
            .order_by(AttendanceHoliday.day)
        )
    reads = [AttendanceHolidayRead.model_validate(row) for row in one_off]
    reads += await recurring_holidays(db, start, end, business_line)
    return sorted(reads, key=lambda holiday: (holiday.day, holiday.recurring_id is not None))


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
    # A one-off holiday wins over a yearly one on the same date.
    calendar = {row.day: row for row in reversed(await holidays(db, start, end))}
    if line is not None:
        calendar.update({row.day: row for row in reversed(await holidays(db, start, end, line))})
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


# The caller's reachable members (attendance_reporting_roster) with their
# department, product specialty and Sub Admin groups for the filters.
_ROSTER = (
    text(
        "SELECT staff_profile_id, name, staff_code, role, department, product_id, "
        "sub_admin_groups FROM attendance_roster_details(:team_id)"
    )
    .columns(
        staff_profile_id=Uuid(),
        name=String(),
        staff_code=String(),
        role=String(),
        department=String(),
        product_id=Uuid(),
        sub_admin_groups=ARRAY(String()),
    )
    .subquery()
)


def _roster_filters(
    *,
    start: date,
    end: date,
    department: str | None,
    product_id: UUID | None,
    role: str | None,
    sub_admin_group: str | None,
    leave_type: str | None,
) -> list:
    """Department matches the member's line or a dual-line member; leave type
    matches members with approved leave of that type in the range."""
    filters = []
    if department is not None:
        filters.append(_ROSTER.c.department.in_((department, "both")))
    if product_id is not None:
        filters.append(_ROSTER.c.product_id == product_id)
    if role is not None:
        filters.append(_ROSTER.c.role == role)
    if sub_admin_group is not None:
        filters.append(_ROSTER.c.sub_admin_groups.any(sub_admin_group))
    if leave_type is not None:
        filters.append(
            _ROSTER.c.staff_profile_id.in_(
                select(AttendanceRequest.staff_profile_id).where(
                    AttendanceRequest.kind == "leave",
                    AttendanceRequest.status == "approved",
                    AttendanceRequest.leave_type == leave_type,
                    AttendanceRequest.start_day <= end,
                    AttendanceRequest.end_day >= start,
                )
            )
        )
    return filters


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
    department: str | None = None,
    product_id: UUID | None = None,
    role: str | None = None,
    sub_admin_group: str | None = None,
    leave_type: str | None = None,
) -> AttendanceRosterRead:
    validate_period(start, end)
    filters = [] if staff_id is None else [_ROSTER.c.staff_profile_id == staff_id]
    filters += _roster_filters(
        start=start,
        end=end,
        department=department,
        product_id=product_id,
        role=role,
        sub_admin_group=sub_admin_group,
        leave_type=leave_type,
    )
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
