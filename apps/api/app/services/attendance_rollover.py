"""Bounded, restartable completion of attendance days in the scheduler."""

from datetime import datetime, time

from sqlalchemy import func, or_, select

import app.db.session as db_session
from app.models.attendance import (
    ATTENDANCE_ROLLOVER_LOCK,
    AttendanceDay,
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
                    AttendanceRolloverState,
                    AttendanceRolloverState.staff_profile_id == StaffProfile.id,
                )
                .where(
                    StaffProfile.role.in_(clock.STAFF_ROLES),
                    StaffProfile.status == ProfileStatus.ACTIVE,
                    User.status == UserStatus.ACTIVE,
                    StaffProfile.created_at < datetime.combine(today, time.min, clock.IST),
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
                cursor = await db.get(AttendanceRolloverState, staff_id)
                day = max(first, clock.work_date(profile.created_at))
                if cursor is not None:
                    day = max(day, cursor.through_day + clock.DAY)
                through = None
                for _ in range(14):
                    if day >= today:
                        break
                    row = await db.get(AttendanceDay, (staff_id, day))
                    policy = (
                        await db.get(AttendancePolicy, row.policy_version)
                        if row is not None
                        else await clock.require_policy(db, day)
                    )
                    if now < clock.shift_cutoff(day, policy):
                        break
                    if row is None and profile.created_at <= clock.shift_start(day, policy):
                        status = await clock.day_without_clock(db, day, policy)
                        db.add(clock.new_day(staff_id, day, policy, status, "rollover"))
                        updated += 1
                    elif row is not None and row.status == "checked_in":
                        row.status = "missing_checkout"
                        updated += 1
                    through = day
                    day += clock.DAY
                if through is not None:
                    if cursor is None:
                        db.add(
                            AttendanceRolloverState(staff_profile_id=staff_id, through_day=through)
                        )
                    else:
                        cursor.through_day = through
                    await db.commit()
        return updated
