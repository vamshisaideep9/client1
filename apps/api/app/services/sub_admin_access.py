"""Sub Admin access changes share the provisioning and session transaction."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.models.profile import (
    AgentProfile,
    ProfileStatus,
    StaffFeatureGrant,
    StaffProfile,
    StaffRole,
    SubAdminAccessProfile,
)
from app.models.staff_team import StaffTeam
from app.models.user import User, UserStatus
from app.schemas.sub_admin_access import (
    GrantList,
    SubAdminAccess,
    SubAdminAccessHistory,
    SubAdminAccessUpdate,
)
from app.services.audit_log import record


class SubAdminAccessTargetMissing(Exception):
    pass


class SubAdminAccessConflict(Exception):
    pass


class InvalidSubAdminAgents(Exception):
    pass


class SubAdminTeamsNeedReassignment(Exception):
    pass


async def access_history(db: AsyncSession, staff_id: UUID) -> list[SubAdminAccessHistory]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == AuditAction.SUB_ADMIN_ACCESS_UPDATED,
            AuditLog.entity_type == "staff_profile",
            AuditLog.entity_uuid == staff_id,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(25)
    )
    return [
        SubAdminAccessHistory(
            actor_uuid=row.actor_uuid,
            created_at=row.created_at,
            before=(row.detail or {}).get("before")
            if "version" in (row.detail or {}).get("before", {})
            else None,
            after=(row.detail or {})["after"],
        )
        for row in rows
    ]


async def validate_assigned_agents(db: AsyncSession, grants: GrantList) -> None:
    expected = {
        (profile_id, grant.business_line)
        for grant in grants
        for profile_id in grant.agent_profile_ids
    }
    if not expected:
        return
    rows = await db.execute(
        select(AgentProfile.id, AgentProfile.business_line)
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .where(
            AgentProfile.id.in_({profile_id for profile_id, _ in expected}),
            User.status != UserStatus.SOFT_DELETED,
        )
    )
    if not expected.issubset(set(rows.all())):
        raise InvalidSubAdminAgents


def read_access(row: SubAdminAccessProfile | None) -> SubAdminAccess | None:
    if row is None:
        return None
    return SubAdminAccess.model_validate(row, from_attributes=True)


async def update_access(
    db: AsyncSession,
    *,
    staff_id: UUID,
    actor_id: UUID,
    update: SubAdminAccessUpdate,
) -> None:
    # Use the parent lock even for the first transition from legacy access,
    # when there is no access row to lock.
    staff = await db.get(StaffProfile, staff_id, with_for_update=True)
    if staff is None or staff.role != StaffRole.SUB_ADMIN:
        raise SubAdminAccessTargetMissing
    user = await db.get(User, staff.auth_user_uuid, with_for_update=True)
    if user is None or user.status == UserStatus.SOFT_DELETED:
        raise SubAdminAccessTargetMissing
    row = await db.get(SubAdminAccessProfile, staff_id)
    before = read_access(row)
    if (before.version if before else 0) != update.expected_version:
        raise SubAdminAccessConflict
    if before is not None and before.status == update.status and before.grants == update.grants:
        return
    if (
        update.status == "inactive"
        and await db.scalar(
            select(StaffTeam.id)
            .where(
                StaffTeam.manager_staff_profile_uuid == staff_id, StaffTeam.archived_at.is_(None)
            )
            .limit(1)
        )
        is not None
    ):
        raise SubAdminTeamsNeedReassignment
    if update.status == "active" and staff.status != ProfileStatus.ACTIVE:
        existing = await db.scalar(
            select(StaffProfile.id).where(
                StaffProfile.auth_user_uuid == user.id,
                StaffProfile.id != staff.id,
                StaffProfile.status == ProfileStatus.ACTIVE,
            )
        )
        if existing is not None or user.status == UserStatus.SUSPENDED:
            raise SubAdminAccessConflict
    await validate_assigned_agents(db, update.grants)
    if row is None:
        row = SubAdminAccessProfile(staff_profile_uuid=staff_id, version=0)
        db.add(row)
    row.status = update.status
    row.grants = [grant.model_dump(mode="json") for grant in update.grants]
    row.version += 1
    staff.status = ProfileStatus.ACTIVE if update.status == "active" else ProfileStatus.INACTIVE
    await db.execute(
        delete(StaffFeatureGrant).where(StaffFeatureGrant.staff_profile_uuid == staff_id)
    )
    from app.services.auth_service import _revoke_all_refresh_tokens

    user.session_version += 1
    await _revoke_all_refresh_tokens(db, user.id, commit=False)
    await record(
        db,
        action=AuditAction.SUB_ADMIN_ACCESS_UPDATED,
        entity_type="staff_profile",
        entity_uuid=staff_id,
        actor_uuid=actor_id,
        actor_role="admin",
        detail={
            "before": before.model_dump(mode="json") if before else {"status": "legacy"},
            "after": read_access(row).model_dump(mode="json"),
        },
    )
    await db.commit()
