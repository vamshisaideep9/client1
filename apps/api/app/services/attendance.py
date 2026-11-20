"""Attendance clock and effective-dated policy. Every clock write locks its staff row."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    AttendanceDay,
    AttendanceHoliday,
    AttendancePolicy,
)
from app.models.audit_log import AuditAction
from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User, UserStatus
from app.schemas.attendance import AttendancePolicyInput, AttendancePolicyState
from app.services.audit_log import record

IST = ZoneInfo("Asia/Kolkata")
STAFF_ROLES = (StaffRole.TELECALLER, StaffRole.EMPLOYEE)
DAY = timedelta(days=1)


class AttendanceError(Exception):
    status = 409


class AttendanceForbidden(AttendanceError):
    status = 403


class AttendanceNotFound(AttendanceError):
    status = 404


class AttendanceInvalid(AttendanceError):
    status = 422


def utc_now() -> datetime:
    return datetime.now(UTC)


def work_date(now: datetime) -> date:
    return now.astimezone(IST).date()


def shift_start(day: date, policy: AttendancePolicy) -> datetime:
    return datetime.combine(day, time.min, IST) + timedelta(minutes=policy.shift_start_minute)


def shift_cutoff(day: date, policy: AttendancePolicy) -> datetime:
    # Leave room for a late check-out through the next daily shift start.
    return shift_start(day, policy) + DAY


async def policy_for(db: AsyncSession, day: date) -> AttendancePolicy | None:
    return await db.scalar(
        select(AttendancePolicy)
        .where(AttendancePolicy.effective_from <= day)
        .order_by(AttendancePolicy.effective_from.desc(), AttendancePolicy.version.desc())
        .limit(1)
    )


async def require_policy(db: AsyncSession, day: date) -> AttendancePolicy:
    policy = await policy_for(db, day)
    if policy is None:
        raise AttendanceError("An Admin must configure attendance before it opens.")
    return policy


async def policy_state(db: AsyncSession) -> AttendancePolicyState:
    today = work_date(utc_now())
    return AttendancePolicyState(
        active=await policy_for(db, today),
        scheduled=await db.scalar(
            select(AttendancePolicy)
            .where(AttendancePolicy.effective_from > today)
            .order_by(AttendancePolicy.effective_from.desc(), AttendancePolicy.version.desc())
            .limit(1)
        ),
    )


async def lock_actor(db: AsyncSession, actor: CurrentUser) -> StaffProfile:
    """Recheck the identity, role and status before any owner-session write."""
    profile = await db.scalar(
        select(StaffProfile)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            StaffProfile.id == actor.staff_profile_uuid,
            StaffProfile.auth_user_uuid == actor.id,
            StaffProfile.role == actor.role,
            StaffProfile.status == ProfileStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
        )
        .with_for_update(of=(StaffProfile, User))
    )
    if profile is None:
        raise AttendanceForbidden("Your staff assignment is no longer active.")
    if (
        profile.role in (StaffRole.ADMIN, StaffRole.SUB_ADMIN)
        and profile.scope != ProfileScope.PLATFORM
    ):
        raise AttendanceForbidden("This action requires a platform staff account.")
    return profile


async def lock_staff(db: AsyncSession, profile_id: UUID) -> StaffProfile:
    profile = await db.scalar(
        select(StaffProfile)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            StaffProfile.id == profile_id,
            StaffProfile.role.in_(STAFF_ROLES),
            StaffProfile.status == ProfileStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
        )
        .with_for_update(of=(StaffProfile, User))
    )
    if profile is None:
        raise AttendanceNotFound("Staff member not found.")
    return profile


async def managers_for(
    db: AsyncSession, target: StaffProfile, manager_id: UUID | None = None
) -> set[UUID]:
    """Lock matching memberships and teams through the decision commit."""
    criteria = [
        StaffTeamMember.staff_profile_uuid == target.id,
        StaffTeam.member_role == target.role.value,
        StaffTeam.archived_at.is_(None),
    ]
    if manager_id is not None:
        criteria.append(StaffTeam.manager_staff_profile_uuid == manager_id)
    manager_rows = (
        await db.execute(
            select(StaffTeam.manager_staff_profile_uuid, StaffProfile.auth_user_uuid)
            .join(StaffTeamMember, StaffTeamMember.team_uuid == StaffTeam.id)
            .join(StaffProfile, StaffProfile.id == StaffTeam.manager_staff_profile_uuid)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(
                *criteria,
                StaffProfile.role == StaffRole.SUB_ADMIN,
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update(read=True, of=(StaffTeam, StaffTeamMember))
        )
    ).all()
    return {row.auth_user_uuid for row in manager_rows}


async def audit(
    db: AsyncSession,
    actor: CurrentUser,
    action: str,
    *,
    entity_id: UUID | None = None,
    detail: dict | None = None,
) -> None:
    await record(
        db,
        action=AuditAction.ATTENDANCE_UPDATED,
        entity_type="staff_attendance",
        entity_uuid=entity_id,
        actor_uuid=actor.id,
        actor_role=actor.role,
        detail={"operation": action, **(detail or {})},
    )


async def configure_policy(
    actor: CurrentUser, values: AttendancePolicyInput
) -> AttendancePolicyState:
    async with db_session.AsyncSessionLocal() as db:
        await lock_actor(db, actor)
        await db.execute(select(func.pg_advisory_xact_lock(ATTENDANCE_POLICY_LOCK)))
        latest = await db.scalar(
            select(AttendancePolicy).order_by(AttendancePolicy.version.desc()).limit(1)
        )
        today = work_date(utc_now())
        new = AttendancePolicy(
            version=latest.version + 1 if latest else 1,
            effective_from=today + DAY if latest else today,
            updated_by=actor.id,
            **values.model_dump(),
        )
        db.add(new)
        await audit(db, actor, "configure_policy", detail={"version": new.version})
        await db.commit()
        return await policy_state(db)


async def configure_holiday(actor: CurrentUser, day: date, name: str | None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await lock_actor(db, actor)
        await db.execute(select(func.pg_advisory_xact_lock(ATTENDANCE_POLICY_LOCK)))
        today = work_date(utc_now())
        if day < today:
            raise AttendanceInvalid("Holiday changes cannot alter past work dates.")
        await require_policy(db, today)
        used = await db.scalar(
            select(AttendanceDay.staff_profile_id)
            .where(AttendanceDay.day == day, AttendanceDay.leave_units > 0)
            .limit(1)
        )
        if used is not None:
            raise AttendanceError("An approved leave already uses this work date.")
        holiday = await db.get(AttendanceHoliday, day)
        if name is None:
            if holiday is None:
                raise AttendanceNotFound("Holiday not found.")
            await db.delete(holiday)
        elif holiday is None:
            db.add(AttendanceHoliday(day=day, name=name))
        else:
            holiday.name = name
        await audit(
            db,
            actor,
            "remove_holiday" if name is None else "set_holiday",
            detail={"day": day.isoformat()},
        )
        await db.commit()


async def day_without_clock(db: AsyncSession, day: date, policy: AttendancePolicy) -> str:
    if await db.get(AttendanceHoliday, day) is not None:
        return "holiday"
    return "week_off" if day.weekday() in policy.weekly_off else "absent"


def apply_clock_result(row: AttendanceDay, policy: AttendancePolicy) -> None:
    row.worked_minutes = max(0, int((row.check_out - row.check_in).total_seconds() // 60))
    row.late = row.check_in > shift_start(row.day, policy) + timedelta(minutes=policy.grace_minutes)
    full = policy.full_day_minutes if not row.leave_units else policy.half_day_minutes
    if row.worked_minutes >= full:
        row.status = "present"
    elif row.worked_minutes >= policy.half_day_minutes:
        row.status = "half_day"
    else:
        row.status = "short_day"


async def open_day(db: AsyncSession, staff_id: UUID) -> AttendanceDay | None:
    return await db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.staff_profile_id == staff_id,
            AttendanceDay.status == "checked_in",
        )
    )


def new_day(staff_id: UUID, day: date, policy: AttendancePolicy, status: str, source: str):
    return AttendanceDay(
        staff_profile_id=staff_id,
        day=day,
        policy_version=policy.version,
        status=status,
        source=source,
        worked_minutes=0,
        leave_units=0,
        late=False,
    )


async def check_clock(actor: CurrentUser, *, checking_in: bool) -> AttendanceDay:
    async with db_session.AsyncSessionLocal() as db:
        profile = await lock_actor(db, actor)
        now = utc_now()
        day = work_date(now)
        today_policy = await require_policy(db, day)
        active = await open_day(db, profile.id)
        if active is not None:
            policy = await db.get(AttendancePolicy, active.policy_version)
            if now < shift_cutoff(active.day, policy):
                if checking_in:
                    return active
                active.original_check_out = active.check_out = now
                apply_clock_result(active, policy)
                await audit(
                    db, actor, "check_out", entity_id=profile.id, detail={"day": str(active.day)}
                )
                await db.commit()
                return active
            active.status = "missing_checkout"
            await db.flush()

        row = await db.get(AttendanceDay, (profile.id, day))
        if not checking_in:
            if row is None or row.check_out is None:
                previous = await db.get(AttendanceDay, (profile.id, day - DAY))
                if previous is not None and previous.original_check_out is not None:
                    policy = await db.get(AttendancePolicy, previous.policy_version)
                    if now < shift_cutoff(previous.day, policy):
                        return previous
                raise AttendanceError("No open shift is available. Submit a correction if needed.")
            return row
        if row is not None:
            if row.check_in is not None:
                return row
            if row.leave_units == 2:
                raise AttendanceError("This date has approved full-day leave.")
        else:
            row = new_day(profile.id, day, today_policy, "checked_in", "clock")
            db.add(row)
        policy = await db.get(AttendancePolicy, row.policy_version)
        row.original_check_in = row.check_in = now
        row.status, row.source = "checked_in", "clock"
        row.late = now > shift_start(day, policy) + timedelta(minutes=policy.grace_minutes)
        await audit(db, actor, "check_in", entity_id=profile.id, detail={"day": str(day)})
        await db.commit()
        return row
