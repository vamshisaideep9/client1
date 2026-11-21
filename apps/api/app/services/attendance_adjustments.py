"""Apply reviewed attendance exceptions under the caller's staff transaction."""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceDay, AttendancePolicy, AttendanceRequest
from app.services import attendance as clock


async def comp_off_date(db: AsyncSession, sunday: date, business_line: str | None = None) -> date:
    if sunday.weekday() != 6:
        raise clock.AttendanceInvalid("Choose a Sunday worked for compensation off.")
    for offset in range(1, 31):
        day = sunday + timedelta(days=offset)
        policy = await clock.require_policy(db, day)
        if await clock.day_without_clock(db, day, policy, business_line) == "absent":
            return day
    raise clock.AttendanceError("No scheduled working day is available after this Sunday.")


def _add(row: AttendanceDay, category: str, request: AttendanceRequest) -> None:
    if category in row.adjustments:
        raise clock.AttendanceError("An approved request already covers this exception.")
    row.adjustments = {**row.adjustments, category: str(request.id)}


def _remove(row: AttendanceDay, category: str, request: AttendanceRequest) -> None:
    if row.adjustments.get(category) != str(request.id):
        raise clock.AttendanceError("This request no longer owns the exception.")
    row.adjustments = {key: value for key, value in row.adjustments.items() if key != category}


def _refresh(row: AttendanceDay, policy: AttendancePolicy) -> None:
    if row.check_in is not None:
        if row.check_out is not None:
            clock.apply_clock_result(row, policy)
        return
    if "on_duty" in row.adjustments:
        row.status = "present"
        row.uncovered_units = 0
    elif row.leave_units:
        row.status = "on_leave"
        row.uncovered_units = 2 * (2 - row.leave_units)
    else:
        row.status = row.calendar_status or "absent"
        row.uncovered_units = 4 if row.status == "absent" else 0


async def apply(db: AsyncSession, request: AttendanceRequest) -> None:
    day = request.start_day
    key = (request.staff_profile_id, day)
    row = await db.get(AttendanceDay, key)
    policy = (
        await db.get(AttendancePolicy, row.policy_version)
        if row
        else (await clock.require_policy(db, day))
    )
    category = request.adjustment_type
    if category == "on_duty" and row is None:
        calendar = await clock.day_without_clock(db, day, policy, request.business_line)
        row = clock.new_day(
            *key,
            policy,
            calendar,
            "correction",
            calendar_status=calendar,
            business_line=request.business_line,
        )
        db.add(row)
    if row is None or not policy.session_clock:
        raise clock.AttendanceError("This exception requires a session-clock attendance day.")
    if row.business_line not in (None, request.business_line):
        raise clock.AttendanceError("This date is recorded in another business line.")
    if row.business_line is None:
        row.business_line = request.business_line
    if category == "late_waiver" and not row.late:
        raise clock.AttendanceError("This day has no late mark to excuse.")
    if category == "early_exit":
        if not row.early_exit or not row.morning_covered or row.leave_units:
            raise clock.AttendanceError("This day does not qualify for an early-exit exception.")
        used = await db.scalar(
            select(func.count())
            .select_from(AttendanceDay)
            .where(
                AttendanceDay.staff_profile_id == row.staff_profile_id,
                AttendanceDay.day >= day.replace(day=1),
                AttendanceDay.day < (day.replace(day=28) + timedelta(days=4)).replace(day=1),
                AttendanceDay.adjustments.has_key("early_exit"),
            )
        )
        if used:
            raise clock.AttendanceError("An early-exit exception was already approved this month.")
    if category == "on_duty" and (row.calendar_status != "absent" or row.leave_units):
        raise clock.AttendanceError(
            "On-duty credit requires a scheduled day without approved leave."
        )
    if category in ("holiday_work", "comp_off"):
        if row.calendar_status not in ("holiday", "week_off") or not row.worked_minutes:
            raise clock.AttendanceError("Holiday work requires completed attendance on a day off.")
        if category == "comp_off":
            if not (row.morning_covered and row.afternoon_covered and row.worked_minutes == 480):
                raise clock.AttendanceError("Compensation off requires a complete Sunday shift.")
            await _apply_comp_off(db, request)
        category = "holiday_work"
    _add(row, category, request)
    _refresh(row, policy)
    await clock.recalculate_late_penalties(db, request.staff_profile_id, day)


async def _apply_comp_off(db: AsyncSession, request: AttendanceRequest) -> None:
    target = await comp_off_date(db, request.start_day, request.business_line)
    if target != request.end_day:
        raise clock.AttendanceError("The next working day changed. Submit a new request.")
    key = (request.staff_profile_id, target)
    row = await db.get(AttendanceDay, key)
    if row is None:
        policy = await clock.require_policy(db, target)
        row = clock.new_day(
            *key,
            policy,
            "on_leave",
            "leave",
            calendar_status="absent",
            business_line=request.business_line,
        )
        db.add(row)
    if (
        row.check_in
        or row.leave_units
        or row.adjustments
        or row.business_line not in (None, request.business_line)
    ):
        raise clock.AttendanceError("The compensation day has conflicting work or leave.")
    _add(row, "comp_off", request)
    row.business_line = request.business_line
    row.leave_units, row.leave_request_id = 2, request.id
    row.status, row.source = "on_leave", "leave"
    row.uncovered_units = row.lop_units = 0


async def undo(db: AsyncSession, request: AttendanceRequest, now: datetime) -> None:
    row = await db.get(AttendanceDay, (request.staff_profile_id, request.start_day))
    if row is None:
        raise clock.AttendanceError("The adjusted day is unavailable.")
    category = request.adjustment_type
    if category == "comp_off":
        target_day = request.end_day
        target = await db.get(AttendanceDay, (request.staff_profile_id, target_day))
        if target is None or target.leave_request_id != request.id:
            raise clock.AttendanceError("The compensation day is unavailable.")
        _remove(target, "comp_off", request)
        if target_day >= clock.work_date(now) and target.check_in is None:
            await db.delete(target)
        else:
            target.leave_units, target.leave_request_id = 0, None
            target.source = "rollover"
            _refresh(target, await db.get(AttendancePolicy, target.policy_version))
            await clock.recalculate_late_penalties(db, request.staff_profile_id, target_day)
        category = "holiday_work"
    _remove(row, category, request)
    if category == "on_duty" and row.day >= clock.work_date(now) and row.check_in is None:
        await db.delete(row)
        return
    _refresh(row, await db.get(AttendancePolicy, row.policy_version))
    await clock.recalculate_late_penalties(db, request.staff_profile_id, request.start_day)
