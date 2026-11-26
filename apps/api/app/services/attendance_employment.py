"""Platform Admin configuration for a staff member's attendance assignment."""

from uuid import UUID

from sqlalchemy import or_, select

import app.db.session as db_session
from app.core.deps import CurrentUser
from app.models.attendance import (
    AttendanceDay,
    AttendanceEmployment,
    AttendanceRequest,
    AttendanceRolloverState,
)
from app.models.profile import (
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
    SubAdminAccessProfile,
)
from app.models.user import User, UserStatus
from app.schemas.attendance import AttendanceEmploymentInput
from app.services import attendance as clock
from app.services.sub_admin_access import read_access

_REVIEWERS = (
    select(
        StaffProfile.id,
        StaffProfile.staff_code,
        User.first_name,
        User.last_name,
        SubAdminAccessProfile,
    )
    .join(User, User.id == StaffProfile.auth_user_uuid)
    .outerjoin(SubAdminAccessProfile, SubAdminAccessProfile.staff_profile_uuid == StaffProfile.id)
    .where(
        StaffProfile.role == StaffRole.SUB_ADMIN,
        StaffProfile.scope == ProfileScope.PLATFORM,
        StaffProfile.status == ProfileStatus.ACTIVE,
        User.status == UserStatus.ACTIVE,
    )
)


def _can_review(access: SubAdminAccessProfile | None, business_line: str) -> bool:
    return access is None or business_line in read_access(access).lines_for(
        "team_manager", "review"
    )


async def reviewers(business_line: str) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            _REVIEWERS.order_by(User.first_name, User.last_name, StaffProfile.id)
        )
        return [
            {
                "staff_profile_id": profile_id,
                "staff_code": code,
                "name": f"{first} {last}",
                "role": "sub_admin",
            }
            for profile_id, code, first, last, access in rows
            if _can_review(access, business_line)
        ]


async def save(
    actor: CurrentUser, staff_id: UUID, values: AttendanceEmploymentInput
) -> AttendanceEmployment:
    async with db_session.AsyncSessionLocal() as db:
        await clock.lock_actor(db, actor)
        target = await clock.lock_staff(db, staff_id)
        current = await db.get(AttendanceEmployment, target.id)
        version = current.version if current else 0
        if version != values.expected_version:
            raise clock.AttendanceError(
                "The attendance assignment changed. Reload it and try again."
            )
        if target.business_line not in (None, "both", values.business_line):
            raise clock.AttendanceInvalid("Choose a calendar in this staff member's business line.")
        if values.reviewer_id is not None:
            reviewer = (
                await db.execute(
                    _REVIEWERS.where(
                        StaffProfile.id == values.reviewer_id,
                        StaffProfile.id != target.id,
                    )
                )
            ).one_or_none()
            if reviewer is None or not _can_review(reviewer[-1], values.business_line):
                raise clock.AttendanceInvalid(
                    "Choose an active Sub Admin with review access in this line."
                )

        today = clock.work_date(clock.utc_now())
        day_conflicts = [AttendanceDay.day < values.start_day]
        request_conflicts = [AttendanceRequest.start_day < values.start_day]
        if values.end_day is not None:
            day_conflicts.append(AttendanceDay.day > values.end_day)
            request_conflicts.append(AttendanceRequest.end_day > values.end_day)
        if current is None or current.business_line != values.business_line:
            day_conflicts.append(
                (AttendanceDay.day >= today)
                & AttendanceDay.business_line.is_distinct_from(values.business_line)
            )
            request_conflicts.append(
                (AttendanceRequest.end_day >= today)
                & AttendanceRequest.business_line.is_distinct_from(values.business_line)
            )
        has_day = await db.scalar(
            select(AttendanceDay.day)
            .where(AttendanceDay.staff_profile_id == target.id, or_(*day_conflicts))
            .limit(1)
        )
        has_request = await db.scalar(
            select(AttendanceRequest.id)
            .where(
                AttendanceRequest.staff_profile_id == target.id,
                AttendanceRequest.status.in_(("pending", "approved")),
                or_(*request_conflicts),
            )
            .limit(1)
        )
        if has_day is not None or has_request is not None:
            raise clock.AttendanceError(
                "The assignment conflicts with saved attendance or an active request."
            )

        previous_start = current.start_day if current else clock.work_date(target.created_at)
        if values.start_day < previous_start:
            cursor = await db.get(AttendanceRolloverState, target.id)
            if cursor is not None and cursor.through_day >= values.start_day:
                cursor.through_day = values.start_day - clock.DAY
        if current is None:
            current = AttendanceEmployment(staff_profile_id=target.id)
            db.add(current)
        for field, value in values.model_dump(exclude={"expected_version"}).items():
            setattr(current, field, value)
        current.version = version + 1
        await clock.audit(
            db,
            actor,
            "configure_employment",
            entity_id=target.id,
            detail={
                "version": current.version,
                **values.model_dump(mode="json", exclude={"expected_version"}),
            },
        )
        await db.commit()
        return current
