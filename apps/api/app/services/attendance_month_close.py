"""Close complete IST months and preserve each revision's aggregate evidence."""

from datetime import date, datetime, time

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    AttendanceDay,
    AttendanceEmployment,
    AttendanceMonthRevision,
    AttendanceRequest,
    AttendanceRolloverState,
)
from app.models.profile import ProfileStatus, StaffProfile, StaffRole
from app.models.user import User, UserStatus
from app.schemas.attendance import AttendanceMonthAction, AttendanceMonthRead, AttendanceMonthTotal
from app.services import attendance as clock
from app.services.attendance_leave_policy import next_month


def bounds(month: date) -> tuple[date, date]:
    if month.day != 1 or not 2000 <= month.year <= 9998:
        raise clock.AttendanceInvalid("Choose the first day of an attendance month.")
    return month, next_month(month) - clock.DAY


async def _revisions(db: AsyncSession, month: date) -> list[AttendanceMonthRevision]:
    return list(
        await db.scalars(
            select(AttendanceMonthRevision)
            .where(AttendanceMonthRevision.month == month)
            .order_by(AttendanceMonthRevision.version.desc())
        )
    )


async def _totals(db: AsyncSession, start: date, end: date) -> list[AttendanceMonthTotal]:
    line = case(
        (AttendanceDay.business_line.in_(("loans", "real_estate")), AttendanceDay.business_line)
    )
    rows = (
        await db.execute(
            select(
                line.label("business_line"),
                func.count().label("recorded_days"),
                func.coalesce(func.sum(AttendanceDay.worked_minutes), 0).label("worked_minutes"),
                func.coalesce(func.sum(AttendanceDay.leave_units), 0).label("leave_units"),
                func.coalesce(func.sum(AttendanceDay.lop_units), 0).label("lop_units"),
                func.count().filter(AttendanceDay.late).label("late_days"),
                func.count().filter(AttendanceDay.status == "absent").label("absences"),
            )
            .where(AttendanceDay.day.between(start, end))
            .group_by(line)
            .order_by(line.nulls_last())
        )
    ).mappings()
    totals = {row["business_line"]: AttendanceMonthTotal.model_validate(row) for row in rows}
    first, last = start.isoformat(), end.isoformat()
    leave = await db.execute(
        select(
            AttendanceRequest.business_line,
            AttendanceRequest.approved_units,
            AttendanceRequest.monthly_charges,
        ).where(
            AttendanceRequest.status == "approved",
            AttendanceRequest.kind == "leave",
            AttendanceRequest.start_day <= end,
            AttendanceRequest.end_day >= start,
        )
    )
    for key, days, charges in leave:
        units = sum(
            count for day, count in charges.items() if first <= day <= last and day not in days
        )
        if units:
            key = key if key in ("loans", "real_estate") else None
            if key not in totals:
                totals[key] = AttendanceMonthTotal(
                    business_line=key,
                    recorded_days=0,
                    worked_minutes=0,
                    leave_units=0,
                    lop_units=0,
                    late_days=0,
                    absences=0,
                )
            totals[key].sandwich_units += units
    return [totals[key] for key in ("loans", "real_estate", None) if key in totals]


async def report(db: AsyncSession, month: date) -> AttendanceMonthRead:
    start, end = bounds(month)
    revisions = await _revisions(db, month)
    closed = bool(revisions and revisions[0].reopened_at is None)
    blocker = None
    if not closed:
        if end >= clock.work_date(clock.utc_now()):
            blocker = "Only completed months can be closed."
        elif await clock.policy_for(db, end) is None:
            blocker = "Attendance policy was not active for this month."
    return AttendanceMonthRead(
        month=month,
        can_close=not closed and blocker is None,
        close_blocker=blocker,
        totals=revisions[0].totals if closed else await _totals(db, start, end),
        revisions=revisions,
    )


async def _check_ready(db: AsyncSession, start: date, end: date) -> None:
    policy = await clock.require_policy(db, end)
    request = await db.scalar(
        select(AttendanceRequest.id)
        .where(
            AttendanceRequest.status == "pending",
            AttendanceRequest.start_day <= end,
            AttendanceRequest.end_day >= start,
        )
        .limit(1)
    )
    if request is not None:
        raise clock.AttendanceError(
            "Resolve pending attendance requests for this month before closing."
        )
    unfinished = await db.scalar(
        select(AttendanceDay.staff_profile_id)
        .where(
            AttendanceDay.day.between(start, end),
            AttendanceDay.status == "checked_in",
        )
        .limit(1)
    )
    if unfinished is not None:
        raise clock.AttendanceError("Wait for open shifts to finish processing before closing.")
    last_eligible = case(
        (AttendanceEmployment.end_day < end, AttendanceEmployment.end_day), else_=end
    )
    missing = await db.scalar(
        select(StaffProfile.id)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .outerjoin(AttendanceEmployment, AttendanceEmployment.staff_profile_id == StaffProfile.id)
        .outerjoin(
            AttendanceRolloverState, AttendanceRolloverState.staff_profile_id == StaffProfile.id
        )
        .where(
            StaffProfile.status == ProfileStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
            StaffProfile.role.in_(
                clock.STAFF_ROLES
                if policy.session_clock
                else (StaffRole.TELECALLER, StaffRole.EMPLOYEE)
            ),
            or_(
                AttendanceEmployment.start_day <= end,
                AttendanceEmployment.start_day.is_(None)
                & (
                    StaffProfile.created_at < datetime.combine(end + clock.DAY, time.min, clock.IST)
                ),
            ),
            or_(AttendanceEmployment.end_day.is_(None), AttendanceEmployment.end_day >= start),
            or_(
                AttendanceRolloverState.through_day.is_(None),
                AttendanceRolloverState.through_day < last_eligible,
            ),
        )
        .limit(1)
    )
    if missing is not None:
        raise clock.AttendanceError("Attendance rollover is still completing dates in this month.")


async def change(
    actor: CurrentUser, month: date, values: AttendanceMonthAction, *, reopening: bool
) -> AttendanceMonthRead:
    start, end = bounds(month)
    async with db_session.AsyncSessionLocal() as db:
        await clock.lock_actor(db, actor)
        await db.execute(select(func.pg_advisory_xact_lock(ATTENDANCE_POLICY_LOCK)))
        now = clock.utc_now()
        revisions = await _revisions(db, month)
        current = revisions[0] if revisions else None
        version = current.version if current else 0
        if values.expected_version != version:
            raise clock.AttendanceError("The monthly report changed. Reload it and try again.")
        if reopening:
            if current is None or current.reopened_at is not None:
                raise clock.AttendanceError("This attendance month is already open.")
            current.reopened_at = now
        else:
            if end >= clock.work_date(now):
                raise clock.AttendanceInvalid("Only completed months can be closed.")
            if current and current.reopened_at is None:
                raise clock.AttendanceError("This attendance month is already closed.")
            await _check_ready(db, start, end)
            totals = await _totals(db, start, end)
            version += 1
            db.add(
                AttendanceMonthRevision(
                    month=month,
                    version=version,
                    closed_at=now,
                    totals=[total.model_dump(mode="json") for total in totals],
                )
            )
        await clock.audit(
            db,
            actor,
            "reopen_month" if reopening else "close_month",
            detail={
                "month": month.isoformat(),
                "version": version,
                "note": values.note,
            },
        )
        await db.flush()
        result = await report(db, month)
        await db.commit()
        return result
