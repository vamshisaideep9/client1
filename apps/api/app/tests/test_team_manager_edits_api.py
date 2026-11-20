"""Manager edits, notes, filters and team analytics (CS-020, migration b2d4f6a8c0e1).

Edits: an open team lead's status, an open team task's due date or
cancellation, and append-only notes, each only inside the caller's own team
and line, through confined functions (direct writes match nothing), audited.
Notes: read by the reaching manager and the assigned member only.
Filters: the team-wide work list carries assignee and lead signals, applies the
Admin's field rules for the member role, and team_lead_signals answers only
managers. Analytics: role filters, a members subset and an aggregated report.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.security import create_access_token
from app.tests.test_admin_hierarchy_api import _headers, _sub_admin
from app.tests.test_staff_teams_api import audit_actions, seed_line_staff, seed_team
from app.tests.test_team_manager_api import (
    _as_manager,
    _seed_lead,
    _seed_task,
    _telecaller_team,
)


def _staff_headers(auth_uuid: uuid.UUID, profile: uuid.UUID, role: str) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(auth_uuid),
            "role": role,
            "business_line": "loans",
            "platform_scope": "false",
            "staff_profile_uuid": str(profile),
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _lead_status(lead_id: uuid.UUID) -> str:
    import app.db.session as session_mod
    from app.models.lead import Lead

    async with session_mod.AsyncSessionLocal() as db:
        return (await db.get(Lead, lead_id)).status.value


async def _task(task_id: uuid.UUID):
    import app.db.session as session_mod
    from app.models.task import Task

    async with session_mod.AsyncSessionLocal() as db:
        return await db.get(Task, task_id)


def _future(hours: int = 48) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_manager_sets_open_team_lead_status_only(client: AsyncClient) -> None:
    token, _, _, team_id, asha, _, outsider = await _telecaller_team(client)
    lead_id = await _seed_lead(asha, status="working")
    closed = await _seed_lead(asha, status="closed")
    outsider_lead = await _seed_lead(outsider)
    base = f"/api/v1/manager/teams/{team_id}/leads"

    done = await client.patch(
        f"{base}/{lead_id}", headers=_headers(token), json={"status": "converted"}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "converted"
    assert await _lead_status(lead_id) == "converted"
    assert await audit_actions(lead_id) == ["team_lead_status_updated"]

    again = await client.patch(
        f"{base}/{lead_id}", headers=_headers(token), json={"status": "closed"}
    )
    assert again.status_code == 409  # no longer open
    assert (
        await client.patch(f"{base}/{closed}", headers=_headers(token), json={"status": "working"})
    ).status_code == 409
    assert (
        await client.patch(
            f"{base}/{outsider_lead}", headers=_headers(token), json={"status": "closed"}
        )
    ).status_code == 404
    bad = await client.patch(f"{base}/{lead_id}", headers=_headers(token), json={"status": "new"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_manager_changes_task_due_date_or_cancels_with_reason(client: AsyncClient) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, raiser = await seed_line_staff("telecaller")
    _, emp = await seed_line_staff("employee", first_name="Chitra")
    team_id = await seed_team(manager, [emp], member_role="employee")
    task_id, _ = await _seed_task(emp, raiser, status="in_progress")
    done_id, _ = await _seed_task(emp, raiser, status="completed")
    base = f"/api/v1/manager/teams/{team_id}/tasks"

    due = _future()
    moved = await client.patch(f"{base}/{task_id}", headers=_headers(token), json={"due_at": due})
    assert moved.status_code == 200, moved.text
    assert (await _task(task_id)).due_at is not None

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert (
        await client.patch(f"{base}/{task_id}", headers=_headers(token), json={"due_at": past})
    ).status_code == 422
    both = await client.patch(
        f"{base}/{task_id}",
        headers=_headers(token),
        json={"due_at": due, "cancel_reason": "Client moved away"},
    )
    assert both.status_code == 422

    cancelled = await client.patch(
        f"{base}/{task_id}", headers=_headers(token), json={"cancel_reason": "Client moved away"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert (await _task(task_id)).status.value == "cancelled"
    detail = await client.get(f"{base}/{task_id}", headers=_headers(token))
    assert detail.status_code == 200
    assert detail.json()["notes"][0]["body"] == "Cancelled: Client moved away"
    assert await audit_actions(task_id) == [
        "team_task_updated",
        "team_task_updated",
        "team_task_viewed",
    ]

    assert (
        await client.patch(
            f"{base}/{done_id}", headers=_headers(token), json={"cancel_reason": "Too late now"}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_notes_reach_the_assigned_member_and_nobody_else(client: AsyncClient) -> None:
    token, _, _, team_id, asha, _, outsider = await _telecaller_team(client)
    lead_id = await _seed_lead(asha)
    base = f"/api/v1/manager/teams/{team_id}/leads/{lead_id}/notes"

    note = await client.post(
        base,
        headers=_headers(token),
        json={"body": "  Call before noon, they prefer Telugu.  ", "follow_up_at": _future()},
    )
    assert note.status_code == 201, note.text
    assert note.json()["body"] == "Call before noon, they prefer Telugu."
    assert note.json()["author_name"]
    assert "team_note_added" in await audit_actions(lead_id)

    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert (
        await client.post(base, headers=_headers(token), json={"body": "x", "follow_up_at": past})
    ).status_code == 422

    # The assigned Telecaller reads it on their own lead page.
    import app.db.session as session_mod
    from app.models.profile import StaffProfile

    async with session_mod.AsyncSessionLocal() as db:
        asha_auth = (await db.get(StaffProfile, asha)).auth_user_uuid
        outsider_auth = (await db.get(StaffProfile, outsider)).auth_user_uuid
    own = await client.get(
        f"/api/v1/telecaller/leads/{lead_id}", headers=_staff_headers(asha_auth, asha, "telecaller")
    )
    assert own.status_code == 200, own.text
    assert [n["body"] for n in own.json()["manager_notes"]] == [
        "Call before noon, they prefer Telugu."
    ]

    # Another Telecaller of the same line cannot read the note row at all.
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

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
                    "set_config('app.role', 'telecaller', true),"
                    "set_config('app.business_line', 'loans', true),"
                    "set_config('app.staff_profile_uuid', :profile, true),"
                    "set_config('app.platform_scope', 'false', true)"
                ),
                {"auth": str(outsider_auth), "profile": str(outsider)},
            )
            rows = await conn.execute(
                text("SELECT id FROM team_work_notes WHERE lead_uuid = :id"), {"id": lead_id}
            )
            assert rows.fetchall() == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_employee_reads_task_notes_and_task_notes_take_no_follow_up(
    client: AsyncClient,
) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, raiser = await seed_line_staff("telecaller")
    emp_auth, emp = await seed_line_staff("employee")
    team_id = await seed_team(manager, [emp], member_role="employee")
    task_id, _ = await _seed_task(emp, raiser, status="assigned")
    base = f"/api/v1/manager/teams/{team_id}/tasks/{task_id}/notes"

    with_follow_up = await client.post(
        base,
        headers=_headers(token),
        json={"body": "Bring the sale deed.", "follow_up_at": _future()},
    )
    assert with_follow_up.status_code == 422
    note = await client.post(base, headers=_headers(token), json={"body": "Bring the sale deed."})
    assert note.status_code == 201

    task = await client.get(
        f"/api/v1/employee/tasks/{task_id}", headers=_staff_headers(emp_auth, emp, "employee")
    )
    assert task.status_code == 200, task.text
    assert [n["body"] for n in task.json()["manager_notes"]] == ["Bring the sale deed."]
    listed = await client.get(
        "/api/v1/employee/tasks", headers=_staff_headers(emp_auth, emp, "employee")
    )
    assert all("manager_notes" not in row for row in listed.json())


@pytest.mark.asyncio
async def test_writes_only_through_confined_functions(client: AsyncClient) -> None:
    _, manager_auth, manager, _ = await _sub_admin(client)
    _, member = await seed_line_staff("telecaller")
    _, outsider = await seed_line_staff("telecaller")
    await seed_team(manager, [member])
    lead_id = await _seed_lead(member)
    outsider_lead = await _seed_lead(outsider)

    with pytest.raises(DBAPIError):
        await _as_manager(
            manager_auth,
            manager,
            "INSERT INTO team_work_notes (id, lead_uuid, business_line, author_name, body) "
            "VALUES (gen_random_uuid(), :id, 'loans', 'x', 'direct')",
            {"id": lead_id},
        )
    with pytest.raises(DBAPIError, match="not in the caller's team"):
        await _as_manager(
            manager_auth,
            manager,
            "SELECT team_manager_set_lead_status(:id, 'closed')",
            {"id": outsider_lead},
        )
    with pytest.raises(DBAPIError, match="not in the caller's team"):
        await _as_manager(
            manager_auth,
            manager,
            "SELECT team_manager_add_note(:id, NULL, 'hello', NULL)",
            {"id": outsider_lead},
        )
    untouched = await _as_manager(
        manager_auth,
        manager,
        "UPDATE leads SET status = 'closed' WHERE id = :id",
        {"id": lead_id},
    )
    assert untouched == [(0,)]
    assert await _lead_status(lead_id) == "working"

    _, other_auth, other_manager, _ = await _sub_admin(client)
    with pytest.raises(DBAPIError, match="not in the caller's team"):
        await _as_manager(
            other_auth,
            other_manager,
            "SELECT team_manager_set_lead_status(:id, 'closed')",
            {"id": lead_id},
        )
    assert (
        await _as_manager(
            other_auth, other_manager, "SELECT * FROM team_lead_signals(:ids)", {"ids": [lead_id]}
        )
        == []
    )
    signals = await _as_manager(
        manager_auth,
        manager,
        "SELECT lead_uuid, last_disposition FROM team_lead_signals(:ids)",
        {"ids": [lead_id, outsider_lead]},
    )
    assert [row[0] for row in signals] == [lead_id]


@pytest.mark.asyncio
async def test_team_work_list_carries_assignee_signals_and_admin_field_rules(
    client: AsyncClient,
) -> None:
    token, _, _, team_id, asha, bala, outsider = await _telecaller_team(client)
    asha_lead = await _seed_lead(asha, calls=("callback_requested",))
    bala_lead = await _seed_lead(bala, calls=("connected",))
    await _seed_lead(outsider, calls=("connected",))

    work = await client.get(f"/api/v1/manager/teams/{team_id}/work", headers=_headers(token))
    assert work.status_code == 200, work.text
    rows = {row["id"]: row for row in work.json()["leads"]}
    assert set(rows) == {str(asha_lead), str(bala_lead)}
    assert rows[str(asha_lead)]["assigned_to"]["first_name"] == "Asha"
    assert rows[str(asha_lead)]["signals"]["last_disposition"] == "callback_requested"
    assert rows[str(bala_lead)]["signals"]["last_interest_level"] == "warm"
    assert rows[str(asha_lead)]["name"] == "Team Lead"

    # The Admin hides lead names from Telecallers: the manager's view follows.
    import app.db.session as session_mod
    from app.models.field_visibility import (
        FieldTargetRole,
        FieldVisibilityConfig,
        FieldVisibilityMode,
    )

    async with session_mod.AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(FieldVisibilityConfig).where(
                FieldVisibilityConfig.target_role == FieldTargetRole.TELECALLER,
                FieldVisibilityConfig.entity == "lead",
                FieldVisibilityConfig.field_key == "name",
            )
        )
        previous_mode = previous.mode if previous else None
        if previous is None:
            db.add(
                FieldVisibilityConfig(
                    target_role=FieldTargetRole.TELECALLER,
                    entity="lead",
                    field_key="name",
                    mode=FieldVisibilityMode.DENY,
                )
            )
        else:
            previous.mode = FieldVisibilityMode.DENY
        await db.commit()
    try:
        hidden = await client.get(f"/api/v1/manager/teams/{team_id}/work", headers=_headers(token))
        row = next(r for r in hidden.json()["leads"] if r["id"] == str(asha_lead))
        assert row["name"] is None
        assert "name" in row["hidden_fields"]
    finally:
        async with session_mod.AsyncSessionLocal() as db:
            config = await db.scalar(
                select(FieldVisibilityConfig).where(
                    FieldVisibilityConfig.target_role == FieldTargetRole.TELECALLER,
                    FieldVisibilityConfig.entity == "lead",
                    FieldVisibilityConfig.field_key == "name",
                )
            )
            if previous_mode is None:
                await db.delete(config)
            else:
                config.mode = previous_mode
            await db.commit()


@pytest.mark.asyncio
async def test_team_analytics_filters_members_and_aggregated_report(client: AsyncClient) -> None:
    token, _, _, team_id, asha, bala, outsider = await _telecaller_team(client)
    await _seed_lead(asha, calls=("connected", "busy", "connected"))
    await _seed_lead(bala, calls=("no_answer", "connected"))
    base = f"/api/v1/manager/teams/{team_id}"

    everyone = await client.get(f"{base}/overview?days=7", headers=_headers(token))
    assert everyone.status_code == 200, everyone.text
    body = everyone.json()
    assert {k["key"]: k["value"] for k in body["totals"]}["calls"] == 5
    report = body["report"]
    assert report["kpis"] == body["totals"]
    assert sum(sum(p["values"].values()) for p in report["trend"]["points"]) == 5
    assert "the team" in report["trend"]["description"]

    connected = await client.get(
        f"{base}/overview?days=7&call_status=connected", headers=_headers(token)
    )
    assert {k["key"]: k["value"] for k in connected.json()["totals"]}["calls"] == 3

    only_bala = await client.get(f"{base}/overview?days=7&member={bala}", headers=_headers(token))
    assert [m["member"]["first_name"] for m in only_bala.json()["members"]] == ["Bala"]
    assert {k["key"]: k["value"] for k in only_bala.json()["totals"]}["calls"] == 2

    assert (
        await client.get(f"{base}/overview?member={outsider}", headers=_headers(token))
    ).status_code == 404
    wrong_role = await client.get(
        f"{base}/overview?task_type=property_visit", headers=_headers(token)
    )
    assert wrong_role.status_code == 422
    member = await client.get(
        f"{base}/members/{asha}/analytics?days=7&call_status=busy", headers=_headers(token)
    )
    assert {k["key"]: k["value"] for k in member.json()["kpis"]}["calls"] == 1


@pytest.mark.asyncio
async def test_lead_notes_stay_with_the_telecallers_manager(client: AsyncClient) -> None:
    """An Employee-team manager reaches a lead through a member's task on it,
    but never the Telecaller manager's lead notes, and cannot add one."""
    tele_token, _, _, tele_team, asha, _, _ = await _telecaller_team(client)
    _, emp_manager_auth, emp_manager, _ = await _sub_admin(client)
    _, emp = await seed_line_staff("employee")
    await seed_team(emp_manager, [emp], member_role="employee")
    task_id, lead_id = await _seed_task(emp, asha)

    note = await client.post(
        f"/api/v1/manager/teams/{tele_team}/leads/{lead_id}/notes",
        headers=_headers(tele_token),
        json={"body": "Coaching for Asha only."},
    )
    assert note.status_code == 201, note.text

    visible = await _as_manager(
        emp_manager_auth,
        emp_manager,
        "SELECT id FROM team_work_notes WHERE lead_uuid = :id",
        {"id": lead_id},
    )
    assert visible == []
    with pytest.raises(DBAPIError, match="not in the caller's team"):
        await _as_manager(
            emp_manager_auth,
            emp_manager,
            "SELECT team_manager_add_note(:id, NULL, 'not mine', NULL)",
            {"id": lead_id},
        )
    # The Employee-team manager still reaches the lead for its task's context.
    rows = await _as_manager(
        emp_manager_auth, emp_manager, "SELECT id FROM leads WHERE id = :id", {"id": lead_id}
    )
    assert rows == [(lead_id,)]
    assert task_id
