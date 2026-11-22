"""Bounded, restartable completion of attendance days in the scheduler."""

from datetime import datetime, time

from sqlalchemy import func, or_, select

import app.db.session as db_session
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    ATTENDANCE_ROLLOVER_LOCK,
    AttendanceDay,
    AttendanceEmployment,
    AttendancePolicy,
    AttendanceRolloverState,
)
from app.models.profile import ProfileStatus, StaffProfile
from app.models.user import User, UserStatus
from app.services import attendance as clock


async def run_attendance_rollover(now: datetime | None = None) -> int:
    now = now or clock.utc_now()
    today = clock.work_date(now)
    async with db_session.AsyncSessionLocal() as guard:
        if not await guard.scalar(select(func.pg_try_advisory_xact_lock(ATTENDANCE_ROLLOVER_LOCK))):
            return 0
        first = await guard.scalar(select(func.min(AttendancePolicy.effective_from)))
        if first is None or first >= today:
            return 0
        staff_ids = list(
            await guard.scalars(
                select(StaffProfile.id)
                .join(User, User.id == StaffProfile.auth_user_uuid)
                .outerjoin(
                    AttendanceEmployment, AttendanceEmployment.staff_profile_id == StaffProfile.id
                )
                .outerjoin(
                    AttendanceRolloverState,
                    AttendanceRolloverState.staff_profile_id == StaffProfile.id,
                )
                .where(
                    StaffProfile.role.in_(clock.STAFF_ROLES),
                    StaffProfile.status == ProfileStatus.ACTIVE,
                    User.status == UserStatus.ACTIVE,
                    StaffProfile.created_at < datetime.combine(today, time.min, clock.IST),
                    or_(
                        AttendanceEmployment.start_day.is_(None),
                        AttendanceEmployment.start_day < today,
                    ),
                    or_(
                        AttendanceEmployment.end_day.is_(None),
                        AttendanceRolloverState.through_day.is_(None),
                        AttendanceRolloverState.through_day < AttendanceEmployment.end_day,
                    ),
                    or_(
                        AttendanceRolloverState.through_day.is_(None),
                        AttendanceRolloverState.through_day < today - clock.DAY,
                    ),
                )
                .order_by(AttendanceRolloverState.through_day.asc().nulls_first(), StaffProfile.id)
                .limit(100)
            )
        )
        updated = 0
        for staff_id in staff_ids:
            async with db_session.AsyncSessionLocal() as db:
                try:
                    profile = await clock.lock_staff(db, staff_id)
                except clock.AttendanceNotFound:
                    continue
                await db.execute(select(func.pg_advisory_xact_lock_shared(ATTENDANCE_POLICY_LOCK)))
                cursor = await db.get(AttendanceRolloverState, staff_id)
                employment = await db.get(AttendanceEmployment, staff_id)
                start = employment.start_day if employment else clock.work_date(profile.created_at)
                end = (
                    min(today - clock.DAY, employment.end_day)
                    if employment and employment.end_day
                    else today - clock.DAY
                )
                day = max(first, start)
                if cursor is not None:
                    day = max(day, cursor.through_day + clock.DAY)
                through = None
                recalculate_months = set()
                frozen_months = await clock.closed_months(db, day, end)
                for _ in range(14):
                    if day > end:
                        break
                    if day.replace(day=1) in frozen_months:
                        through = day
                        day += clock.DAY
                        continue
                    row = await db.get(AttendanceDay, (staff_id, day))
                    policy = (
                        await db.get(AttendancePolicy, row.policy_version)
                        if row is not None
                        else await clock.require_policy(db, day)
                    )
                    if (
                        row is None
                        and clock.allows_personal_attendance(profile.role, policy)
                        and (employment or profile.created_at <= clock.shift_start(day, policy))
                    ):
                        line = (
                            employment.business_line
                            if employment
                            else profile.business_line
                            if policy.session_clock
                            and profile.business_line in ("loans", "real_estate")
                            else None
                        )
                        status = await clock.day_without_clock(db, day, policy, line)
                        row = clock.new_day(
                            staff_id,
                            day,
                            policy,
                            status,
                            "rollover",
                            calendar_status=status,
                            business_line=line,
                        )
                        if policy.session_clock:
                            row.uncovered_units = row.lop_units = 4 if status == "absent" else 0
                        db.add(row)
                        updated += 1
                    elif row is not None and row.status == "checked_in":
                        await clock.close_expired_day(db, row, policy)
                        if policy.session_clock:
                            recalculate_months.add(day.replace(day=1))
                        updated += 1
                    elif (
                        row is not None
                        and policy.session_clock
                        and row.status == "on_leave"
                        and row.uncovered_units is None
                    ):
                        row.uncovered_units = row.lop_units = (2 - row.leave_units) * 2
                        updated += 1
                    through = day
                    day += clock.DAY
                if through is not None:
                    for month in sorted(recalculate_months):
                        await clock.recalculate_late_penalties(db, staff_id, month)
                    if cursor is None:
                        db.add(
                            AttendanceRolloverState(staff_profile_id=staff_id, through_day=through)
                        )
                    else:
                        cursor.through_day = through
                    await db.commit()
        return updated
