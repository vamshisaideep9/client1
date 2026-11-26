"""Sub Admin access changes share the provisioning and session transaction."""

from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.lead_reference import format_lead_ref
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
    RelationshipLead,
    RelationshipManagerOption,
    RelationshipManagerRead,
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


def line_matches(agent_line: str, grant_line: str) -> bool:
    """A grant on either line reaches a dual-line (``both``) Agent."""
    return agent_line == grant_line or agent_line == "both"


def relationship_agent_ids(grants: GrantList) -> set[UUID]:
    return {
        profile_id
        for grant in grants
        if grant.assignment == "relationship_manager"
        for profile_id in grant.agent_profile_ids
    }


def _without_agents(grants: GrantList) -> list[dict]:
    return [grant.model_dump(mode="json", exclude={"agent_profile_ids"}) for grant in grants]


async def validate_assigned_agents(
    db: AsyncSession, grants: GrantList, *, previous: GrantList | None = None
) -> None:
    """Every listed Agent exists on a matching line and is not soft-deleted;
    Agents newly added (absent from ``previous``) must also be active, with an
    account that is not suspended. An Agent already assigned keeps its place
    when its account later becomes inactive, so the editor can still save."""
    expected = {
        (profile_id, grant.business_line)
        for grant in grants
        for profile_id in grant.agent_profile_ids
    }
    if not expected:
        return
    rows = (
        await db.execute(
            select(AgentProfile.id, AgentProfile.business_line, AgentProfile.status, User.status)
            .join(User, User.id == AgentProfile.auth_user_uuid)
            .where(
                AgentProfile.id.in_({profile_id for profile_id, _ in expected}),
                User.status != UserStatus.SOFT_DELETED,
            )
        )
    ).all()
    found = {row[0]: row for row in rows}
    kept = relationship_agent_ids(previous or [])
    for profile_id, grant_line in expected:
        row = found.get(profile_id)
        if row is None or not line_matches(str(row[1]), grant_line):
            raise InvalidSubAdminAgents
        if profile_id not in kept and (
            row[2] != ProfileStatus.ACTIVE or row[3] == UserStatus.SUSPENDED
        ):
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
    await validate_assigned_agents(
        db, update.grants, previous=before.grants if before is not None else None
    )
    # One Relationship Manager per Agent: Agents added here leave any other
    # Relationship Manager first, under row locks.
    added = relationship_agent_ids(update.grants) - relationship_agent_ids(
        before.grants if before is not None else []
    )
    await _release_agents(db, added, keep_staff_id=staff_id, actor_id=actor_id)
    # Assigned Agents are read live (relationship_can_access), so changing
    # only the Agent lists keeps the Sub Admin signed in.
    agents_only = (
        before is not None
        and before.status == update.status
        and _without_agents(before.grants) == _without_agents(update.grants)
    )
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
    if not agents_only:
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


# ---------------------------------------------------------------------------
# One Relationship Manager per Agent (client feedback round 3, 2026-11-26)
# ---------------------------------------------------------------------------

RELATIONSHIP_AGENT_CAP = 100


class RelationshipAgentMissing(Exception):
    pass


class RelationshipManagerUnavailable(Exception):
    """The chosen Sub Admin has no active Relationship Manager grant that can
    reach the Agent's line."""


class RelationshipAgentInactive(Exception):
    pass


class RelationshipManagerFull(Exception):
    pass


def _holds_agent(agent_id: UUID):
    return SubAdminAccessProfile.grants.contains(
        [{"assignment": "relationship_manager", "agent_profile_ids": [str(agent_id)]}]
    )


async def _lock_staff(db: AsyncSession, staff_ids: set[UUID]) -> None:
    """Lock the parent staff rows in a stable order (the same parent lock
    ``update_access`` takes) before their access rows change."""
    for staff_id in sorted(staff_ids, key=str):
        await db.get(StaffProfile, staff_id, with_for_update=True)


async def _write_access(
    db: AsyncSession,
    row: SubAdminAccessProfile,
    before: SubAdminAccess,
    grants: list[dict],
    *,
    actor_id: UUID,
    agent_id: UUID | None,
) -> None:
    row.grants = grants
    row.version += 1
    await db.flush()
    await record(
        db,
        action=AuditAction.SUB_ADMIN_ACCESS_UPDATED,
        entity_type="staff_profile",
        entity_uuid=row.staff_profile_uuid,
        actor_uuid=actor_id,
        actor_role="admin",
        detail={
            "before": before.model_dump(mode="json"),
            "after": read_access(row).model_dump(mode="json"),
            "change": "relationship_agents",
            **({"agent_profile_id": str(agent_id)} if agent_id is not None else {}),
        },
    )


async def _release_agents(
    db: AsyncSession, agent_ids: set[UUID], *, keep_staff_id: UUID | None, actor_id: UUID
) -> None:
    """Remove each Agent from every other Sub Admin's Relationship Manager
    grants. Session versions are untouched: only Agent lists change."""
    if not agent_ids:
        return
    holders: set[UUID] = set()
    for agent_id in sorted(agent_ids, key=str):
        # The Agent row lock serialises concurrent assignments of one Agent
        # (the Agent-side PUT takes it first), so no Agent ends up listed
        # under two Relationship Managers.
        await db.get(AgentProfile, agent_id, with_for_update=True)
        holders.update(
            await db.scalars(
                select(SubAdminAccessProfile.staff_profile_uuid).where(_holds_agent(agent_id))
            )
        )
    holders.discard(keep_staff_id)
    if not holders:
        return
    await _lock_staff(db, holders)
    released = {str(agent_id) for agent_id in agent_ids}
    for staff_id in sorted(holders, key=str):
        row = await db.get(SubAdminAccessProfile, staff_id, populate_existing=True)
        before = read_access(row)
        if row is None or before is None:
            continue
        grants = [
            {
                **grant,
                "agent_profile_ids": [
                    value for value in grant.get("agent_profile_ids", []) if value not in released
                ],
            }
            if grant.get("assignment") == "relationship_manager"
            else grant
            for grant in row.grants
        ]
        if grants != row.grants:
            await _write_access(db, row, before, grants, actor_id=actor_id, agent_id=None)


async def _manager_read(db: AsyncSession, staff: StaffProfile) -> RelationshipManagerRead:
    user = await db.get(User, staff.auth_user_uuid)
    name = " ".join(part for part in (user.first_name, user.last_name) if part) if user else ""
    return RelationshipManagerRead(
        staff_profile_id=staff.id, name=name or None, staff_code=staff.staff_code
    )


async def assign_relationship_manager(
    db: AsyncSession,
    *,
    agent_id: UUID,
    sub_admin_profile_id: UUID | None,
    actor_id: UUID,
) -> RelationshipManagerRead | None:
    """Make ``sub_admin_profile_id`` the Agent's only Relationship Manager, or
    remove every Relationship Manager when it is None. Main Admin only (the
    route checks; ``sub_admin_access`` RLS also limits updates to the Main
    Admin). Agent-list changes never sign the Sub Admins out. Commits."""
    agent = await db.get(AgentProfile, agent_id, with_for_update=True)
    if agent is None:
        raise RelationshipAgentMissing
    agent_user = await db.get(User, agent.auth_user_uuid)
    if agent_user is None or agent_user.status == UserStatus.SOFT_DELETED:
        raise RelationshipAgentMissing

    target: StaffProfile | None = None
    if sub_admin_profile_id is not None:
        if agent.status != ProfileStatus.ACTIVE or agent_user.status == UserStatus.SUSPENDED:
            raise RelationshipAgentInactive
        target = await db.get(StaffProfile, sub_admin_profile_id, with_for_update=True)
        target_user = await db.get(User, target.auth_user_uuid) if target is not None else None
        if (
            target is None
            or target.role != StaffRole.SUB_ADMIN
            or target.status != ProfileStatus.ACTIVE
            or target_user is None
            or target_user.status in (UserStatus.SOFT_DELETED, UserStatus.SUSPENDED)
        ):
            raise RelationshipManagerUnavailable

    await _release_agents(db, {agent_id}, keep_staff_id=sub_admin_profile_id, actor_id=actor_id)
    if target is None:
        await db.commit()
        return None

    row = await db.get(SubAdminAccessProfile, target.id, populate_existing=True)
    access = read_access(row)
    if row is None or access is None or access.status != "active":
        raise RelationshipManagerUnavailable
    candidates = [
        index
        for index, grant in enumerate(access.grants)
        if grant.assignment == "relationship_manager"
        and line_matches(str(agent.business_line), grant.business_line)
    ]
    if not candidates:
        raise RelationshipManagerUnavailable
    # The grant that already lists the Agent wins, else the first one that
    # matches its line (a dual-line Agent goes to the Loans grant first).
    holding = [i for i in candidates if agent_id in access.grants[i].agent_profile_ids]
    for extra in holding[1:]:
        access.grants[extra].agent_profile_ids.remove(agent_id)
    grant = access.grants[holding[0] if holding else candidates[0]]
    if agent_id not in grant.agent_profile_ids:
        if len(grant.agent_profile_ids) >= RELATIONSHIP_AGENT_CAP:
            raise RelationshipManagerFull
        grant.agent_profile_ids.append(agent_id)
        grant.agent_profile_ids.sort()
    grants = [item.model_dump(mode="json") for item in access.grants]
    if grants != row.grants:
        await _write_access(db, row, read_access(row), grants, actor_id=actor_id, agent_id=agent_id)
    await db.commit()
    return await _manager_read(db, target)


async def relationship_manager_options(
    db: AsyncSession, agent_id: UUID
) -> list[RelationshipManagerOption]:
    """Active Sub Admins whose Relationship Manager grant can take this Agent.
    Runs on the Main Admin's session, to which ``sub_admin_access`` is
    readable."""
    agent = await db.get(AgentProfile, agent_id)
    if agent is None:
        raise RelationshipAgentMissing
    rows = (
        await db.execute(
            select(SubAdminAccessProfile, StaffProfile, User)
            .join(StaffProfile, StaffProfile.id == SubAdminAccessProfile.staff_profile_uuid)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(
                SubAdminAccessProfile.status == "active",
                StaffProfile.role == StaffRole.SUB_ADMIN,
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status.notin_((UserStatus.SOFT_DELETED, UserStatus.SUSPENDED)),
            )
        )
    ).all()
    options: list[RelationshipManagerOption] = []
    for row, staff, user in rows:
        access = read_access(row)
        for grant in access.grants if access else []:
            if grant.assignment != "relationship_manager" or not line_matches(
                str(agent.business_line), grant.business_line
            ):
                continue
            name = " ".join(part for part in (user.first_name, user.last_name) if part)
            options.append(
                RelationshipManagerOption(
                    staff_profile_id=staff.id,
                    name=name or None,
                    staff_code=staff.staff_code,
                    business_line=grant.business_line,
                    agent_count=len(grant.agent_profile_ids),
                    current=agent_id in grant.agent_profile_ids,
                )
            )
    return sorted(options, key=lambda option: (option.name or "", option.staff_code))


async def relationship_managers_for(
    db: AsyncSession, agent_ids: list[UUID]
) -> dict[UUID, RelationshipManagerRead]:
    """Each Agent's Relationship Manager, through the confined
    ``agent_relationship_managers`` function: a platform Admin may ask about
    any Agent, an Agent only about their own profile."""
    if not agent_ids:
        return {}
    rows = (
        await db.execute(
            text("SELECT * FROM public.agent_relationship_managers(CAST(:ids AS uuid[]))"),
            {"ids": list(agent_ids)},
        )
    ).all()
    return {
        row.agent_profile_id: RelationshipManagerRead(
            staff_profile_id=row.staff_profile_id, name=row.name, staff_code=row.staff_code
        )
        for row in rows
    }


async def relationship_leads(db: AsyncSession, agent_id: UUID) -> list[RelationshipLead]:
    """The assigned Agent's leads on the lines the caller's grant reaches,
    read-only and without contact details (``relationship_agent_leads``)."""
    rows = (
        await db.execute(
            text("SELECT * FROM public.relationship_agent_leads(:agent_id)"),
            {"agent_id": agent_id},
        )
    ).all()
    return [
        RelationshipLead(
            id=row.id,
            lead_ref=format_lead_ref(row.lead_number),
            business_line=row.business_line,
            status="expired" if row.agent_expired else row.status,
            product_label=row.product_label,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
