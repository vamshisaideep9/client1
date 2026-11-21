"""Attendance clock and effective-dated policy. Every clock write locks its staff row."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    AttendanceDay,
    AttendanceEmployment,
    AttendanceHoliday,
    AttendanceLineHoliday,
    AttendancePolicy,
    AttendanceRequest,
)
from app.models.audit_log import AuditAction
from app.models.profile import (
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
    SubAdminAccessProfile,
)
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User, UserStatus
from app.schemas.attendance import AttendancePolicyInput, AttendancePolicyState
from app.services.attendance_sessions import (
    IST,
    late_login,
    late_penalty_units,
    midnight_after,
    session_coverage,
)
from app.services.audit_log import record
from app.services.sub_admin_access import read_access

STAFF_ROLES = (StaffRole.TELECALLER, StaffRole.EMPLOYEE, StaffRole.SUB_ADMIN)
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
    if policy.session_clock:
        return midnight_after(day)
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


def allows_personal_attendance(role: str, policy: AttendancePolicy | None) -> bool:
    return policy is not None and (role != StaffRole.SUB_ADMIN or policy.session_clock)


async def policy_state(
    db: AsyncSession, *, can_configure_leave_rules: bool = False
) -> AttendancePolicyState:
    today = work_date(utc_now())
    return AttendancePolicyState(
        can_configure_leave_rules=can_configure_leave_rules,
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
    db: AsyncSession,
    target: StaffProfile,
    manager_id: UUID | None = None,
    *,
    business_line: str | None = None,
    include_direct: bool = True,
) -> set[UUID]:
    """Lock matching memberships and teams through the decision commit."""
    criteria = [
        StaffTeamMember.staff_profile_uuid == target.id,
        StaffTeam.member_role == target.role.value,
        StaffTeam.archived_at.is_(None),
    ]
    if manager_id is not None:
        criteria.append(StaffTeam.manager_staff_profile_uuid == manager_id)
    if business_line is not None:
        criteria.append(StaffTeam.business_line == business_line)
    manager_rows = (
        await db.execute(
            select(StaffProfile.auth_user_uuid, StaffTeam.business_line, SubAdminAccessProfile)
            .join(StaffTeamMember, StaffTeamMember.team_uuid == StaffTeam.id)
            .join(StaffProfile, StaffProfile.id == StaffTeam.manager_staff_profile_uuid)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .outerjoin(
                SubAdminAccessProfile, SubAdminAccessProfile.staff_profile_uuid == StaffProfile.id
            )
            .where(
                *criteria,
                StaffProfile.role == StaffRole.SUB_ADMIN,
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update(read=True, of=(StaffTeam, StaffTeamMember))
        )
    ).all()
    managers = {
        auth_user_uuid
        for auth_user_uuid, line, access_row in manager_rows
        if access_row is None or line in read_access(access_row).lines_for("team_manager", "review")
    }
    # A direct assignment grants attendance reach only for records with a recorded line.
    if include_direct and business_line is not None:
        direct = (
            await db.execute(
                select(StaffProfile.auth_user_uuid, SubAdminAccessProfile)
                .join(AttendanceEmployment, AttendanceEmployment.reviewer_id == StaffProfile.id)
                .join(User, User.id == StaffProfile.auth_user_uuid)
                .outerjoin(
                    SubAdminAccessProfile,
                    SubAdminAccessProfile.staff_profile_uuid == StaffProfile.id,
                )
                .where(
                    AttendanceEmployment.staff_profile_id == target.id,
                    AttendanceEmployment.business_line == business_line,
                    StaffProfile.id == manager_id if manager_id else True,
                    StaffProfile.role == StaffRole.SUB_ADMIN,
                    StaffProfile.scope == ProfileScope.PLATFORM,
                    StaffProfile.status == ProfileStatus.ACTIVE,
                    User.status == UserStatus.ACTIVE,
                )
                .with_for_update(read=True, of=AttendanceEmployment)
            )
        ).one_or_none()
        if direct is not None and (
            direct[1] is None
            or business_line in read_access(direct[1]).lines_for("team_manager", "review")
        ):
            managers.add(direct[0])
    return managers


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
        admin = await lock_actor(db, actor)
        await db.execute(select(func.pg_advisory_xact_lock(ATTENDANCE_POLICY_LOCK)))
        latest = await db.scalar(
            select(AttendancePolicy).order_by(AttendancePolicy.version.desc()).limit(1)
        )
        today = work_date(utc_now())
        if latest and latest.session_clock and not values.session_clock:
            raise AttendanceInvalid("The session clock cannot be replaced by the legacy clock.")
        effective_from = today + DAY if latest else today
        if values.session_clock and not (latest and latest.session_clock):
            effective_from = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        if latest:
            effective_from = max(effective_from, latest.effective_from)
        values_dict = values.model_dump()
        previous_rules = latest.monthly_leave_rules if latest else {}
        previous_retention = latest.certificate_retention_days if latest else None
        if "monthly_leave_rules" not in values.model_fields_set:
            values_dict["monthly_leave_rules"] = previous_rules
        if "certificate_retention_days" not in values.model_fields_set:
            values_dict["certificate_retention_days"] = previous_retention
        rules = values_dict["monthly_leave_rules"]
        retention = values_dict["certificate_retention_days"]
        if (
            any(rule["certificate_after_days"] is not None for rule in rules.values())
            and retention is None
        ):
            raise AttendanceInvalid("Set certificate retention before requiring a certificate.")
        if not rules.keys() <= values.leave_quotas.keys():
            raise AttendanceInvalid("Keep leave types with monthly rules in the policy.")
        if rules != previous_rules or retention != previous_retention:
            if not admin.is_primary_admin:
                raise AttendanceForbidden("Only Main Admin may configure monthly leave rules.")
            revised_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            effective_from = max(effective_from, revised_month)
            if effective_from.day != 1:
                effective_from = (effective_from.replace(day=28) + timedelta(days=4)).replace(day=1)
            affected_types = {
                kind
                for kind in previous_rules.keys() | rules.keys()
                if previous_rules.get(kind) != rules.get(kind) or retention != previous_retention
            }
            if affected_types and await db.scalar(
                select(AttendanceRequest.id)
                .where(
                    AttendanceRequest.status.in_(("pending", "approved")),
                    AttendanceRequest.leave_type.in_(affected_types),
                    AttendanceRequest.end_day >= effective_from,
                )
                .limit(1)
            ):
                raise AttendanceError(
                    "Resolve existing future leave before changing its monthly rules."
                )
        new = AttendancePolicy(
            version=latest.version + 1 if latest else 1,
            effective_from=effective_from,
            updated_by=actor.id,
            **values_dict,
        )
        db.add(new)
        await audit(db, actor, "configure_policy", detail={"version": new.version})
        await db.commit()
        return await policy_state(db, can_configure_leave_rules=admin.is_primary_admin)


async def configure_holiday(
    actor: CurrentUser, day: date, name: str | None, business_line: str | None = None
) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await lock_actor(db, actor)
        await db.execute(select(func.pg_advisory_xact_lock(ATTENDANCE_POLICY_LOCK)))
        today = work_date(utc_now())
        if day < today:
            raise AttendanceInvalid("Holiday changes cannot alter past work dates.")
        await require_policy(db, today)
        recorded = select(AttendanceDay.staff_profile_id).where(AttendanceDay.day == day)
        if business_line is None:
            recorded = recorded.where(AttendanceDay.leave_units > 0)
        else:
            recorded = recorded.where(AttendanceDay.business_line == business_line)
        used = await db.scalar(recorded.limit(1))
        if used is not None:
            raise AttendanceError("This calendar date already has attendance or approved leave.")
        holiday = (
            await db.get(AttendanceLineHoliday, (business_line, day))
            if business_line is not None
            else await db.get(AttendanceHoliday, day)
        )
        if name is None:
            if holiday is None:
                raise AttendanceNotFound("Holiday not found.")
            await db.delete(holiday)
        elif holiday is None:
            db.add(
                AttendanceLineHoliday(business_line=business_line, day=day, name=name)
                if business_line is not None
                else AttendanceHoliday(day=day, name=name)
            )
        else:
            holiday.name = name
        await audit(
            db,
            actor,
            "remove_holiday" if name is None else "set_holiday",
            detail={"day": day.isoformat(), "business_line": business_line},
        )
        await db.commit()


async def day_without_clock(
    db: AsyncSession, day: date, policy: AttendancePolicy, business_line: str | None = None
) -> str:
    if business_line is not None and await db.get(AttendanceLineHoliday, (business_line, day)):
        return "holiday"
    if await db.get(AttendanceHoliday, day) is not None:
        return "holiday"
    return "week_off" if day.weekday() in policy.weekly_off else "absent"


def require_employment_days(
    employment: AttendanceEmployment | None, start: date, end: date
) -> None:
    if employment and (
        start < employment.start_day or (employment.end_day and end > employment.end_day)
    ):
        raise AttendanceInvalid("Choose dates within your recorded employment period.")


def apply_clock_result(row: AttendanceDay, policy: AttendancePolicy) -> None:
    if policy.session_clock:
        coverage = session_coverage(row.day, row.check_in, row.check_out)
        row.worked_minutes = coverage.minutes_worked
        row.morning_covered = coverage.morning
        row.afternoon_covered = coverage.afternoon
        row.late = (
            coverage.late
            and row.calendar_status == "absent"
            and "morning" not in row.leave_sessions
            and "on_duty" not in row.adjustments
        )
        row.early_exit = coverage.early_exit and row.calendar_status == "absent"
        covered = int(coverage.morning or "morning" in row.leave_sessions) + int(
            coverage.afternoon
            or "afternoon" in row.leave_sessions
            or (coverage.morning and "early_exit" in row.adjustments)
        )
        if "on_duty" in row.adjustments:
            covered = 2
        if not row.leave_sessions:
            covered = min(2, covered + row.leave_units)
        row.uncovered_units = (2 - covered) * 2 if row.calendar_status == "absent" else 0
        row.status = ("short_day", "half_day", "present")[covered]
        return
    row.worked_minutes = max(0, int((row.check_out - row.check_in).total_seconds() // 60))
    row.late = row.check_in > shift_start(row.day, policy) + timedelta(minutes=policy.grace_minutes)
    full = policy.full_day_minutes if not row.leave_units else policy.half_day_minutes
    if row.worked_minutes >= full:
        row.status = "present"
    elif row.worked_minutes >= policy.half_day_minutes:
        row.status = "half_day"
    else:
        row.status = "short_day"


async def recalculate_late_penalties(db: AsyncSession, staff_id: UUID, day: date) -> None:
    """Call while holding the same staff lock used for punches and approvals."""
    start = day.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    await db.flush()
    rows = await db.scalars(
        select(AttendanceDay)
        .join(AttendancePolicy, AttendanceDay.policy_version == AttendancePolicy.version)
        .where(
            AttendanceDay.staff_profile_id == staff_id,
            AttendanceDay.day >= start,
            AttendanceDay.day < end,
            AttendancePolicy.session_clock.is_(True),
        )
        .order_by(AttendanceDay.day)
    )
    ordinal = 0
    for row in rows:
        penalty = 0
        if row.late and "late_waiver" not in row.adjustments:
            ordinal += 1
            penalty = late_penalty_units(ordinal)
        if row.uncovered_units is None:
            row.lop_units = None
        else:
            row.lop_units = min(4 - 2 * row.leave_units, row.uncovered_units + penalty)


def close_expired_day(row: AttendanceDay, policy: AttendancePolicy) -> None:
    if policy.session_clock:
        row.system_check_out = row.check_out = midnight_after(row.day)
        apply_clock_result(row, policy)
    else:
        row.status = "missing_checkout"


async def open_day(db: AsyncSession, staff_id: UUID) -> AttendanceDay | None:
    return await db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.staff_profile_id == staff_id,
            AttendanceDay.status == "checked_in",
        )
    )


def new_day(
    staff_id: UUID,
    day: date,
    policy: AttendancePolicy,
    status: str,
    source: str,
    *,
    calendar_status: str | None = None,
    business_line: str | None = None,
) -> AttendanceDay:
    return AttendanceDay(
        staff_profile_id=staff_id,
        day=day,
        policy_version=policy.version,
        status=status,
        source=source,
        worked_minutes=0,
        leave_units=0,
        late=False,
        calendar_status=calendar_status if policy.session_clock else None,
        business_line=business_line,
        adjustments={},
        leave_sessions={},
    )


async def check_clock(actor: CurrentUser, *, checking_in: bool) -> AttendanceDay:
    async with db_session.AsyncSessionLocal() as db:
        profile = await lock_actor(db, actor)
        now = utc_now()
        day = work_date(now)
        today_policy = await require_policy(db, day)
        if not allows_personal_attendance(profile.role, today_policy):
            raise AttendanceError("Attendance for Sub Admins opens with the session clock.")
        active = await open_day(db, profile.id)
        if active is not None:
            policy = await db.get(AttendancePolicy, active.policy_version)
            if now < shift_cutoff(active.day, policy):
                if checking_in:
                    return active
                active.original_check_out = active.check_out = now
                apply_clock_result(active, policy)
                if policy.session_clock:
                    await recalculate_late_penalties(db, profile.id, active.day)
                await audit(
                    db, actor, "check_out", entity_id=profile.id, detail={"day": str(active.day)}
                )
                await db.commit()
                return active
            close_expired_day(active, policy)
            if policy.session_clock:
                await recalculate_late_penalties(db, profile.id, active.day)
            await db.flush()

        row = await db.get(AttendanceDay, (profile.id, day))
        if not checking_in:
            if row is None or row.check_out is None:
                previous = await db.get(AttendanceDay, (profile.id, day - DAY))
                if previous is not None and previous.system_check_out is not None:
                    await db.commit()
                    return previous
                if previous is not None and previous.original_check_out is not None:
                    policy = await db.get(AttendancePolicy, previous.policy_version)
                    if now < shift_cutoff(previous.day, policy):
                        return previous
                raise AttendanceError("No open shift is available. Submit a correction if needed.")
            return row
        employment = await db.get(AttendanceEmployment, profile.id)
        require_employment_days(employment, day, day)
        business_line = (
            employment.business_line
            if employment
            else (actor.business_line if today_policy.session_clock else None)
        )
        await db.execute(select(func.pg_advisory_xact_lock_shared(ATTENDANCE_POLICY_LOCK)))
        if row is not None:
            if row.check_in is not None:
                return row
            if row.leave_units == 2:
                raise AttendanceError("This date has approved full-day leave.")
        else:
            row = new_day(
                profile.id,
                day,
                today_policy,
                "checked_in",
                "clock",
                calendar_status=await day_without_clock(db, day, today_policy, business_line)
                if today_policy.session_clock
                else None,
                business_line=business_line,
            )
            db.add(row)
        policy = await db.get(AttendancePolicy, row.policy_version)
        if policy.session_clock and row.business_line not in (None, business_line):
            raise AttendanceError("This date is recorded in another business line.")
        if policy.session_clock and row.business_line is None:
            row.business_line = business_line
        row.original_check_in = row.check_in = now
        row.status, row.source = "checked_in", "clock"
        row.late = (
            late_login(day, now)
            and row.calendar_status == "absent"
            and "morning" not in row.leave_sessions
            and "on_duty" not in row.adjustments
            if policy.session_clock
            else now > shift_start(day, policy) + timedelta(minutes=policy.grace_minutes)
        )
        await audit(db, actor, "check_in", entity_id=profile.id, detail={"day": str(day)})
        await db.commit()
        return row
