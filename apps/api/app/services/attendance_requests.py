"""Attendance request state transitions, quota accounting and notifications."""

from collections import Counter
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    AttendanceDay,
    AttendancePolicy,
    AttendanceRequest,
)
from app.models.notification import Notification, NotificationType
from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
from app.models.user import User, UserStatus
from app.schemas.attendance import (
    AttendanceBalance,
    AttendanceCorrectionInput,
    AttendanceDecisionInput,
    AttendanceLeaveInput,
)
from app.services import attendance as clock


def notify(db: AsyncSession, recipients: set[UUID], title: str, message: str, href: str) -> None:
    db.add_all(
        Notification(
            user_uuid=recipient,
            type=NotificationType.ATTENDANCE_REQUEST_UPDATED,
            title=title,
            body=message,
            href=href,
        )
        for recipient in recipients
    )


async def _reviewers(db: AsyncSession, target: StaffProfile) -> set[UUID]:
    managers = await clock.managers_for(db, target)
    if managers:
        return managers
    return set(
        await db.scalars(
            select(StaffProfile.auth_user_uuid)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(
                StaffProfile.role == StaffRole.ADMIN,
                StaffProfile.scope == ProfileScope.PLATFORM,
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
            )
        )
    )


def _validate_times(
    day: date, start: datetime, end: datetime, policy: AttendancePolicy, now: datetime
):
    if (
        clock.work_date(start) != day
        or end <= start
        or end > now
        or end > clock.shift_cutoff(day, policy)
    ):
        raise clock.AttendanceInvalid(
            "Check-in must be on the work date and check-out within that shift and in the past."
        )


async def submit(
    actor: CurrentUser, values: AttendanceLeaveInput | AttendanceCorrectionInput
) -> AttendanceRequest:
    async with db_session.AsyncSessionLocal() as db:
        profile = await clock.lock_actor(db, actor)
        now = clock.utc_now()
        today = clock.work_date(now)
        await clock.require_policy(db, today)
        if isinstance(values, AttendanceLeaveInput):
            if values.start_day < today:
                raise clock.AttendanceInvalid("Choose a current or future leave date.")
            policy = await clock.require_policy(db, values.start_day)
            if values.leave_type not in policy.leave_quotas:
                raise clock.AttendanceInvalid(
                    "This leave type is unavailable for the requested dates."
                )
            request = AttendanceRequest(
                kind="leave",
                start_day=values.start_day,
                end_day=values.end_day,
                reason=values.reason,
                leave_type=values.leave_type,
                half_day=values.half_day,
            )
        else:
            if values.day < clock.work_date(profile.created_at) or values.day > today:
                raise clock.AttendanceInvalid("Choose an existing work date for your account.")
            row = await db.get(AttendanceDay, (profile.id, values.day))
            policy = (
                await db.get(AttendancePolicy, row.policy_version)
                if row
                else await clock.require_policy(db, values.day)
            )
            _validate_times(values.day, values.check_in, values.check_out, policy, now)
            request = AttendanceRequest(
                kind="correction",
                start_day=values.day,
                end_day=values.day,
                reason=values.reason,
                requested_check_in=values.check_in,
                requested_check_out=values.check_out,
            )
        existing = await db.scalar(
            select(AttendanceRequest.id)
            .where(
                AttendanceRequest.staff_profile_id == profile.id,
                AttendanceRequest.kind == request.kind,
                AttendanceRequest.status == "pending",
                AttendanceRequest.start_day <= request.end_day,
                AttendanceRequest.end_day >= request.start_day,
            )
            .limit(1)
        )
        if existing is not None:
            raise clock.AttendanceError("A pending request overlaps these dates.")
        request.staff_profile_id, request.requester_id = profile.id, actor.id
        request.created_at = now
        db.add(request)
        await db.flush()
        await clock.audit(
            db, actor, "submit_request", entity_id=request.id, detail={"kind": request.kind}
        )
        notify(
            db,
            await _reviewers(db, profile),
            "Attendance request submitted",
            "A staff request is ready for review.",
            "/dashboard/attendance-management",
        )
        await db.commit()
        return request


async def usages(db: AsyncSession, staff_id: UUID, year: int) -> Counter:
    start, end = date(year, 1, 1), date(year, 12, 31)
    data = await db.execute(
        select(AttendanceRequest.leave_type, AttendanceRequest.approved_units).where(
            AttendanceRequest.staff_profile_id == staff_id,
            AttendanceRequest.kind == "leave",
            AttendanceRequest.status == "approved",
            AttendanceRequest.start_day <= end,
            AttendanceRequest.end_day >= start,
        )
    )
    used: Counter = Counter()
    for leave_type, per_day in data:
        used[leave_type] += sum(value for day, value in per_day.items() if day[:4] == str(year))
    return used


async def balances(db: AsyncSession, staff_id: UUID, day: date) -> list[AttendanceBalance]:
    policy = await clock.policy_for(db, day)
    if policy is None:
        return []
    used = await usages(db, staff_id, day.year)
    return [
        AttendanceBalance(leave_type=kind, allocated_units=count, used_units=used[kind])
        for kind, count in sorted(policy.leave_quotas.items())
    ]


async def _apply_leave(db: AsyncSession, request: AttendanceRequest) -> None:
    by_year: Counter = Counter()
    quota: dict[int, int] = {}
    applied: dict[str, int] = {}
    units = 1 if request.half_day else 2
    day = request.start_day
    while day <= request.end_day:
        policy = await clock.require_policy(db, day)
        if request.leave_type not in policy.leave_quotas:
            raise clock.AttendanceError(
                "This leave type is unavailable for part of the requested period."
            )
        if await clock.day_without_clock(db, day, policy) == "absent":
            row = await db.get(AttendanceDay, (request.staff_profile_id, day))
            if row is None:
                row = clock.new_day(request.staff_profile_id, day, policy, "on_leave", "leave")
                db.add(row)
            if row.leave_units or (units == 2 and row.check_in is not None):
                raise clock.AttendanceError("These dates overlap approved leave or recorded work.")
            row.leave_units, row.leave_request_id = units, request.id
            if row.check_in is None:
                row.status, row.source = "on_leave", "leave"
            elif row.check_out is not None:
                clock.apply_clock_result(row, await db.get(AttendancePolicy, row.policy_version))
            applied[day.isoformat()] = units
            by_year[day.year] += units
            maximum = policy.leave_quotas[request.leave_type]
            quota[day.year] = min(quota.get(day.year, maximum), maximum)
        day += clock.DAY
    if not applied:
        raise clock.AttendanceError("The request contains no scheduled work days.")
    for year, count in by_year.items():
        used = await usages(db, request.staff_profile_id, year)
        if used[request.leave_type] + count > quota[year]:
            raise clock.AttendanceError(
                f"This request exceeds the available leave balance for {year}."
            )
    request.approved_units = applied


async def _undo_leave(db: AsyncSession, request: AttendanceRequest, today: date) -> None:
    for iso in request.approved_units:
        day = date.fromisoformat(iso)
        row = await db.get(AttendanceDay, (request.staff_profile_id, day))
        if row is None or row.leave_request_id != request.id:
            continue
        row.leave_units, row.leave_request_id = 0, None
        policy = await db.get(AttendancePolicy, row.policy_version)
        if row.check_in is None and row.source == "leave":
            if day >= today:
                await db.delete(row)
            else:
                row.status = await clock.day_without_clock(db, day, policy)
                row.source = "rollover"
        elif row.check_out is not None:
            clock.apply_clock_result(row, policy)


async def _apply_correction(db: AsyncSession, request: AttendanceRequest, now: datetime) -> None:
    key = (request.staff_profile_id, request.start_day)
    row = await db.get(AttendanceDay, key)
    policy = (
        await db.get(AttendancePolicy, row.policy_version)
        if row
        else await clock.require_policy(db, request.start_day)
    )
    _validate_times(
        request.start_day, request.requested_check_in, request.requested_check_out, policy, now
    )
    if row is None:
        row = clock.new_day(*key, policy, "present", "correction")
        db.add(row)
        request.correction_before = None
    else:
        if row.leave_units == 2:
            raise clock.AttendanceError("Cancel full-day leave before correcting this day.")
        if row.correction_request_id is not None:
            raise clock.AttendanceError("Reopen the existing approved correction first.")
        request.correction_before = {
            "check_in": row.check_in.isoformat() if row.check_in else None,
            "check_out": row.check_out.isoformat() if row.check_out else None,
            "worked_minutes": row.worked_minutes,
            "late": row.late,
            "status": row.status,
            "source": row.source,
        }
    row.check_in, row.check_out = request.requested_check_in, request.requested_check_out
    row.correction_request_id, row.source = request.id, "correction"
    clock.apply_clock_result(row, policy)


async def _undo_correction(db: AsyncSession, request: AttendanceRequest, now: datetime) -> None:
    row = await db.get(AttendanceDay, (request.staff_profile_id, request.start_day))
    if row is None or row.correction_request_id != request.id:
        raise clock.AttendanceError("This correction no longer owns the attendance record.")
    before = request.correction_before
    policy = await db.get(AttendancePolicy, row.policy_version)
    if not before:
        row.check_in, row.check_out, row.worked_minutes, row.late = None, None, 0, False
        row.status = (
            "on_leave" if row.leave_units else await clock.day_without_clock(db, row.day, policy)
        )
        row.source = "leave" if row.leave_units else "rollover"
    else:
        row.check_in = datetime.fromisoformat(before["check_in"]) if before["check_in"] else None
        row.check_out = datetime.fromisoformat(before["check_out"]) if before["check_out"] else None
        row.status, row.source = before["status"], before["source"]
        row.worked_minutes, row.late = before["worked_minutes"], before["late"]
        if row.status == "checked_in" and (
            now >= clock.shift_cutoff(row.day, policy)
            or await clock.open_day(db, row.staff_profile_id)
        ):
            row.status = "missing_checkout"
        if row.check_out is not None:
            clock.apply_clock_result(row, policy)
    row.correction_request_id = None


async def _decision(
    actor: CurrentUser,
    request_id: UUID,
    values: AttendanceDecisionInput | None,
) -> AttendanceRequest:
    async with db_session.AsyncSessionLocal() as db:
        reviewer = await clock.lock_actor(db, actor)
        target_id = await db.scalar(
            select(AttendanceRequest.staff_profile_id).where(AttendanceRequest.id == request_id)
        )
        if target_id is None or (values is None and target_id != reviewer.id):
            raise clock.AttendanceNotFound("Attendance request not found.")
        target = reviewer if target_id == reviewer.id else await clock.lock_staff(db, target_id)
        request = await db.get(AttendanceRequest, request_id, with_for_update=True)
        now = clock.utc_now()
        today = clock.work_date(now)
        await clock.require_policy(db, today)
        if request.kind == "leave":
            await db.execute(select(func.pg_advisory_xact_lock_shared(ATTENDANCE_POLICY_LOCK)))
        before = request.status
        if values is None:
            if request.requester_id != actor.id:
                raise clock.AttendanceNotFound("Attendance request not found.")
            if before == "cancelled":
                return request
            if before != "pending" and not (
                before == "approved" and request.kind == "leave" and request.start_day > today
            ):
                raise clock.AttendanceError("This request can no longer be cancelled here.")
            status, note = "cancelled", "Cancelled by requester."
        else:
            if actor.id in (request.requester_id, target.auth_user_uuid):
                raise clock.AttendanceForbidden("You cannot decide your own attendance request.")
            if reviewer.role == StaffRole.SUB_ADMIN:
                if not await clock.managers_for(db, target, reviewer.id):
                    raise clock.AttendanceNotFound("Attendance request not found.")
                if before != "pending" or values.status == "cancelled":
                    raise clock.AttendanceError("Only Admin can override an attendance decision.")
            elif reviewer.role != StaffRole.ADMIN:
                raise clock.AttendanceForbidden("Only Admin or a current team manager can decide.")
            if len(request.decisions) != values.expected_decisions:
                raise clock.AttendanceError("The request changed. Reload it and try again.")
            status, note = values.status, values.note
            if before == status:
                return request
            if before == "cancelled" and status != "approved":
                raise clock.AttendanceError("Only approval can reopen a cancelled request.")
        if before == "approved" and status != "approved":
            if request.kind == "leave":
                await _undo_leave(db, request, today)
            else:
                await _undo_correction(db, request, now)
        if status == "approved":
            if request.kind == "leave":
                await _apply_leave(db, request)
            else:
                await _apply_correction(db, request, now)
        request.status = status
        request.decisions = [
            *request.decisions,
            {
                "status": status,
                "actor_id": str(actor.id),
                "actor_role": actor.role,
                "at": now.isoformat(),
                "note": note,
            },
        ]
        await clock.audit(
            db,
            actor,
            "decide_request",
            entity_id=request.id,
            detail={"before": before, "after": status, "kind": request.kind},
        )
        recipients = await _reviewers(db, target) if values is None else {target.auth_user_uuid}
        notify(
            db,
            recipients,
            "Attendance request updated",
            f"An attendance request was {status}.",
            "/dashboard/attendance-management" if values is None else "/dashboard/attendance",
        )
        await db.commit()
        return request


async def decide(actor: CurrentUser, request_id: UUID, values: AttendanceDecisionInput):
    return await _decision(actor, request_id, values)


async def cancel(actor: CurrentUser, request_id: UUID):
    return await _decision(actor, request_id, None)
