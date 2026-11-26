"""Attendance request state transitions, quota accounting and notifications."""

from collections import Counter
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    ATTENDANCE_POLICY_LOCK,
    AttendanceDay,
    AttendanceEmployment,
    AttendancePolicy,
    AttendanceRequest,
)
from app.models.notification import Notification, NotificationType
from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
from app.models.user import User, UserStatus
from app.schemas.attendance import (
    AttendanceAdjustmentInput,
    AttendanceBalance,
    AttendanceCorrectionInput,
    AttendanceDecisionInput,
    AttendanceLeaveInput,
)
from app.services import attendance as clock
from app.services import attendance_adjustments, attendance_certificates, attendance_leave_policy


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


async def _admins(db: AsyncSession) -> set[UUID]:
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


async def _reviewers(
    db: AsyncSession,
    target: StaffProfile,
    *,
    business_line: str | None = None,
    include_direct: bool = True,
) -> set[UUID]:
    managers = await clock.managers_for(
        db, target, business_line=business_line, include_direct=include_direct
    )
    if managers:
        return managers
    return await _admins(db)


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
    actor: CurrentUser,
    values: AttendanceLeaveInput | AttendanceCorrectionInput | AttendanceAdjustmentInput,
) -> AttendanceRequest:
    async with db_session.AsyncSessionLocal() as db:
        profile = await clock.lock_actor(db, actor)
        employment = await db.get(AttendanceEmployment, profile.id)
        first_day = employment.start_day if employment else clock.work_date(profile.created_at)
        calendar_line = employment.business_line if employment else actor.business_line
        now = clock.utc_now()
        today = clock.work_date(now)
        active_policy = await clock.require_policy(db, today)
        if not clock.allows_personal_attendance(profile.role, active_policy):
            raise clock.AttendanceError("Attendance for Sub Admins opens with the session clock.")
        await db.execute(select(func.pg_advisory_xact_lock_shared(ATTENDANCE_POLICY_LOCK)))
        if isinstance(values, AttendanceLeaveInput):
            if values.start_day < today:
                raise clock.AttendanceInvalid("Choose a current or future leave date.")
            policy = await clock.require_policy(db, values.start_day)
            end_policy = await clock.require_policy(db, values.end_day)
            if policy.session_clock != end_policy.session_clock:
                raise clock.AttendanceInvalid("Submit separate requests across the policy change.")
            if policy.session_clock and values.half_day and values.leave_session is None:
                raise clock.AttendanceInvalid("Choose a morning or afternoon session.")
            if values.leave_type not in policy.leave_quotas:
                raise clock.AttendanceInvalid(
                    "This leave type is unavailable for the requested dates."
                )
            rule = attendance_leave_policy.rule_for(policy, values.leave_type)
            end_rule = attendance_leave_policy.rule_for(end_policy, values.leave_type)
            if rule != end_rule or (
                rule and policy.certificate_retention_days != end_policy.certificate_retention_days
            ):
                raise clock.AttendanceInvalid(
                    "Submit separate requests across the leave policy change."
                )
            if rule and values.end_day.year > 9998:
                raise clock.AttendanceInvalid("Choose leave dates before the year 9999.")
            required = (
                rule is not None
                and rule.certificate_after_days is not None
                and (values.end_day - values.start_day).days + 1 > rule.certificate_after_days
            )
            request = AttendanceRequest(
                kind="leave",
                start_day=values.start_day,
                end_day=values.end_day,
                reason=values.reason,
                leave_type=values.leave_type,
                half_day=values.half_day,
                leave_session=values.leave_session,
                certificate_retention_days=policy.certificate_retention_days if required else None,
            )
        elif isinstance(values, AttendanceAdjustmentInput):
            if values.day < first_day or (
                values.day > today and values.adjustment_type != "on_duty"
            ):
                raise clock.AttendanceInvalid("Choose an eligible work date.")
            policy = await clock.require_policy(db, values.day)
            if not policy.session_clock:
                raise clock.AttendanceError("Regularization opens with the session clock.")
            request = AttendanceRequest(
                kind="adjustment",
                adjustment_type=values.adjustment_type,
                start_day=values.day,
                end_day=await attendance_adjustments.comp_off_date(db, values.day, calendar_line)
                if values.adjustment_type == "comp_off"
                else values.day,
                reason=values.reason,
            )
        else:
            if values.day < first_day or values.day > today:
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
        clock.require_employment_days(employment, request.start_day, request.end_day)
        await clock.ensure_period_open(db, request.start_day, request.end_day)
        if not clock.allows_personal_attendance(profile.role, policy):
            raise clock.AttendanceError("This date predates attendance for Sub Admins.")
        overlap = select(AttendanceRequest.id).where(
            AttendanceRequest.staff_profile_id == profile.id,
            AttendanceRequest.kind == request.kind,
            AttendanceRequest.adjustment_type == request.adjustment_type,
            AttendanceRequest.status == "pending",
            AttendanceRequest.start_day <= request.end_day,
            AttendanceRequest.end_day >= request.start_day,
        )
        if request.leave_session:
            overlap = overlap.where(
                or_(
                    AttendanceRequest.leave_session.is_(None),
                    AttendanceRequest.leave_session == request.leave_session,
                )
            )
        existing = await db.scalar(overlap.limit(1))
        if existing is not None:
            raise clock.AttendanceError("A pending request overlaps these dates.")
        request.staff_profile_id, request.requester_id = profile.id, actor.id
        request.created_at = now
        request.two_stage = policy.session_clock
        request.business_line = calendar_line if employment or policy.session_clock else None
        db.add(request)
        await db.flush()
        await clock.audit(
            db, actor, "submit_request", entity_id=request.id, detail={"kind": request.kind}
        )
        notify(
            db,
            await _reviewers(
                db, profile, business_line=request.business_line, include_direct=request.two_stage
            ),
            "Attendance request submitted",
            "A staff request is ready for review.",
            "/dashboard/attendance-management",
        )
        await db.commit()
        return request


async def usages(db: AsyncSession, staff_id: UUID, year: int) -> Counter:
    start, end = date(year, 1, 1), date(year, 12, 31)
    data = await db.execute(
        select(
            AttendanceRequest.leave_type,
            AttendanceRequest.approved_units,
            AttendanceRequest.monthly_charges,
        ).where(
            AttendanceRequest.staff_profile_id == staff_id,
            AttendanceRequest.kind == "leave",
            AttendanceRequest.status == "approved",
            AttendanceRequest.start_day <= end,
            AttendanceRequest.end_day >= start,
        )
    )
    used: Counter = Counter()
    for leave_type, per_day, monthly in data:
        used[leave_type] += sum(
            value for day, value in per_day.items() if day[:4] == str(year) and day not in monthly
        )
    return used


async def balances(db: AsyncSession, staff_id: UUID, day: date) -> list[AttendanceBalance]:
    policy = await clock.policy_for(db, day)
    if policy is None:
        return []
    used = await usages(db, staff_id, day.year)
    annual = [
        AttendanceBalance(leave_type=kind, allocated_units=count, used_units=used[kind])
        for kind, count in sorted(policy.leave_quotas.items())
        if kind not in policy.monthly_leave_rules
    ]
    if not policy.monthly_leave_rules:
        return annual
    monthly = await attendance_leave_policy.month_balances(db, staff_id, day.replace(day=1))
    return sorted([*annual, *monthly], key=lambda balance: balance.leave_type)


async def _apply_leave(db: AsyncSession, request: AttendanceRequest) -> None:
    by_year: Counter = Counter()
    quota: dict[int, int] = {}
    applied: dict[str, int] = {}
    monthly: dict[str, int] = {}
    sandwich_days: list[date] = []
    units = 1 if request.half_day else 2
    day = request.start_day
    while day <= request.end_day:
        policy = await clock.require_policy(db, day)
        if request.leave_type not in policy.leave_quotas:
            raise clock.AttendanceError(
                "This leave type is unavailable for part of the requested period."
            )
        rule = attendance_leave_policy.rule_for(policy, request.leave_type)
        if await clock.day_without_clock(db, day, policy, request.business_line) == "absent":
            row = await db.get(AttendanceDay, (request.staff_profile_id, day))
            if row is None:
                row = clock.new_day(
                    request.staff_profile_id,
                    day,
                    policy,
                    "on_leave",
                    "leave",
                    calendar_status="absent",
                    business_line=request.business_line,
                )
                db.add(row)
            if policy.session_clock and row.business_line not in (None, request.business_line):
                raise clock.AttendanceError("This date is recorded in another business line.")
            if policy.session_clock and row.business_line is None:
                row.business_line = request.business_line
            sessions = ("morning", "afternoon") if units == 2 else (request.leave_session,)
            if row.adjustments.get("on_duty") or (
                (row.leave_units + units == 2) and row.check_in is not None and row.leave_units
            ):
                raise clock.AttendanceError("These dates overlap approved leave or recorded work.")
            if units == 2 and row.check_in is not None:
                raise clock.AttendanceError("These dates overlap approved leave or recorded work.")
            if policy.session_clock and all(sessions):
                if (row.leave_units and not row.leave_sessions) or any(
                    session in row.leave_sessions for session in sessions
                ):
                    raise clock.AttendanceError("These dates overlap approved leave.")
                row.leave_sessions = {
                    **row.leave_sessions,
                    **dict.fromkeys(sessions, str(request.id)),
                }
                row.leave_units = len(row.leave_sessions)
            else:
                if row.leave_units:
                    raise clock.AttendanceError("These dates overlap approved leave.")
                row.leave_units = units
            row.leave_request_id = request.id
            if row.check_in is None:
                row.status, row.source = "on_leave", "leave"
                if policy.session_clock and day < clock.work_date(clock.utc_now()):
                    row.uncovered_units = row.lop_units = (2 - row.leave_units) * 2
            elif row.check_out is not None or row.system_check_out is not None:
                clock.apply_clock_result(row, await db.get(AttendancePolicy, row.policy_version))
                if policy.session_clock:
                    await clock.recalculate_late_penalties(db, request.staff_profile_id, day)
            applied[day.isoformat()] = units
            if rule is not None:
                monthly[day.isoformat()] = units
            else:
                by_year[day.year] += units
                maximum = policy.leave_quotas[request.leave_type]
                quota[day.year] = min(quota.get(day.year, maximum), maximum)
        elif rule is not None and rule.sandwich:
            sandwich_days.append(day)
        day += clock.DAY
    if not applied:
        raise clock.AttendanceError("The request contains no scheduled work days.")
    for year, count in by_year.items():
        used = await usages(db, request.staff_profile_id, year)
        if used[request.leave_type] + count > quota[year]:
            raise clock.AttendanceError(
                f"This request exceeds the available leave balance for {year}."
            )
    if monthly:
        first, last = min(applied), max(applied)
        for off_day in sandwich_days:
            iso = off_day.isoformat()
            if first < iso < last:
                monthly[iso] = 2
        await attendance_leave_policy.month_balances(
            db,
            request.staff_profile_id,
            request.end_day.replace(day=1),
            kind=request.leave_type,
            additional=monthly,
        )
    request.approved_units = applied
    request.monthly_charges = monthly


async def _undo_leave(db: AsyncSession, request: AttendanceRequest, today: date) -> None:
    for iso in request.approved_units:
        day = date.fromisoformat(iso)
        row = await db.get(AttendanceDay, (request.staff_profile_id, day))
        if row is None:
            continue
        if str(request.id) in row.leave_sessions.values():
            row.leave_sessions = {
                session: owner
                for session, owner in row.leave_sessions.items()
                if owner != str(request.id)
            }
            row.leave_units = len(row.leave_sessions)
            row.leave_request_id = (
                UUID(next(iter(row.leave_sessions.values()))) if row.leave_sessions else None
            )
        elif row.leave_request_id != request.id:
            continue
        else:
            row.leave_units, row.leave_request_id = 0, None
        policy = await db.get(AttendancePolicy, row.policy_version)
        if row.check_in is None and row.source == "leave" and not row.leave_units:
            if day >= today:
                await db.delete(row)
            else:
                row.status = row.calendar_status or await clock.day_without_clock(
                    db, day, policy, row.business_line
                )
                row.source = "rollover"
                if policy.session_clock:
                    row.uncovered_units = row.lop_units = 4 if row.status == "absent" else 0
        elif row.check_out is not None or row.system_check_out is not None:
            clock.apply_clock_result(row, policy)
            if policy.session_clock:
                await clock.recalculate_late_penalties(db, request.staff_profile_id, day)
        elif policy.session_clock and day < today:
            row.uncovered_units = row.lop_units = (2 - row.leave_units) * 2


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
        row = clock.new_day(
            *key,
            policy,
            "present",
            "correction",
            calendar_status=await clock.day_without_clock(
                db, request.start_day, policy, request.business_line
            )
            if policy.session_clock
            else None,
            business_line=request.business_line,
        )
        db.add(row)
        request.correction_before = None
    else:
        if row.business_line not in (None, request.business_line):
            raise clock.AttendanceError("This date is recorded in another business line.")
        if set(row.adjustments) & {"early_exit", "late_waiver", "holiday_work"}:
            raise clock.AttendanceError(
                "Reverse the approved regularization before changing punches."
            )
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
    if policy.session_clock and row.business_line is None:
        row.business_line = request.business_line
    row.correction_request_id, row.source = request.id, "correction"
    clock.apply_clock_result(row, policy)
    if policy.session_clock:
        await clock.recalculate_late_penalties(db, request.staff_profile_id, row.day)


async def _undo_correction(db: AsyncSession, request: AttendanceRequest, now: datetime) -> None:
    row = await db.get(AttendanceDay, (request.staff_profile_id, request.start_day))
    if row is None or row.correction_request_id != request.id:
        raise clock.AttendanceError("This correction no longer owns the attendance record.")
    if set(row.adjustments) & {"early_exit", "late_waiver", "holiday_work"}:
        raise clock.AttendanceError("Reverse the approved regularization before changing punches.")
    before = request.correction_before
    policy = await db.get(AttendancePolicy, row.policy_version)
    if not before:
        row.check_in, row.check_out, row.worked_minutes, row.late = None, None, 0, False
        row.status = (
            "on_leave"
            if row.leave_units
            else row.calendar_status
            or await clock.day_without_clock(db, row.day, policy, row.business_line)
        )
        row.source = "leave" if row.leave_units else "rollover"
        if policy.session_clock:
            row.morning_covered = row.afternoon_covered = None
            row.early_exit = False
            row.uncovered_units = 4 if row.status == "absent" else 0
    else:
        row.check_in = datetime.fromisoformat(before["check_in"]) if before["check_in"] else None
        row.check_out = datetime.fromisoformat(before["check_out"]) if before["check_out"] else None
        row.status, row.source = before["status"], before["source"]
        row.worked_minutes, row.late = before["worked_minutes"], before["late"]
        if row.status == "checked_in" and (
            now >= clock.midnight_after(row.day) or await clock.open_day(db, row.staff_profile_id)
        ):
            await clock.close_expired_day(db, row, policy)
        if row.check_out is not None or row.system_check_out is not None:
            clock.apply_clock_result(row, policy)
    row.correction_request_id = None
    if policy.session_clock:
        await clock.recalculate_late_penalties(db, request.staff_profile_id, row.day)


def _decision_entry(actor: CurrentUser, status: str, note: str, now: datetime, *, stage: str):
    return {
        "status": status,
        "actor_id": str(actor.id),
        "actor_role": actor.role,
        "at": now.isoformat(),
        "note": note,
        "stage": stage,
    }


async def _check_two_stage(
    db: AsyncSession,
    actor: CurrentUser,
    target: StaffProfile,
    request: AttendanceRequest,
    values: AttendanceDecisionInput,
    now: datetime,
) -> bool:
    """Return true for a recorded recommendation. The final decision is separate."""
    eligible = await _reviewers(db, target, business_line=request.business_line)
    last_final = max(
        (index for index, step in enumerate(request.decisions) if step.get("stage") == "decision"),
        default=-1,
    )
    recommendation = next(
        (
            step
            for step in reversed(request.decisions[last_final + 1 :])
            if step.get("stage") == "recommendation" and UUID(step["actor_id"]) in eligible
        ),
        None,
    )
    if values.stage == "recommendation":
        if actor.id not in eligible:
            raise clock.AttendanceNotFound("Attendance request not found.")
        expected_stage = (
            (request.status == "approved")
            if values.status == "cancelled"
            else (request.status == "pending")
        )
        if not expected_stage or recommendation:
            raise clock.AttendanceError("This request is not awaiting a recommendation.")
        request.decisions = [
            *request.decisions,
            _decision_entry(actor, values.status, values.note, now, stage="recommendation"),
        ]
        await clock.audit(db, actor, "recommend_request", entity_id=request.id)
        notify(
            db,
            (await _admins(db)) - {actor.id},
            "Attendance recommendation ready",
            "An attendance request is ready for a final decision.",
            "/dashboard/attendance-management",
        )
        return True
    if actor.role != StaffRole.ADMIN:
        raise clock.AttendanceForbidden("A platform Admin must give the final decision.")
    if recommendation is None:
        raise clock.AttendanceError("An eligible reviewer must recommend a decision first.")
    if (request.status == "approved") != (values.status == "cancelled") or (
        (recommendation["status"] == "cancelled") != (values.status == "cancelled")
    ):
        raise clock.AttendanceError("This decision does not match the request's current stage.")
    if recommendation["actor_id"] == str(actor.id):
        raise clock.AttendanceForbidden("A different Admin must give the final decision.")
    return False


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
        await db.execute(select(func.pg_advisory_xact_lock_shared(ATTENDANCE_POLICY_LOCK)))
        await clock.ensure_period_open(db, request.start_day, request.end_day)
        before = request.status
        if values is None:
            if request.requester_id != actor.id:
                raise clock.AttendanceNotFound("Attendance request not found.")
            if before == "cancelled":
                return request
            if before != "pending" and not (
                not request.two_stage
                and before == "approved"
                and request.kind == "leave"
                and request.start_day > today
            ):
                raise clock.AttendanceError("This request can no longer be cancelled here.")
            status, note = "cancelled", "Cancelled by requester."
        else:
            if actor.id in (request.requester_id, target.auth_user_uuid):
                raise clock.AttendanceForbidden("You cannot decide your own attendance request.")
            if request.two_stage:
                if len(request.decisions) != values.expected_decisions:
                    raise clock.AttendanceError("The request changed. Reload it and try again.")
                if await _check_two_stage(db, actor, target, request, values, now):
                    await db.commit()
                    return request
            elif values.stage == "recommendation":
                raise clock.AttendanceError("This request follows the earlier approval policy.")
            elif reviewer.role == StaffRole.SUB_ADMIN:
                if not await clock.managers_for(
                    db,
                    target,
                    reviewer.id,
                    business_line=request.business_line,
                    include_direct=False,
                ):
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
            elif request.kind == "adjustment":
                await attendance_adjustments.undo(db, request, now)
            else:
                await _undo_correction(db, request, now)
        if status == "approved":
            if request.certificate_required and not await attendance_certificates.has_certificate(
                db, request.id, now
            ):
                raise clock.AttendanceError(
                    "A current medical certificate is required before approving this leave."
                )
            clock.require_employment_days(
                await db.get(AttendanceEmployment, target.id), request.start_day, request.end_day
            )
            if request.kind == "leave":
                await _apply_leave(db, request)
            elif request.kind == "adjustment":
                await attendance_adjustments.apply(db, request)
            else:
                await _apply_correction(db, request, now)
        request.status = status
        request.decisions = [
            *request.decisions,
            _decision_entry(actor, status, note, now, stage="decision"),
        ]
        await clock.audit(
            db,
            actor,
            "decide_request",
            entity_id=request.id,
            detail={"before": before, "after": status, "kind": request.kind},
        )
        recipients = (
            await _reviewers(db, target, business_line=request.business_line)
            if values is None
            else {target.auth_user_uuid}
        )
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
