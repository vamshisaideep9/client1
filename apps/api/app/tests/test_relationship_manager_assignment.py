"""Client feedback round 3, slice 2: one Relationship Manager per Agent.

- ``PUT /admin/agents/{agent_id}/relationship-manager`` (Main Admin only)
  makes one Sub Admin the Agent's only Relationship Manager, moving the Agent
  out of every other RM grant, or removes them all. No Sub Admin is signed
  out by a change to Agent lists only; other grant changes still sign out.
- The bulk editor (``PUT /admin/staff-access/{id}/dashboard``) applies the
  same move when it adds an Agent another RM already has.
- Inactive, pending and suspended Agents are not offered or newly
  assignable, and a grant must cover the Agent's line.
- ``GET /relationships/{agent_id}/leads`` is read-only, scoped to the
  assigned Agent and carries no contact details; other RMs read nothing.
- The Agent home and the Admin Agent queue show the Relationship Manager.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.audit_log import AuditAction, AuditLog
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.loan import LoanType
from app.models.profile import AgentApplication, AgentProfile, ProfileStatus, SubmissionStatus
from app.models.user import User, UserStatus
from app.services.sub_admin_access import line_matches
from app.tests.test_admin_hierarchy_api import (
    _headers,
    _primary_admin,
    _staff_token,
    _sub_admin,
    _user_id,
)
from app.tests.test_agent_api import _agent_token
from conftest import full_registration, unique_mobile

pytestmark = pytest.mark.asyncio


def _session():
    import app.db.session as session_mod

    return session_mod.AsyncSessionLocal()


async def _agent(
    client: AsyncClient,
    line: str = "loans",
    *,
    status: ProfileStatus = ProfileStatus.ACTIVE,
    first_name: str | None = None,
    with_application: bool = False,
) -> AgentProfile:
    _, mobile = await full_registration(client)
    user_id = await _user_id(mobile)
    async with _session() as db:
        user = await db.get(User, user_id)
        if first_name:
            user.first_name = first_name
        application_id = None
        if with_application:
            application = AgentApplication(
                applicant_auth_user_uuid=user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                mobile=mobile,
                business_line=line if line != "both" else "loans",
                status=SubmissionStatus.APPROVED,
            )
            db.add(application)
            await db.flush()
            application_id = application.id
        agent = AgentProfile(
            auth_user_uuid=user_id,
            agent_code=f"RM{uuid.uuid4().hex[:10]}",
            business_line=line,
            status=status,
            application_uuid=application_id,
        )
        db.add(agent)
        await db.commit()
        return agent


async def _rm(
    client: AsyncClient,
    main_token: str,
    *,
    lines: tuple[str, ...] = ("loans",),
    agents: dict[str, list[str]] | None = None,
    extra: list[dict] | None = None,
) -> dict:
    """A Sub Admin with an active Relationship Manager grant per line."""
    _, user_id, staff_id, _ = await _sub_admin(client)
    grants = [
        {
            "assignment": "relationship_manager",
            "business_line": line,
            "actions": ["view", "follow_up"],
            "agent_profile_ids": (agents or {}).get(line, []),
        }
        for line in lines
    ] + (extra or [])
    response = await client.put(
        f"/api/v1/admin/staff-access/{staff_id}/dashboard",
        headers=_headers(main_token),
        json={"expected_version": 0, "status": "active", "grants": grants},
    )
    assert response.status_code == 200, response.text
    async with _session() as db:
        user = await db.get(User, user_id)
        version = user.session_version
    return {
        "staff_id": staff_id,
        "user_id": user_id,
        "token": _staff_token(
            user_id=user_id, profile_id=staff_id, role="sub_admin", session_version=version
        ),
        "session_version": version,
    }


async def _session_version(user_id: uuid.UUID) -> int:
    async with _session() as db:
        return (await db.get(User, user_id)).session_version


async def _assign(client: AsyncClient, token: str, agent_id, staff_id) -> object:
    return await client.put(
        f"/api/v1/admin/agents/{agent_id}/relationship-manager",
        headers=_headers(token),
        json={"sub_admin_profile_id": str(staff_id) if staff_id else None},
    )


async def _listed(client: AsyncClient, rm: dict) -> list[str]:
    response = await client.get("/api/v1/relationships", headers=_headers(rm["token"]))
    assert response.status_code == 200, response.text
    return [agent["id"] for agent in response.json()]


async def test_assigning_moves_the_agent_and_keeps_sessions(client: AsyncClient) -> None:
    main, _, _ = await _primary_admin(client)
    agent = await _agent(client, first_name="Moving")
    first = await _rm(client, main, agents={"loans": [str(agent.id)]})
    second = await _rm(client, main)
    assert await _listed(client, first) == [str(agent.id)]

    response = await _assign(client, main, agent.id, second["staff_id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_profile_id"] == str(agent.id)
    assert body["relationship_manager"]["staff_profile_id"] == str(second["staff_id"])

    # The Agent moved; both Sub Admins keep their sessions (same tokens work).
    assert await _listed(client, first) == []
    assert await _listed(client, second) == [str(agent.id)]
    assert await _session_version(first["user_id"]) == first["session_version"]
    assert await _session_version(second["user_id"]) == second["session_version"]

    # Both access rows were audited as Agent-list changes.
    async with _session() as db:
        changes = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.SUB_ADMIN_ACCESS_UPDATED,
                    AuditLog.entity_uuid.in_([first["staff_id"], second["staff_id"]]),
                    AuditLog.detail["change"].astext == "relationship_agents",
                )
            )
        ).all()
    assert {row.entity_uuid for row in changes} == {first["staff_id"], second["staff_id"]}

    # Removing the Relationship Manager empties every list.
    response = await _assign(client, main, agent.id, None)
    assert response.status_code == 200, response.text
    assert response.json()["relationship_manager"] is None
    assert await _listed(client, second) == []


async def test_bulk_editor_adding_an_agent_moves_it_too(client: AsyncClient) -> None:
    main, _, _ = await _primary_admin(client)
    agent = await _agent(client)
    first = await _rm(client, main, agents={"loans": [str(agent.id)]})
    second = await _rm(client, main)
    url = f"/api/v1/admin/staff-access/{second['staff_id']}/dashboard"
    grant = {
        "assignment": "relationship_manager",
        "business_line": "loans",
        "actions": ["view", "follow_up"],
        "agent_profile_ids": [str(agent.id)],
    }
    response = await client.put(
        url,
        headers=_headers(main),
        json={"expected_version": 1, "status": "active", "grants": [grant]},
    )
    assert response.status_code == 200, response.text
    assert await _listed(client, first) == []
    assert await _listed(client, second) == [str(agent.id)]
    # An Agent-list-only edit does not sign the edited Sub Admin out...
    assert await _session_version(second["user_id"]) == second["session_version"]

    # ...but changing the grant's actions still does.
    grant["actions"] = ["view"]
    response = await client.put(
        url,
        headers=_headers(main),
        json={"expected_version": 2, "status": "active", "grants": [grant]},
    )
    assert response.status_code == 200, response.text
    assert await _session_version(second["user_id"]) == second["session_version"] + 1


def test_a_grant_on_either_line_reaches_a_dual_line_agent() -> None:
    # Agent profiles are single-line today (ck_agent_profiles_business_line_
    # operational); the rule is kept so a future dual-line Agent still matches.
    assert line_matches("loans", "loans")
    assert not line_matches("loans", "real_estate")
    assert line_matches("both", "loans") and line_matches("both", "real_estate")


async def test_picker_and_assignment_skip_inactive_agents_and_other_lines(
    client: AsyncClient,
) -> None:
    main, _, _ = await _primary_admin(client)
    marker = uuid.uuid4().hex[:8]
    active = await _agent(client, "loans", first_name=f"Live{marker}")
    other_line = await _agent(client, "real_estate", first_name=f"Land{marker}")
    inactive = await _agent(
        client, "loans", status=ProfileStatus.INACTIVE, first_name=f"Idle{marker}"
    )
    pending = await _agent(
        client, "loans", status=ProfileStatus.PENDING, first_name=f"Wait{marker}"
    )
    suspended = await _agent(client, "loans", first_name=f"Held{marker}")
    async with _session() as db:
        user = await db.get(User, suspended.auth_user_uuid)
        user.status = UserStatus.SUSPENDED
        await db.commit()
    loans_rm = await _rm(client, main)

    # The picker offers only active Agents on the requested line.
    response = await client.get(
        "/api/v1/relationships/options",
        params={"line": "loans", "query": marker},
        headers=_headers(main),
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [str(active.id)]

    # Inactive, pending and suspended Agents cannot be newly assigned...
    for agent in (inactive, pending, suspended):
        assert (await _assign(client, main, agent.id, loans_rm["staff_id"])).status_code == 409
    grant = {
        "assignment": "relationship_manager",
        "business_line": "loans",
        "actions": ["view"],
        "agent_profile_ids": [str(inactive.id)],
    }
    _, _, staff_id, _ = await _sub_admin(client)
    response = await client.put(
        f"/api/v1/admin/staff-access/{staff_id}/dashboard",
        headers=_headers(main),
        json={"expected_version": 0, "status": "active", "grants": [grant]},
    )
    assert response.status_code == 422, response.text

    # ...and a Relationship Manager without a grant on the Agent's line is refused.
    response = await _assign(client, main, other_line.id, loans_rm["staff_id"])
    assert response.status_code == 422, response.text

    # An Agent already listed keeps its place when it becomes inactive, so the
    # editor can still save; the selected-Agent lookup names it.
    assert (await _assign(client, main, active.id, loans_rm["staff_id"])).status_code == 200
    async with _session() as db:
        profile = await db.get(AgentProfile, active.id)
        profile.status = ProfileStatus.INACTIVE
        await db.commit()
    grant["agent_profile_ids"] = [str(active.id)]
    grant["actions"] = ["view", "follow_up"]
    response = await client.put(
        f"/api/v1/admin/staff-access/{loans_rm['staff_id']}/dashboard",
        headers=_headers(main),
        json={"expected_version": 2, "status": "active", "grants": [grant]},
    )
    assert response.status_code == 200, response.text
    response = await client.get(
        "/api/v1/relationships/options/selected",
        params=[("ids", str(active.id)), ("ids", str(inactive.id))],
        headers=_headers(main),
    )
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()} == {str(active.id), str(inactive.id)}


async def test_only_the_main_admin_assigns(client: AsyncClient) -> None:
    from app.tests.test_admin_hierarchy_api import _additional_admin

    main, _, _ = await _primary_admin(client)
    agent = await _agent(client)
    rm = await _rm(client, main)
    other_admin, _, _ = await _additional_admin(client)
    for token in (other_admin, rm["token"]):
        assert (await _assign(client, token, agent.id, rm["staff_id"])).status_code == 403
        options = await client.get(
            f"/api/v1/admin/agents/{agent.id}/relationship-manager/options",
            headers=_headers(token),
        )
        assert options.status_code == 403
    assert (await _assign(client, main, uuid.uuid4(), rm["staff_id"])).status_code == 404

    options = await client.get(
        f"/api/v1/admin/agents/{agent.id}/relationship-manager/options", headers=_headers(main)
    )
    assert options.status_code == 200, options.text
    mine = [row for row in options.json() if row["staff_profile_id"] == str(rm["staff_id"])]
    assert mine == [
        {
            "staff_profile_id": str(rm["staff_id"]),
            "name": mine[0]["name"],
            "staff_code": mine[0]["staff_code"],
            "business_line": "loans",
            "agent_count": 0,
            "current": False,
        }
    ]


async def _agent_leads(agent: AgentProfile, product: LoanType) -> list[Lead]:
    async with _session() as db:
        leads = [
            Lead(
                name="Private Person",
                mobile=unique_mobile(),
                business_line="loans",
                status=LeadStatus.NEW,
                origin=LeadOrigin.AGENT,
                origin_agent_profile_uuid=agent.id,
                product_id=product.id,
                requirement={"notes": "secret note"},
            )
            for _ in range(2)
        ]
        db.add_all(leads)
        await db.commit()
        return leads


async def test_rm_reads_the_assigned_agents_leads_only(client: AsyncClient) -> None:
    main, _, _ = await _primary_admin(client)
    agent = await _agent(client)
    other_agent = await _agent(client)
    async with _session() as db:
        product = LoanType(name=f"rm-{uuid.uuid4().hex[:8]}", label="RM Home Loan")
        db.add(product)
        await db.commit()
    leads = await _agent_leads(agent, product)
    await _agent_leads(other_agent, product)
    rm = await _rm(client, main, agents={"loans": [str(agent.id)]})
    other_rm = await _rm(client, main, agents={"loans": [str(other_agent.id)]})

    response = await client.get(
        f"/api/v1/relationships/{agent.id}/leads", headers=_headers(rm["token"])
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    rows = response.json()
    assert {row["id"] for row in rows} == {str(lead.id) for lead in leads}
    assert {row["product_label"] for row in rows} == {"RM Home Loan"}
    assert all(row["lead_ref"].startswith("LD-") for row in rows)
    assert set(rows[0]) == {
        "id",
        "lead_ref",
        "business_line",
        "status",
        "product_label",
        "created_at",
        "updated_at",
    }
    for secret in ("Private Person", "secret note", leads[0].mobile):
        assert secret not in response.text

    # Another RM, and a Sub Admin without the RM grant, read nothing.
    denied = await client.get(
        f"/api/v1/relationships/{agent.id}/leads", headers=_headers(other_rm["token"])
    )
    assert denied.status_code == 404
    media = await _rm(
        client,
        main,
        lines=(),
        extra=[{"assignment": "media_sub_admin", "business_line": "loans", "actions": ["view"]}],
    )
    no_grant = await client.get(
        f"/api/v1/relationships/{agent.id}/leads", headers=_headers(media["token"])
    )
    assert no_grant.status_code == 403


async def test_agent_home_and_admin_queue_show_the_relationship_manager(
    client: AsyncClient,
) -> None:
    main, _, _ = await _primary_admin(client)
    agent = await _agent(client, with_application=True)
    rm = await _rm(client, main)
    assert (await _assign(client, main, agent.id, rm["staff_id"])).status_code == 200
    async with _session() as db:
        rm_user = await db.get(User, rm["user_id"])
        expected_name = " ".join(p for p in (rm_user.first_name, rm_user.last_name) if p)

    home = await client.get(
        "/api/v1/agent/home",
        headers=_headers(_agent_token(str(agent.auth_user_uuid), str(agent.id))),
    )
    assert home.status_code == 200, home.text
    manager = home.json()["relationship_manager"]
    assert manager["name"] == expected_name
    assert manager["staff_code"].startswith("SUB")
    assert "staff_profile_id" not in manager

    queue = await client.get("/api/v1/admin/agents?status=approved", headers=_headers(main))
    assert queue.status_code == 200, queue.text
    (row,) = [
        item for item in queue.json()["applications"] if item["id"] == str(agent.application_uuid)
    ]
    assert row["agent_profile_id"] == str(agent.id)
    assert row["relationship_manager"]["staff_profile_id"] == str(rm["staff_id"])

    # Another Agent's home never shows this Relationship Manager.
    stranger = await _agent(client)
    other_home = await client.get(
        "/api/v1/agent/home",
        headers=_headers(_agent_token(str(stranger.auth_user_uuid), str(stranger.id))),
    )
    assert other_home.json()["relationship_manager"] is None
