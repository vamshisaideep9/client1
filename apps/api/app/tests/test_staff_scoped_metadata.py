"""Task counterpart and own-profile metadata cannot become a staff directory."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

import app.db.session as sessions
from app.core.security import create_access_token
from app.models.profile import StaffProfile
from app.models.staff_team import StaffTeam
from app.models.task import Task
from app.models.user import User, UserStatus
from app.services.profile_metadata import task_staff_for_ids
from app.tests.test_admin_hierarchy_api import _headers, _primary_admin, _sub_admin
from app.tests.test_employee_api import _employee_token, _seed_employee, _seed_task
from app.tests.test_staff_teams_api import seed_line_staff, seed_team


def token(user_id, profile_id, role="telecaller", line="loans"):
    return create_access_token(
        {
            "sub": str(user_id),
            "role": role,
            "business_line": line,
            "staff_profile_uuid": str(profile_id),
            "platform_scope": "false",
        }
    )


async def context(db, user_id, profile_id, role, line):
    await db.execute(text("SET LOCAL ROLE api_user"))
    await db.execute(
        text(
            "SELECT set_config('app.auth_user_uuid', :u, true), "
            "set_config('app.staff_profile_uuid', :p, true), "
            "set_config('app.business_line', :line, true), "
            "set_config('app.role', :role, true), set_config('app.platform_scope', 'false', true)"
        ),
        {"u": str(user_id), "p": str(profile_id), "role": role, "line": line},
    )


@pytest.mark.asyncio
async def test_employee_all_task_responses_include_counterpart_without_contacts(
    client: AsyncClient,
):
    user, profile = await _seed_employee()
    task_id = await _seed_task("loans", profile, due_at=datetime.now(UTC) + timedelta(minutes=3))
    headers = _headers(_employee_token(user, profile))
    async with sessions.AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        raiser = await db.get(StaffProfile, task.raised_by_staff_profile_uuid)
    expected = {
        "raised_by_telecaller_name": "Test Staff",
        "raised_by_telecaller_code": raiser.staff_code,
    }
    paths = ["/api/v1/employee/tasks", f"/api/v1/employee/tasks/{task_id}", "/api/v1/employee/home"]
    for path in paths:
        res = await client.get(path, headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        row = (
            body[0]
            if isinstance(body, list)
            else body["tasks_today"][0]
            if "tasks_today" in body
            else body
        )
        assert expected.items() <= row.items()
        assert not any("email" in key or "telecaller_mobile" in key for key in row)
    for status in ("in_progress", "cancelled"):
        changed = await client.patch(
            f"/api/v1/employee/tasks/{task_id}", headers=headers, json={"status": status}
        )
        assert changed.status_code == 200, changed.text
        assert expected.items() <= changed.json().items()
    reopened = await client.post(
        f"/api/v1/employee/tasks/{task_id}/reopen",
        headers=headers,
        json={"reason": "Resume scheduled field work"},
    )
    assert reopened.status_code == 200, reopened.text
    assert expected.items() <= reopened.json().items()


@pytest.mark.asyncio
async def test_telecaller_detail_and_created_task_include_employee(client: AsyncClient):
    _, employee = await _seed_employee()
    task_id = await _seed_task("loans", employee)
    async with sessions.AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        raiser = await db.get(StaffProfile, task.raised_by_staff_profile_uuid)
        worker = await db.get(StaffProfile, UUID(employee))
    headers = _headers(token(raiser.auth_user_uuid, raiser.id))
    res = await client.get(f"/api/v1/telecaller/leads/{task.lead_uuid}", headers=headers)
    assert res.status_code == 200, res.text
    row = res.json()["tasks"][0]
    assert row["assigned_employee_name"] == "Test Employee"
    assert row["assigned_employee_code"] == worker.staff_code
    created = await client.post(
        f"/api/v1/telecaller/leads/{task.lead_uuid}/tasks",
        headers=headers,
        json={"notes": "Collect supporting documents"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["raised_by_telecaller_code"] == raiser.staff_code
    if created.json()["assigned_employee_profile_uuid"]:
        assert created.json()["assigned_employee_name"]
        assert created.json()["assigned_employee_code"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "denial", ["unrelated", "wrong_line", "wrong_role", "wrong_user", "inactive"]
)
async def test_task_projection_enforces_actual_assignment_role_line_and_identity(denial):
    user, profile = await _seed_employee()
    task_id = UUID(await _seed_task("loans", profile))
    if denial == "unrelated":
        user, profile = await _seed_employee()
    async with sessions.AsyncSessionLocal() as db:
        if denial == "inactive":
            await db.execute(
                update(StaffProfile)
                .where(StaffProfile.id == UUID(profile))
                .values(status="inactive")
            )
            await db.commit()
        await context(
            db,
            uuid4() if denial == "wrong_user" else user,
            profile,
            "telecaller" if denial == "wrong_role" else "employee",
            "real_estate" if denial == "wrong_line" else "loans",
        )
        assert await task_staff_for_ids(db, [task_id]) == {}
        assert list(await db.scalars(select(User.id).where(User.id != UUID(user)))) == []


@pytest.mark.asyncio
async def test_task_projection_grants_only_names_codes_and_redacts_deleted_staff():
    user, profile = await _seed_employee()
    task_id = UUID(await _seed_task("loans", profile))
    async with sessions.AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        raiser = await db.get(StaffProfile, task.raised_by_staff_profile_uuid)
        await db.execute(
            update(User)
            .where(User.id == raiser.auth_user_uuid)
            .values(status=UserStatus.SOFT_DELETED)
        )
        await db.commit()
        await context(db, user, profile, "employee", "loans")
        projection = (await task_staff_for_ids(db, [task_id]))[task_id].model_dump()
        assert set(projection) == {
            "raised_by_telecaller_name",
            "raised_by_telecaller_code",
            "assigned_employee_name",
            "assigned_employee_code",
        }
        assert projection["raised_by_telecaller_name"] is None
        assert projection["raised_by_telecaller_code"] is None
        assert projection["assigned_employee_name"] == "Test Employee"
        assert await db.get(User, raiser.auth_user_uuid, populate_existing=True) is None


@pytest.mark.asyncio
async def test_own_metadata_retains_both_team_names_and_does_not_open_directory(
    client: AsyncClient,
):
    _, _, manager, _ = await _sub_admin(client)
    user, staff = await seed_line_staff("telecaller", "both")
    loans = await seed_team(manager, [staff], business_line="loans")
    estate = await seed_team(manager, [staff], business_line="real_estate")
    headers = _headers(token(user, staff, line="both"))
    res = await client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200, res.text
    meta = res.json()["role_profiles"]
    assert len(meta) == 1
    assert meta[0]["role"] == "telecaller"
    assert meta[0]["business_line"] == "both"
    assert {team["business_line"] for team in meta[0]["teams"]} == {"loans", "real_estate"}
    async with sessions.AsyncSessionLocal() as db:
        profile = await db.get(StaffProfile, staff)
        assert meta[0]["code"] == profile.staff_code
        await db.execute(
            update(StaffTeam).where(StaffTeam.id == estate).values(archived_at=datetime.now(UTC))
        )
        await db.commit()
    refreshed = await client.get("/api/v1/auth/me", headers=headers)
    assert [team["business_line"] for team in refreshed.json()["role_profiles"][0]["teams"]] == [
        "loans"
    ]
    async with sessions.AsyncSessionLocal() as db:
        await context(db, user, staff, "telecaller", "loans")
        assert list(await db.scalars(select(StaffTeam.id))) == []
        own = list(await db.execute(text("SELECT * FROM own_profile_teams()")))
        assert len(own) == 1
        assert own[0].staff_profile_uuid == staff
        assert own[0].business_line == "loans"
        assert await db.get(StaffTeam, loans) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["admin", "sub_admin", "telecaller", "employee", "agent", "client"]
)
async def test_own_role_codes_all_roles(client: AsyncClient, role):
    if role == "admin":
        auth, _, profile = await _primary_admin(client)
    elif role == "sub_admin":
        auth, _, profile, _ = await _sub_admin(client)
    elif role == "agent":
        from app.tests.test_lead_auto_assignment import _seed_agent

        row = await _seed_agent()
        profile = row.id
        auth = create_access_token(
            {
                "sub": str(row.auth_user_uuid),
                "role": "agent",
                "business_line": "loans",
                "agent_profile_uuid": str(row.id),
            }
        )
    elif role == "client":
        from conftest import full_registration

        auth, _ = await full_registration(client)
        profile = None
    else:
        user, profile = await seed_line_staff(role)
        auth = token(user, profile, role=role)
    res = await client.get("/api/v1/auth/me", headers=_headers(auth))
    assert res.status_code == 200, res.text
    if role == "client":
        assert res.json()["role_profiles"] == []
        assert res.json()["profiles"][0]["customer_code"]
    else:
        row = next(item for item in res.json()["role_profiles"] if item["role"] == role)
        assert row["profile_uuid"] == str(profile)
        assert row["code"]
