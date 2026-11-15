"""/api/v1/admin/teams — Main Admin manages Sub Admin–led teams (CS-019).

Covers: Main Admin create / staff / rename / re-manage / archive; every
platform Admin may read but only the Main Admin may write; Sub Admins and line
staff are refused; one live team per manager per line; one team per member
per line (dual-line staff may join one team in each line); member role, line
and status validation; archive frees members; audit rows for every write.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.tests.test_admin_hierarchy_api import (
    _additional_admin,
    _headers,
    _primary_admin,
    _sub_admin,
)
from conftest import unique_mobile


async def seed_line_staff(
    role: str,
    business_line: str = "loans",
    *,
    first_name: str = "Team",
    status: str = "active",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A line-scoped Telecaller/Employee. Returns (auth_user_uuid, staff_profile_uuid)."""
    import app.db.session as session_mod
    from app.models.profile import ProfileScope, ProfileStatus, StaffProfile, StaffRole
    from app.models.user import User

    async with session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name=first_name,
            last_name=role.title(),
            mobile=unique_mobile(),
            email=f"tm_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole(role),
            scope=ProfileScope.LINE,
            business_line=business_line,
            staff_code=f"TM-{uuid.uuid4().hex[:8]}",
            status=ProfileStatus(status),
        )
        db.add(profile)
        await db.commit()
        return user.id, profile.id


async def seed_team(
    manager_profile: uuid.UUID,
    member_profiles: list[uuid.UUID],
    *,
    business_line: str = "loans",
    member_role: str = "telecaller",
) -> uuid.UUID:
    """Insert a team directly (superuser session) for manager-side tests."""
    import app.db.session as session_mod
    from app.models.staff_team import StaffTeam, StaffTeamMember

    async with session_mod.AsyncSessionLocal() as db:
        team = StaffTeam(
            name=f"Team {uuid.uuid4().hex[:6]}",
            business_line=business_line,
            member_role=member_role,
            manager_staff_profile_uuid=manager_profile,
        )
        db.add(team)
        await db.flush()
        for member in member_profiles:
            db.add(
                StaffTeamMember(
                    team_uuid=team.id, staff_profile_uuid=member, business_line=business_line
                )
            )
        await db.commit()
        return team.id


async def audit_actions(entity_uuid: uuid.UUID) -> list[str]:
    import app.db.session as session_mod
    from app.models.audit_log import AuditLog

    async with session_mod.AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_uuid == entity_uuid)
            .order_by(AuditLog.created_at)
        )
        return [str(getattr(action, "value", action)) for action in rows]


async def _create(
    client: AsyncClient,
    token: str,
    manager: uuid.UUID,
    *,
    business_line: str = "loans",
    member_role: str = "telecaller",
    name: str = "  North   callers ",
):
    return await client.post(
        "/api/v1/admin/teams",
        headers=_headers(token),
        json={
            "name": name,
            "business_line": business_line,
            "member_role": member_role,
            "manager_staff_profile_uuid": str(manager),
        },
    )


@pytest.mark.asyncio
async def test_main_admin_builds_a_team_and_every_admin_can_read_it(client: AsyncClient) -> None:
    main_token, _, _ = await _primary_admin(client)
    _, _, manager, _ = await _sub_admin(client)
    _, caller_a = await seed_line_staff("telecaller", first_name="Asha")
    _, caller_b = await seed_line_staff("telecaller", first_name="Bala")

    created = await _create(client, main_token, manager)
    assert created.status_code == 201, created.text
    team = created.json()
    assert team["name"] == "North callers"
    assert team["manager"]["staff_profile_uuid"] == str(manager)
    assert team["members"] == []

    for member in (caller_a, caller_b):
        added = await client.post(
            f"/api/v1/admin/teams/{team['id']}/members/{member}", headers=_headers(main_token)
        )
        assert added.status_code == 200, added.text
    assert [m["first_name"] for m in added.json()["members"]] == ["Asha", "Bala"]

    eligible = await client.get(
        "/api/v1/admin/teams/eligible?business_line=loans&member_role=telecaller",
        headers=_headers(main_token),
    )
    assert eligible.status_code == 200
    eligible_members = {p["staff_profile_uuid"] for p in eligible.json()["members"]}
    eligible_managers = {p["staff_profile_uuid"] for p in eligible.json()["managers"]}
    assert str(caller_a) not in eligible_members
    assert str(manager) not in eligible_managers

    other_token, _, _ = await _additional_admin(client)
    listed = await client.get("/api/v1/admin/teams", headers=_headers(other_token))
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.json()["can_edit"] is False
    assert team["id"] in {t["id"] for t in listed.json()["teams"]}

    team_id = uuid.UUID(team["id"])
    assert await audit_actions(team_id) == [
        "staff_team_created",
        "staff_team_member_added",
        "staff_team_member_added",
    ]


@pytest.mark.asyncio
async def test_only_the_main_admin_may_write_and_staff_may_not_read(client: AsyncClient) -> None:
    other_token, _, _ = await _additional_admin(client)
    sub_token, _, manager, _ = await _sub_admin(client)

    refused = await _create(client, other_token, manager)
    assert refused.status_code == 403
    assert "Main Admin" in refused.json()["detail"]
    eligible = await client.get(
        "/api/v1/admin/teams/eligible?business_line=loans&member_role=telecaller",
        headers=_headers(other_token),
    )
    assert eligible.status_code == 403

    assert (await client.get("/api/v1/admin/teams", headers=_headers(sub_token))).status_code == 403
    assert (await _create(client, sub_token, manager)).status_code == 403


@pytest.mark.asyncio
async def test_one_live_team_per_manager_per_line(client: AsyncClient) -> None:
    main_token, _, _ = await _primary_admin(client)
    _, _, manager, _ = await _sub_admin(client)

    assert (await _create(client, main_token, manager)).status_code == 201
    duplicate = await _create(client, main_token, manager, member_role="employee")
    assert duplicate.status_code == 409
    other_line = await _create(client, main_token, manager, business_line="real_estate")
    assert other_line.status_code == 201

    not_a_sub_admin = await _create(client, main_token, (await seed_line_staff("telecaller"))[1])
    assert not_a_sub_admin.status_code == 422


@pytest.mark.asyncio
async def test_member_rules_role_line_status_and_one_team_per_line(client: AsyncClient) -> None:
    main_token, _, _ = await _primary_admin(client)
    _, _, manager_one, _ = await _sub_admin(client)
    _, _, manager_two, _ = await _sub_admin(client)
    loans_team = (await _create(client, main_token, manager_one)).json()["id"]
    second_loans_team = (await _create(client, main_token, manager_two)).json()["id"]
    estate_team = (
        await _create(client, main_token, manager_one, business_line="real_estate")
    ).json()["id"]

    async def add(team_id: str, member: uuid.UUID) -> int:
        res = await client.post(
            f"/api/v1/admin/teams/{team_id}/members/{member}", headers=_headers(main_token)
        )
        return res.status_code

    assert await add(loans_team, (await seed_line_staff("employee"))[1]) == 422
    assert await add(loans_team, (await seed_line_staff("telecaller", "real_estate"))[1]) == 422
    _, suspended = await seed_line_staff("telecaller", status="suspended")
    assert await add(loans_team, suspended) == 422

    _, dual = await seed_line_staff("telecaller", "both")
    assert await add(loans_team, dual) == 200
    assert await add(estate_team, dual) == 200
    assert await add(second_loans_team, dual) == 409

    removed = await client.delete(
        f"/api/v1/admin/teams/{loans_team}/members/{dual}", headers=_headers(main_token)
    )
    assert removed.status_code == 200
    assert removed.json()["members"] == []
    assert await add(second_loans_team, dual) == 200
    missing = await client.delete(
        f"/api/v1/admin/teams/{loans_team}/members/{dual}", headers=_headers(main_token)
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_rename_change_manager_and_archive(client: AsyncClient) -> None:
    main_token, _, _ = await _primary_admin(client)
    _, _, manager, _ = await _sub_admin(client)
    _, _, successor, _ = await _sub_admin(client)
    _, member = await seed_line_staff("employee")
    team_id = (await _create(client, main_token, manager, member_role="employee")).json()["id"]
    await client.post(
        f"/api/v1/admin/teams/{team_id}/members/{member}", headers=_headers(main_token)
    )

    changed = await client.patch(
        f"/api/v1/admin/teams/{team_id}",
        headers=_headers(main_token),
        json={"name": "Field squad", "manager_staff_profile_uuid": str(successor)},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Field squad"
    assert changed.json()["manager"]["staff_profile_uuid"] == str(successor)

    # A deactivated manager blocks a rename (clear 422, not a database error)
    # but never blocks handing the team on or archiving it.
    import app.db.session as session_mod
    from app.models.profile import ProfileStatus, StaffProfile

    async with session_mod.AsyncSessionLocal() as db:
        (await db.get(StaffProfile, successor)).status = ProfileStatus.SUSPENDED
        await db.commit()
    blocked = await client.patch(
        f"/api/v1/admin/teams/{team_id}", headers=_headers(main_token), json={"name": "Renamed"}
    )
    assert blocked.status_code == 422
    async with session_mod.AsyncSessionLocal() as db:
        (await db.get(StaffProfile, successor)).status = ProfileStatus.ACTIVE
        await db.commit()

    archived = await client.patch(
        f"/api/v1/admin/teams/{team_id}", headers=_headers(main_token), json={"archive": True}
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert archived.json()["members"] == []

    again = await client.patch(
        f"/api/v1/admin/teams/{team_id}", headers=_headers(main_token), json={"name": "Again"}
    )
    assert again.status_code == 409
    # The archived team no longer blocks either the member or the manager.
    fresh = (await _create(client, main_token, successor, member_role="employee")).json()["id"]
    rejoin = await client.post(
        f"/api/v1/admin/teams/{fresh}/members/{member}", headers=_headers(main_token)
    )
    assert rejoin.status_code == 200

    live = await client.get("/api/v1/admin/teams", headers=_headers(main_token))
    assert team_id not in {t["id"] for t in live.json()["teams"]}
    everything = await client.get(
        "/api/v1/admin/teams?include_archived=true", headers=_headers(main_token)
    )
    assert team_id in {t["id"] for t in everything.json()["teams"]}
    assert (await audit_actions(uuid.UUID(team_id)))[-2:] == [
        "staff_team_updated",
        "staff_team_archived",
    ]
