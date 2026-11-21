"""Minimal Agent activity for explicitly assigned Relationship Managers."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_assignment, require_platform_admin
from app.db.session import get_db
from app.models.profile import AgentProfile
from app.models.user import User, UserStatus
from app.schemas.sub_admin_access import (
    AccessLine,
    RelationshipActivity,
    RelationshipActivityInput,
    RelationshipAgent,
)
from app.services.admin import is_primary_admin

router = APIRouter()
Reader = Annotated[CurrentUser, Depends(require_assignment("relationship_manager", "view"))]
Writer = Annotated[CurrentUser, Depends(require_assignment("relationship_manager", "follow_up"))]
Admin = Annotated[CurrentUser, Depends(require_platform_admin)]
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/options", response_model=list[RelationshipAgent])
async def relationship_options(
    user: Admin,
    db: DB,
    response: Response,
    line: AccessLine,
    query: Annotated[str, Query(min_length=2, max_length=100)],
):
    if not await is_primary_admin(
        db, auth_user_uuid=user.id, staff_profile_uuid=user.staff_profile_uuid
    ):
        raise HTTPException(403, detail="Only the Main Admin can assign Agents.")
    response.headers["Cache-Control"] = "private, no-store"
    name = func.concat_ws(" ", User.first_name, User.last_name)
    rows = await db.execute(
        select(
            AgentProfile.id,
            name.label("name"),
            AgentProfile.agent_code,
            AgentProfile.business_line,
            AgentProfile.status,
            AgentProfile.kyc_status,
            AgentProfile.approved_at,
        )
        .join(User, User.id == AgentProfile.auth_user_uuid)
        .where(
            AgentProfile.business_line == line,
            User.status != UserStatus.SOFT_DELETED,
            or_(
                name.icontains(query, autoescape=True),
                AgentProfile.agent_code.icontains(query, autoescape=True),
            ),
        )
        .order_by(AgentProfile.agent_code)
        .limit(25)
    )
    return rows.mappings().all()


@router.get("", response_model=list[RelationshipAgent])
async def list_relationship_agents(_: Reader, db: DB, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    rows = await db.execute(text("SELECT * FROM public.relationship_agents()"))
    return rows.mappings().all()


async def _require_agent(db: DB, agent_id: UUID, action: str) -> None:
    allowed = await db.scalar(
        text("SELECT public.relationship_can_access(:agent_id, :action)"),
        {"agent_id": agent_id, "action": action},
    )
    if not allowed:
        raise HTTPException(404, detail="Assigned Agent not found.")


@router.get("/{agent_id}/activity", response_model=list[RelationshipActivity])
async def list_relationship_activity(agent_id: UUID, _: Reader, db: DB, response: Response):
    await _require_agent(db, agent_id, "view")
    response.headers["Cache-Control"] = "private, no-store"
    rows = await db.execute(
        text("""
            SELECT id, kind, note, created_at
            FROM relationship_activity WHERE agent_profile_id = :agent_id
            ORDER BY created_at DESC, id DESC LIMIT 100
        """),
        {"agent_id": agent_id},
    )
    return rows.mappings().all()


@router.post("/{agent_id}/activity", response_model=RelationshipActivity, status_code=201)
async def add_relationship_activity(
    agent_id: UUID, payload: RelationshipActivityInput, user: Writer, db: DB
):
    await _require_agent(db, agent_id, "follow_up")
    result = await db.execute(
        text("""
            INSERT INTO relationship_activity (id, agent_profile_id, staff_profile_id, kind, note)
            VALUES (:id, :agent_id, :staff_id, :kind, :note)
            RETURNING id, kind, note, created_at
        """),
        {
            "id": uuid4(),
            "agent_id": agent_id,
            "staff_id": user.staff_profile_uuid,
            **payload.model_dump(),
        },
    )
    item = RelationshipActivity.model_validate(result.mappings().one())
    await db.commit()
    return item
