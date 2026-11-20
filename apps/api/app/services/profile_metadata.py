"""Small, request-scoped projections; no staff directory or bypass session."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import bindparam, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan import LoanType
from app.models.profile import AgentProfile, ProfileStatus, StaffProfile
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User, UserStatus
from app.schemas.profile_metadata import ProfileTeamRead, RoleProfileRead, TaskStaffRead

_TASK_NAMES = text("SELECT * FROM task_staff_names(:ids)").bindparams(
    bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))
)


async def task_staff_for_ids(
    db: AsyncSession, task_ids: Iterable[UUID]
) -> dict[UUID, TaskStaffRead]:
    ids = list(set(task_ids))
    if not ids:
        return {}
    return {
        row.task_uuid: TaskStaffRead.model_validate(dict(row._mapping))
        for row in await db.execute(_TASK_NAMES, {"ids": ids})
    }


async def role_profiles_for_users(
    db: AsyncSession, user_ids: Iterable[UUID], *, own: bool = False
) -> dict[UUID, list[RoleProfileRead]]:
    """RLS controls visible staff/Agents/teams; Admin pages use bounded queries."""
    ids = list(set(user_ids))
    result: dict[UUID, list[RoleProfileRead]] = defaultdict(list)
    if not ids:
        return result
    staff_rows = list(
        await db.execute(
            select(StaffProfile, LoanType.label)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .outerjoin(LoanType, LoanType.id == StaffProfile.loan_specialty_id)
            .where(
                StaffProfile.auth_user_uuid.in_(ids),
                StaffProfile.status == ProfileStatus.ACTIVE,
                User.status != UserStatus.SOFT_DELETED,
            )
            .order_by(StaffProfile.created_at, StaffProfile.id)
        )
    )
    teams: dict[UUID, list[ProfileTeamRead]] = defaultdict(list)
    profile_ids = [profile.id for profile, _ in staff_rows]
    if profile_ids:
        if own:
            rows = await db.execute(text("SELECT * FROM own_profile_teams()"))
        else:
            rows = await db.execute(
                select(
                    StaffProfile.id.label("staff_profile_uuid"),
                    StaffTeam.business_line,
                    StaffTeam.name,
                )
                .join(
                    StaffTeam,
                    or_(
                        StaffTeam.manager_staff_profile_uuid == StaffProfile.id,
                        select(StaffTeamMember.team_uuid)
                        .where(
                            StaffTeamMember.team_uuid == StaffTeam.id,
                            StaffTeamMember.staff_profile_uuid == StaffProfile.id,
                            StaffTeamMember.business_line == StaffTeam.business_line,
                        )
                        .exists(),
                    ),
                )
                .where(StaffProfile.id.in_(profile_ids), StaffTeam.archived_at.is_(None))
                .order_by(StaffTeam.business_line, StaffTeam.name)
            )
        for row in rows:
            teams[row.staff_profile_uuid].append(
                ProfileTeamRead(business_line=row.business_line, name=row.name)
            )
    for profile, label in staff_rows:
        result[profile.auth_user_uuid].append(
            RoleProfileRead(
                profile_uuid=profile.id,
                role=profile.role.value,
                code=profile.staff_code,
                business_line=profile.business_line,
                teams=teams[profile.id],
                loan_specialty_id=profile.loan_specialty_id,
                loan_specialty_label=label,
            )
        )
    for profile in await db.scalars(
        select(AgentProfile)
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .where(
            AgentProfile.auth_user_uuid.in_(ids),
            AgentProfile.status == ProfileStatus.ACTIVE,
            User.status != UserStatus.SOFT_DELETED,
        )
        .order_by(AgentProfile.business_line, AgentProfile.id)
    ):
        result[profile.auth_user_uuid].append(
            RoleProfileRead(
                profile_uuid=profile.id,
                role="agent",
                code=profile.agent_code,
                business_line=profile.business_line,
            )
        )
    return result
