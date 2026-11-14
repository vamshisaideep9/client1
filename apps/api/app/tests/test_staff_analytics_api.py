"""GET /api/v1/me/analytics — personal analytics per role.

Covers: the caller's own numbers only (another person's calls/tasks never
count), role gating (Client gets 403), the period clamp, and the response
shape every role shares.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from conftest import full_registration, unique_mobile


async def _seed_staff(role: str, business_line: str = "loans") -> tuple[str, str]:
    import app.db.session as _session_mod
    from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
    from app.models.user import User

    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name=role.title(),
            mobile=unique_mobile(),
            email=f"an_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole(role),
            scope=ProfileScope.LINE,
            business_line=business_line,
            staff_code=f"AN-{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return str(user.id), str(profile.id)


def _token(auth_uuid: str, role: str, **claims: str) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": auth_uuid,
            "role": role,
            "business_line": "loans",
            "platform_scope": "false",
            **claims,
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_lead_with_calls(staff_uuid: str, dispositions: list[str]) -> str:
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity

    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            name="Analytics Lead",
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.WORKING,
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=uuid.UUID(staff_uuid),
        )
        db.add(lead)
        await db.flush()
        for disposition in dispositions:
            db.add(
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=uuid.UUID(staff_uuid),
                    business_line="loans",
                    disposition=CallDisposition(disposition),
                    interest_level=InterestLevel.HOT if disposition == "connected" else None,
                )
            )
        await db.commit()
        return str(lead.id)


def _kpis(body: dict) -> dict[str, float | None]:
    return {kpi["key"]: kpi["value"] for kpi in body["kpis"]}


@pytest.mark.asyncio
async def test_telecaller_sees_only_own_calls_and_leads(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    _, other_staff = await _seed_staff("telecaller")
    await _seed_lead_with_calls(staff_uuid, ["connected", "busy", "no_answer", "connected"])
    await _seed_lead_with_calls(other_staff, ["connected", "connected", "connected"])

    res = await client.get(
        "/api/v1/me/analytics",
        headers=_token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid),
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["role"] == "telecaller"
    assert body["range_days"] == 30
    kpis = _kpis(body)
    assert kpis["calls"] == 4
    assert kpis["connect_rate"] == 50.0
    assert kpis["active_leads"] == 1

    points = body["trend"]["points"]
    assert len(points) == 30
    today = points[-1]["values"]
    assert today["connected"] == 2
    assert today["not_reached"] == 2
    assert [step["value"] for step in body["funnel"]["steps"]] == [1, 1, 0]
    interest = next(b for b in body["breakdowns"] if b["key"] == "interest")
    assert interest["items"] == [{"key": "hot", "label": "Hot", "value": 2.0}]


@pytest.mark.asyncio
async def test_period_is_clamped_to_supported_ranges(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_staff("telecaller")
    headers = _token(auth_uuid, "telecaller", staff_profile_uuid=staff_uuid)

    week = await client.get("/api/v1/me/analytics?days=7", headers=headers)
    assert week.json()["range_days"] == 7
    assert len(week.json()["trend"]["points"]) == 7
    odd = await client.get("/api/v1/me/analytics?days=45", headers=headers)
    assert odd.json()["range_days"] == 30
    too_big = await client.get("/api/v1/me/analytics?days=999", headers=headers)
    assert too_big.status_code == 422


@pytest.mark.asyncio
async def test_employee_sees_own_tasks_with_on_time_rate(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus
    from app.models.task import Task, TaskStatus, TaskType

    auth_uuid, employee_uuid = await _seed_staff("employee")
    _, other_employee = await _seed_staff("employee")
    _, raiser = await _seed_staff("telecaller")
    now = datetime.now(UTC)

    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.WORKING,
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=uuid.UUID(raiser),
        )
        db.add(lead)
        await db.flush()

        def task(employee: str, status: TaskStatus, due: datetime | None) -> Task:
            return Task(
                raised_by_staff_profile_uuid=uuid.UUID(raiser),
                assigned_employee_profile_uuid=uuid.UUID(employee),
                business_line="loans",
                task_type=TaskType.DOCUMENT_COLLECTION,
                lead_uuid=lead.id,
                status=status,
                due_at=due,
            )

        db.add_all(
            [
                task(employee_uuid, TaskStatus.COMPLETED, now + timedelta(days=1)),
                task(employee_uuid, TaskStatus.COMPLETED, now - timedelta(days=1)),
                task(employee_uuid, TaskStatus.ASSIGNED, None),
                task(other_employee, TaskStatus.ASSIGNED, None),
            ]
        )
        await db.commit()

    res = await client.get(
        "/api/v1/me/analytics",
        headers=_token(auth_uuid, "employee", staff_profile_uuid=employee_uuid),
    )
    assert res.status_code == 200, res.text
    kpis = _kpis(res.json())
    assert kpis["open_tasks"] == 1
    assert kpis["completed"] == 2
    assert kpis["on_time"] == 50.0
    assert res.json()["trend"]["points"][-1]["values"] == {"assigned": 3, "completed": 2}


@pytest.mark.asyncio
async def test_agent_and_sub_admin_get_their_shape(client: AsyncClient) -> None:
    agent_auth, _ = await _seed_staff("telecaller")
    sub_admin_auth, _ = await _seed_staff("telecaller")
    agent = await client.get(
        "/api/v1/me/analytics",
        headers=_token(agent_auth, "agent", agent_profile_uuid=str(uuid.uuid4())),
    )
    assert agent.status_code == 200, agent.text
    assert agent.json()["role"] == "agent"
    assert {kpi["key"] for kpi in agent.json()["kpis"]} >= {"introduced", "paid", "pending"}

    sub_admin = await client.get(
        "/api/v1/me/analytics", headers=_token(sub_admin_auth, "sub_admin")
    )
    assert sub_admin.status_code == 200, sub_admin.text
    assert sub_admin.json()["role"] == "sub_admin"
    assert sub_admin.json()["funnel"] is None


@pytest.mark.asyncio
async def test_clients_and_unauthenticated_callers_are_refused(client: AsyncClient) -> None:
    staff_auth, _ = await _seed_staff("telecaller")
    assert (await client.get("/api/v1/me/analytics")).status_code == 401
    token, _ = await full_registration(client, lines=["loans"])
    res = await client.get("/api/v1/me/analytics", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403

    staff_without_profile = await client.get(
        "/api/v1/me/analytics", headers=_token(staff_auth, "telecaller")
    )
    assert staff_without_profile.status_code == 403
