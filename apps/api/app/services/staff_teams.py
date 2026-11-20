"""Admin management of Sub Admin–led teams (CS-019).

Every read runs on the platform Admin's own request session (platform bypass
in ``staff_teams_select``). Every write is additionally limited to the Main
Admin by the router *and* by the ``staff_teams_*`` / ``staff_team_members_*``
RLS policies, because a team grants its manager read and reassign reach over
the members' client work.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction
from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User
from app.schemas.staff_teams import (
    StaffTeamCreate,
    StaffTeamRead,
    StaffTeamUpdate,
    TeamEligibleResponse,
    TeamMemberRead,
    TeamPersonRead,
)
from app.services.audit_log import record as record_audit


class TeamNotFound(Exception):
    pass


class TeamArchived(Exception):
    pass


class InvalidTeamManager(Exception):
    pass


class ManagerAlreadyHasTeam(Exception):
    pass


class InvalidTeamMember(Exception):
    pass


class MemberAlreadyInTeam(Exception):
    pass


class TeamMemberNotFound(Exception):
    pass


def _person(profile: StaffProfile, first_name: str, last_name: str) -> TeamPersonRead:
    return TeamPersonRead(
        staff_profile_uuid=profile.id,
        first_name=first_name,
        last_name=last_name,
        staff_code=profile.staff_code,
        loan_specialty_id=profile.loan_specialty_id,
        status=profile.status.value,
        business_line=profile.business_line,
    )


_ROSTER_NAMES = text(
    "SELECT staff_profile_uuid, first_name, last_name FROM team_roster_names(:ids)"
).bindparams(bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))))


async def people_by_profile(
    db: AsyncSession, profile_ids: Iterable[UUID]
) -> dict[UUID, TeamPersonRead]:
    """Names for staff profiles the caller may read.

    A platform Admin (and anyone for their own account) reads names straight
    from auth_users under RLS. A manager has no auth_users access to members,
    whose rows carry the password hash, email and income fields; their names
    come from ``team_roster_names``, which returns names only and only for
    members the caller reaches.
    """
    ids = list(set(profile_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(StaffProfile, User.first_name, User.last_name)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(StaffProfile.id.in_(ids))
    )
    people = {profile.id: _person(profile, first, last) for profile, first, last in rows.all()}
    missing = [profile_id for profile_id in ids if profile_id not in people]
    if not missing:
        return await _with_specialty_labels(db, people)
    names = {
        row.staff_profile_uuid: (row.first_name, row.last_name)
        for row in await db.execute(_ROSTER_NAMES, {"ids": missing})
    }
    if names:
        for profile in await db.scalars(
            select(StaffProfile).where(StaffProfile.id.in_(list(names)))
        ):
            people[profile.id] = _person(profile, *names[profile.id])
    return await _with_specialty_labels(db, people)


async def _with_specialty_labels(
    db: AsyncSession, people: dict[UUID, TeamPersonRead]
) -> dict[UUID, TeamPersonRead]:
    from app.models.loan import LoanType

    ids = {person.loan_specialty_id for person in people.values() if person.loan_specialty_id}
    if ids:
        labels = dict(
            (
                await db.execute(select(LoanType.id, LoanType.label).where(LoanType.id.in_(ids)))
            ).all()
        )
        for person in people.values():
            person.loan_specialty_label = labels.get(person.loan_specialty_id)
    return people


async def build_team_reads(db: AsyncSession, teams: list[StaffTeam]) -> list[StaffTeamRead]:
    if not teams:
        return []
    memberships = list(
        await db.scalars(
            select(StaffTeamMember)
            .where(StaffTeamMember.team_uuid.in_([team.id for team in teams]))
            .order_by(StaffTeamMember.created_at)
        )
    )
    people = await people_by_profile(
        db,
        [team.manager_staff_profile_uuid for team in teams]
        + [member.staff_profile_uuid for member in memberships],
    )
    reads: list[StaffTeamRead] = []
    for team in teams:
        members = [
            TeamMemberRead(
                **people[member.staff_profile_uuid].model_dump(), added_at=member.created_at
            )
            for member in memberships
            if member.team_uuid == team.id and member.staff_profile_uuid in people
        ]
        members.sort(key=lambda person: (person.first_name.lower(), person.last_name.lower()))
        reads.append(
            StaffTeamRead(
                id=team.id,
                name=team.name,
                business_line=team.business_line,
                member_role=team.member_role,
                manager=people[team.manager_staff_profile_uuid],
                members=members,
                archived_at=team.archived_at,
                created_at=team.created_at,
                updated_at=team.updated_at,
            )
        )
    return reads


async def list_teams(db: AsyncSession, *, include_archived: bool) -> list[StaffTeamRead]:
    stmt = select(StaffTeam).order_by(StaffTeam.business_line, StaffTeam.name)
    if not include_archived:
        stmt = stmt.where(StaffTeam.archived_at.is_(None))
    return await build_team_reads(db, list(await db.scalars(stmt)))


async def _active_manager(db: AsyncSession, staff_profile_uuid: UUID) -> StaffProfile:
    profile = await db.get(StaffProfile, staff_profile_uuid)
    if (
        profile is None
        or profile.role != StaffRole.SUB_ADMIN
        or profile.scope != ProfileScope.PLATFORM
        or profile.status != ProfileStatus.ACTIVE
    ):
        raise InvalidTeamManager
    return profile


async def _manager_has_live_team(
    db: AsyncSession, manager_uuid: UUID, business_line: str, *, excluding: UUID | None = None
) -> bool:
    stmt = select(StaffTeam.id).where(
        StaffTeam.manager_staff_profile_uuid == manager_uuid,
        StaffTeam.business_line == business_line,
        StaffTeam.archived_at.is_(None),
    )
    if excluding is not None:
        stmt = stmt.where(StaffTeam.id != excluding)
    return (await db.scalar(stmt.limit(1))) is not None


async def _locked_live_team(db: AsyncSession, team_id: UUID) -> StaffTeam:
    team = await db.get(StaffTeam, team_id, with_for_update=True)
    if team is None:
        raise TeamNotFound
    if team.archived_at is not None:
        raise TeamArchived
    return team


async def _read_one(db: AsyncSession, team: StaffTeam) -> StaffTeamRead:
    return (await build_team_reads(db, [team]))[0]


async def create_team(
    db: AsyncSession, payload: StaffTeamCreate, *, actor_uuid: UUID, actor_role: str
) -> StaffTeamRead:
    await _active_manager(db, payload.manager_staff_profile_uuid)
    if await _manager_has_live_team(db, payload.manager_staff_profile_uuid, payload.business_line):
        raise ManagerAlreadyHasTeam
    team = StaffTeam(
        name=payload.name,
        business_line=payload.business_line,
        member_role=payload.member_role,
        manager_staff_profile_uuid=payload.manager_staff_profile_uuid,
        created_by_auth_user_uuid=actor_uuid,
    )
    db.add(team)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ManagerAlreadyHasTeam from exc
    await record_audit(
        db,
        action=AuditAction.STAFF_TEAM_CREATED,
        entity_type="staff_team",
        entity_uuid=team.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=team.business_line,
        detail={
            "member_role": team.member_role,
            "manager_staff_profile_uuid": str(team.manager_staff_profile_uuid),
        },
    )
    await db.commit()
    await db.refresh(team)
    return await _read_one(db, team)


async def update_team(
    db: AsyncSession,
    team_id: UUID,
    payload: StaffTeamUpdate,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> StaffTeamRead:
    team = await _locked_live_team(db, team_id)
    changes: dict[str, str | None] = {}

    if payload.name is not None and payload.name != team.name:
        changes["name"] = payload.name
        team.name = payload.name

    new_manager = payload.manager_staff_profile_uuid
    if new_manager is not None and new_manager != team.manager_staff_profile_uuid:
        await _active_manager(db, new_manager)
        if await _manager_has_live_team(db, new_manager, team.business_line, excluding=team.id):
            raise ManagerAlreadyHasTeam
        changes["previous_manager_staff_profile_uuid"] = str(team.manager_staff_profile_uuid)
        changes["manager_staff_profile_uuid"] = str(new_manager)
        team.manager_staff_profile_uuid = new_manager

    removed: list[str] = []
    if payload.archive:
        # Archiving frees every member to join another team in this line and
        # ends the manager's reach at once.
        removed = [
            str(member_id)
            for member_id in await db.scalars(
                select(StaffTeamMember.staff_profile_uuid).where(
                    StaffTeamMember.team_uuid == team.id
                )
            )
        ]
        await db.execute(delete(StaffTeamMember).where(StaffTeamMember.team_uuid == team.id))
        team.archived_at = datetime.now(UTC)

    if changes and not payload.archive and new_manager in (None, team.manager_staff_profile_uuid):
        # A live team may not keep a deactivated manager (staff_teams_update
        # WITH CHECK); say so instead of failing at the database.
        await _active_manager(db, team.manager_staff_profile_uuid)

    if not changes and not payload.archive:
        return await _read_one(db, team)

    team.updated_at = datetime.now(UTC)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ManagerAlreadyHasTeam from exc
    await record_audit(
        db,
        action=(
            AuditAction.STAFF_TEAM_ARCHIVED if payload.archive else AuditAction.STAFF_TEAM_UPDATED
        ),
        entity_type="staff_team",
        entity_uuid=team.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=team.business_line,
        detail={**changes, **({"removed_members": removed} if payload.archive else {})},
    )
    await db.commit()
    await db.refresh(team)
    return await _read_one(db, team)


async def add_member(
    db: AsyncSession,
    team_id: UUID,
    staff_profile_uuid: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> StaffTeamRead:
    team = await _locked_live_team(db, team_id)
    member = await db.get(StaffProfile, staff_profile_uuid)
    if (
        member is None
        or member.role.value != team.member_role
        or member.scope != ProfileScope.LINE
        or member.status != ProfileStatus.ACTIVE
        or member.business_line not in (team.business_line, "both")
    ):
        raise InvalidTeamMember
    taken = await db.scalar(
        select(StaffTeamMember.team_uuid).where(
            StaffTeamMember.staff_profile_uuid == staff_profile_uuid,
            StaffTeamMember.business_line == team.business_line,
        )
    )
    if taken is not None:
        raise MemberAlreadyInTeam
    db.add(
        StaffTeamMember(
            team_uuid=team.id,
            staff_profile_uuid=staff_profile_uuid,
            business_line=team.business_line,
            added_by_auth_user_uuid=actor_uuid,
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise MemberAlreadyInTeam from exc
    await record_audit(
        db,
        action=AuditAction.STAFF_TEAM_MEMBER_ADDED,
        entity_type="staff_team",
        entity_uuid=team.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=team.business_line,
        detail={"staff_profile_uuid": str(staff_profile_uuid)},
    )
    team.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(team)
    return await _read_one(db, team)


async def remove_member(
    db: AsyncSession,
    team_id: UUID,
    staff_profile_uuid: UUID,
    *,
    actor_uuid: UUID,
    actor_role: str,
) -> StaffTeamRead:
    team = await _locked_live_team(db, team_id)
    result = await db.execute(
        delete(StaffTeamMember).where(
            StaffTeamMember.team_uuid == team.id,
            StaffTeamMember.staff_profile_uuid == staff_profile_uuid,
        )
    )
    if result.rowcount == 0:
        raise TeamMemberNotFound
    await record_audit(
        db,
        action=AuditAction.STAFF_TEAM_MEMBER_REMOVED,
        entity_type="staff_team",
        entity_uuid=team.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=team.business_line,
        detail={"staff_profile_uuid": str(staff_profile_uuid)},
    )
    team.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(team)
    return await _read_one(db, team)


async def eligible_people(
    db: AsyncSession, *, business_line: str, member_role: str
) -> TeamEligibleResponse:
    busy_managers = select(StaffTeam.manager_staff_profile_uuid).where(
        StaffTeam.business_line == business_line, StaffTeam.archived_at.is_(None)
    )
    managers = await db.execute(
        select(StaffProfile, User.first_name, User.last_name)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            StaffProfile.role == StaffRole.SUB_ADMIN,
            StaffProfile.scope == ProfileScope.PLATFORM,
            StaffProfile.status == ProfileStatus.ACTIVE,
            StaffProfile.id.not_in(busy_managers),
        )
        .order_by(User.first_name, User.last_name)
    )
    teamed = select(StaffTeamMember.staff_profile_uuid).where(
        StaffTeamMember.business_line == business_line
    )
    members = await db.execute(
        select(StaffProfile, User.first_name, User.last_name)
        .join(User, User.id == StaffProfile.auth_user_uuid)
        .where(
            StaffProfile.role == StaffRole(member_role),
            StaffProfile.scope == ProfileScope.LINE,
            StaffProfile.status == ProfileStatus.ACTIVE,
            StaffProfile.business_line.in_((business_line, "both")),
            StaffProfile.id.not_in(teamed),
        )
        .order_by(User.first_name, User.last_name)
        .limit(500)
    )
    return TeamEligibleResponse(
        managers=[_person(profile, first, last) for profile, first, last in managers.all()],
        members=[_person(profile, first, last) for profile, first, last in members.all()],
    )
