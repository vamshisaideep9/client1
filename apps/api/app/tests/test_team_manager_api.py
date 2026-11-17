"""/api/v1/manager and the team-manager RLS reach (CS-019, migration e4f6a8c0b2d5).

API: a Sub Admin manager sees only their own live teams, members' analytics,
members' work and audited lead detail; non-members, other teams, other lines
and line staff are refused; reassignment stays inside the team, only for open
work, and is audited.

RLS (direct, as ``api_user``): reach exists only for the manager's own active
Sub Admin identity and only over members' rows in the team's line; it ends on
member removal, team archive and Sub Admin deactivation; it cannot be forged
with another account's auth uuid; an UPDATE cannot move work to a non-member.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token
from app.tests.test_admin_hierarchy_api import _headers, _sub_admin
from app.tests.test_staff_teams_api import audit_actions, seed_line_staff, seed_team
from conftest import unique_mobile


async def _seed_lead(
    telecaller: uuid.UUID,
    *,
    business_line: str = "loans",
    status: str = "working",
    calls: tuple[str, ...] = (),
    name: str = "Team Lead",
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity

    async with session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            name=name,
            mobile=unique_mobile(),
            business_line=business_line,
            status=LeadStatus(status),
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=telecaller,
        )
        db.add(lead)
        await db.flush()
        for disposition in calls:
            db.add(
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=telecaller,
                    business_line=business_line,
                    disposition=CallDisposition(disposition),
                    interest_level=InterestLevel.WARM if disposition == "connected" else None,
                    notes="Client asked for a callback after salary credit.",
                )
            )
        await db.commit()
        return lead.id


async def _seed_task(
    employee: uuid.UUID, raised_by: uuid.UUID, *, status: str = "in_progress"
) -> tuple[uuid.UUID, uuid.UUID]:
    import app.db.session as session_mod
    from app.models.task import Task, TaskStatus, TaskType

    lead_id = await _seed_lead(raised_by, name="Field Client")
    async with session_mod.AsyncSessionLocal() as db:
        task = Task(
            raised_by_staff_profile_uuid=raised_by,
            assigned_employee_profile_uuid=employee,
            business_line="loans",
            task_type=TaskType.DOCUMENT_COLLECTION,
            lead_uuid=lead_id,
            status=TaskStatus(status),
        )
        db.add(task)
        await db.commit()
        return task.id, lead_id


async def _assignee(lead_id: uuid.UUID) -> uuid.UUID | None:
    import app.db.session as session_mod
    from app.models.lead import Lead

    async with session_mod.AsyncSessionLocal() as db:
        return (await db.get(Lead, lead_id)).assigned_telecaller_profile_uuid


async def _set_profile_status(profile_id: uuid.UUID, status: str) -> None:
    import app.db.session as session_mod
    from app.models.profile import ProfileStatus, StaffProfile

    async with session_mod.AsyncSessionLocal() as db:
        (await db.get(StaffProfile, profile_id)).status = ProfileStatus(status)
        await db.commit()


async def _as_manager(
    auth_uuid: uuid.UUID, profile: uuid.UUID, sql: str, params: dict[str, Any] | None = None
) -> list[tuple]:
    """Run SQL as api_user with a Sub Admin's real RLS context."""
    engine = create_async_engine(
        settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432"),
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(
                text(
                    "SELECT set_config('app.auth_user_uuid', :auth, true),"
                    "set_config('app.role', 'sub_admin', true),"
                    "set_config('app.business_line', '', true),"
                    "set_config('app.client_profile_uuid', '', true),"
                    "set_config('app.agent_profile_uuid', '', true),"
                    "set_config('app.staff_profile_uuid', :profile, true),"
                    "set_config('app.platform_scope', 'true', true)"
                ),
                {"auth": str(auth_uuid), "profile": str(profile)},
            )
            result = await conn.execute(text(sql), params or {})
            return list(result.fetchall()) if result.returns_rows else [(result.rowcount,)]
    finally:
        await engine.dispose()


async def _telecaller_team(client: AsyncClient):
    token, manager_auth, manager, _ = await _sub_admin(client)
    _, asha = await seed_line_staff("telecaller", first_name="Asha")
    _, bala = await seed_line_staff("telecaller", first_name="Bala")
    _, outsider = await seed_line_staff("telecaller", first_name="Out")
    team_id = await seed_team(manager, [asha, bala])
    return token, manager_auth, manager, team_id, asha, bala, outsider


@pytest.mark.asyncio
async def test_manager_lists_only_own_live_teams(client: AsyncClient) -> None:
    token, _, _, team_id, _, _, _ = await _telecaller_team(client)
    other_token, _, other_manager, _ = await _sub_admin(client)
    await seed_team(other_manager, [])

    mine = await client.get("/api/v1/manager/teams", headers=_headers(token))
    assert mine.status_code == 200
    assert mine.headers["cache-control"] == "private, no-store"
    assert [t["id"] for t in mine.json()["teams"]] == [str(team_id)]
    assert [m["first_name"] for m in mine.json()["teams"][0]["members"]] == ["Asha", "Bala"]

    no_team_token, *_ = await _sub_admin(client)
    empty = await client.get("/api/v1/manager/teams", headers=_headers(no_team_token))
    assert empty.json() == {"teams": []}
    foreign = await client.get(
        f"/api/v1/manager/teams/{team_id}/overview", headers=_headers(other_token)
    )
    assert foreign.status_code == 404

    tele_auth, tele = await seed_line_staff("telecaller")
    tele_token = create_access_token(
        {
            "sub": str(tele_auth),
            "role": "telecaller",
            "business_line": "loans",
            "platform_scope": "false",
            "staff_profile_uuid": str(tele),
        }
    )
    assert (
        await client.get("/api/v1/manager/teams", headers=_headers(tele_token))
    ).status_code == 403


@pytest.mark.asyncio
async def test_overview_and_member_views_cover_members_only(client: AsyncClient) -> None:
    token, _, _, team_id, asha, bala, outsider = await _telecaller_team(client)
    asha_lead = await _seed_lead(asha, calls=("connected", "busy", "connected"))
    await _seed_lead(bala, calls=("no_answer",))
    await _seed_lead(outsider, calls=("connected",) * 5)

    overview = await client.get(
        f"/api/v1/manager/teams/{team_id}/overview?days=7", headers=_headers(token)
    )
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["range_days"] == 7
    totals = {k["key"]: k["value"] for k in body["totals"]}
    assert totals["calls"] == 4
    assert totals["active_leads"] == 2
    per_member = {
        m["member"]["first_name"]: {k["key"]: k["value"] for k in m["kpis"]}
        for m in body["members"]
    }
    assert per_member["Asha"]["calls"] == 3
    assert per_member["Bala"]["connect_rate"] == 0.0
    # Rates are averaged over members that have one: (66.7 + 0) / 2.
    assert totals["connect_rate"] == pytest.approx(33.35, abs=0.1)

    analytics = await client.get(
        f"/api/v1/manager/teams/{team_id}/members/{asha}/analytics", headers=_headers(token)
    )
    assert analytics.status_code == 200
    assert analytics.json()["trend"]["description"] == "Every call they logged, by outcome."

    work = await client.get(
        f"/api/v1/manager/teams/{team_id}/members/{asha}/work", headers=_headers(token)
    )
    assert work.status_code == 200
    assert work.json()["kind"] == "leads"
    [row] = work.json()["leads"]
    assert row["id"] == str(asha_lead)
    assert row["last_call"]["disposition"] == "connected"

    for path in ("analytics", "work"):
        refused = await client.get(
            f"/api/v1/manager/teams/{team_id}/members/{outsider}/{path}", headers=_headers(token)
        )
        assert refused.status_code == 404


@pytest.mark.asyncio
async def test_lead_detail_is_audited_and_limited_to_team_leads(client: AsyncClient) -> None:
    token, _, _, team_id, asha, _, outsider = await _telecaller_team(client)
    lead_id = await _seed_lead(asha, calls=("connected", "busy"))
    outsider_lead = await _seed_lead(outsider, calls=("connected",))

    detail = await client.get(
        f"/api/v1/manager/teams/{team_id}/leads/{lead_id}", headers=_headers(token)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["assigned_to"]["first_name"] == "Asha"
    assert len(body["activities"]) == 2
    assert body["activities"][0]["notes"].startswith("Client asked")
    assert await audit_actions(lead_id) == ["team_lead_viewed"]

    hidden = await client.get(
        f"/api/v1/manager/teams/{team_id}/leads/{outsider_lead}", headers=_headers(token)
    )
    assert hidden.status_code == 404
    assert await audit_actions(outsider_lead) == []


@pytest.mark.asyncio
async def test_reassign_lead_inside_team_only(client: AsyncClient) -> None:
    token, _, _, team_id, asha, bala, outsider = await _telecaller_team(client)
    lead_id = await _seed_lead(asha, status="working")
    closed = await _seed_lead(asha, status="closed")
    base = f"/api/v1/manager/teams/{team_id}/leads"

    to_outsider = await client.post(
        f"{base}/{lead_id}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(outsider)},
    )
    assert to_outsider.status_code == 422
    to_self = await client.post(
        f"{base}/{lead_id}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(asha)},
    )
    assert to_self.status_code == 422
    finished = await client.post(
        f"{base}/{closed}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(bala)},
    )
    assert finished.status_code == 409

    moved = await client.post(
        f"{base}/{lead_id}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(bala)},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json() == {
        "id": str(lead_id),
        "assigned_staff_profile_uuid": str(bala),
        "status": "assigned",
    }
    assert await _assignee(lead_id) == bala
    assert await audit_actions(lead_id) == ["team_lead_reassigned"]

    await _set_profile_status(asha, "suspended")
    back_to_suspended = await client.post(
        f"{base}/{lead_id}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(asha)},
    )
    assert back_to_suspended.status_code == 422


@pytest.mark.asyncio
async def test_employee_team_tasks_and_reassignment(client: AsyncClient) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, raiser = await seed_line_staff("telecaller")
    _, emp_a = await seed_line_staff("employee", first_name="Chitra")
    _, emp_b = await seed_line_staff("employee", first_name="Dev")
    team_id = await seed_team(manager, [emp_a, emp_b], member_role="employee")
    task_id, _ = await _seed_task(emp_a, raiser, status="in_progress")

    work = await client.get(
        f"/api/v1/manager/teams/{team_id}/members/{emp_a}/work", headers=_headers(token)
    )
    assert work.status_code == 200
    [row] = work.json()["tasks"]
    assert row["id"] == str(task_id)
    assert row["lead_name"] == "Field Client"

    overview = await client.get(
        f"/api/v1/manager/teams/{team_id}/overview", headers=_headers(token)
    )
    assert {k["key"]: k["value"] for k in overview.json()["totals"]}["open_tasks"] == 1

    moved = await client.post(
        f"/api/v1/manager/teams/{team_id}/tasks/{task_id}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(emp_b)},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "assigned"
    assert await audit_actions(task_id) == ["team_task_reassigned"]

    no_leads_here = await client.post(
        f"/api/v1/manager/teams/{team_id}/leads/{uuid.uuid4()}/reassign",
        headers=_headers(token),
        json={"to_staff_profile_uuid": str(emp_b)},
    )
    assert no_leads_here.status_code == 404


@pytest.mark.asyncio
async def test_rls_reach_is_live_line_bound_and_unforgeable(client: AsyncClient) -> None:
    _, manager_auth, manager, _ = await _sub_admin(client)
    _, dual = await seed_line_staff("telecaller", "both")
    _, outsider = await seed_line_staff("telecaller")
    team_id = await seed_team(manager, [dual])
    loans_lead = await _seed_lead(dual, calls=("connected",))
    estate_lead = await _seed_lead(dual, business_line="real_estate", calls=("busy",))
    outsider_lead = await _seed_lead(outsider, calls=("connected",))
    ids = {"ids": [loans_lead, estate_lead, outsider_lead]}
    leads_sql = "SELECT id FROM leads WHERE id = ANY(:ids)"
    calls_sql = "SELECT lead_uuid FROM lead_activities WHERE lead_uuid = ANY(:ids)"

    assert await _as_manager(manager_auth, manager, leads_sql, ids) == [(loans_lead,)]
    assert await _as_manager(manager_auth, manager, calls_sql, ids) == [(loans_lead,)]
    names = await _as_manager(
        manager_auth, manager, "SELECT staff_code FROM staff_profiles WHERE id = :id", {"id": dual}
    )
    assert len(names) == 1
    # Member auth rows (password hash, email, income) stay closed; names come
    # only from the roster function and only for reached members.
    hidden = await _as_manager(
        manager_auth,
        manager,
        "SELECT a.id FROM auth_users a JOIN staff_profiles s ON s.auth_user_uuid = a.id "
        "WHERE s.id = :id",
        {"id": dual},
    )
    assert hidden == []
    roster = await _as_manager(
        manager_auth,
        manager,
        "SELECT staff_profile_uuid, first_name FROM team_roster_names(:ids)",
        {"ids": [dual, outsider]},
    )
    assert roster == [(dual, "Team")]

    # Another account cannot borrow the manager's staff profile id.
    forged = await _as_manager(uuid.uuid4(), manager, leads_sql, ids)
    assert forged == []

    # A manager has no UPDATE policy: a direct write matches nothing.
    for lead_id in (loans_lead, outsider_lead):
        untouched = await _as_manager(
            manager_auth,
            manager,
            "UPDATE leads SET assigned_telecaller_profile_uuid = :to WHERE id = :id",
            {"to": outsider, "id": lead_id},
        )
        assert untouched == [(0,)]
    # The confined function refuses a non-member target and a non-team lead.
    with pytest.raises(DBAPIError, match="not another active member"):
        await _as_manager(
            manager_auth,
            manager,
            "SELECT team_manager_reassign_lead(:id, :to)",
            {"id": loans_lead, "to": outsider},
        )
    with pytest.raises(DBAPIError, match="not in the caller's team"):
        await _as_manager(
            manager_auth,
            manager,
            "SELECT team_manager_reassign_lead(:id, :to)",
            {"id": outsider_lead, "to": dual},
        )
    assert await _assignee(loans_lead) == dual

    # Sub Admin deactivation ends reach at once, reactivation restores it.
    await _set_profile_status(manager, "suspended")
    assert await _as_manager(manager_auth, manager, leads_sql, ids) == []
    await _set_profile_status(manager, "active")
    assert await _as_manager(manager_auth, manager, leads_sql, ids) == [(loans_lead,)]

    # Removing the member ends reach without any token change.
    import app.db.session as session_mod
    from app.models.staff_team import StaffTeamMember

    async with session_mod.AsyncSessionLocal() as db:
        await db.delete(await db.get(StaffTeamMember, (team_id, dual)))
        await db.commit()
    assert await _as_manager(manager_auth, manager, leads_sql, ids) == []


@pytest.mark.asyncio
async def test_archived_team_and_teamless_sub_admin_reach_nothing(client: AsyncClient) -> None:
    _, manager_auth, manager, _ = await _sub_admin(client)
    _, member = await seed_line_staff("telecaller")
    team_id = await seed_team(manager, [member])
    lead_id = await _seed_lead(member)
    sql = "SELECT id FROM leads WHERE id = :id"

    _, other_auth, other_manager, _ = await _sub_admin(client)
    assert await _as_manager(other_auth, other_manager, sql, {"id": lead_id}) == []
    assert await _as_manager(manager_auth, manager, sql, {"id": lead_id}) == [(lead_id,)]

    import app.db.session as session_mod
    from app.models.staff_team import StaffTeam

    async with session_mod.AsyncSessionLocal() as db:
        team = await db.get(StaffTeam, team_id)
        team.archived_at = team.created_at
        await db.commit()
    assert await _as_manager(manager_auth, manager, sql, {"id": lead_id}) == []
