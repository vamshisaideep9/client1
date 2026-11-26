"""Per-product dashboard, Team Manager product index and specialist home counts.

GET /api/v1/products/{id}/dashboard: platform Admin sees every lead, task and
person; a Team Manager sees only their own active Loans teams' members and
their work (explicit member filters plus ``team_manager_reaches`` RLS); every
other caller gets 403. GET /api/v1/manager/products lists the team's products.
The Telecaller and Officer homes count only the caller's own work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

import app.db.session as db_session
from app.core.security import create_access_token
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity
from app.models.loan import LoanApplication, LoanType
from app.models.profile import ClientProfile, StaffProfile
from app.models.task import Task, TaskStatus, TaskType
from app.models.user import User
from app.tests.test_admin_hierarchy_api import _headers, _primary_admin, _staff_token, _sub_admin
from app.tests.test_staff_teams_api import seed_line_staff, seed_team
from conftest import unique_email, unique_mobile

UUID = uuid.UUID


async def make_product(category: str = "loan", *, active: bool = True) -> LoanType:
    async with db_session.AsyncSessionLocal() as db:
        row = LoanType(
            name=f"dash-{uuid.uuid4().hex}",
            label=f"Dash {category} {uuid.uuid4().hex[:6]}",
            category=category,
            active=active,
        )
        db.add(row)
        await db.commit()
        return row


async def specialise(profile_id: UUID, product_id: UUID | None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == profile_id)
            .values(loan_specialty_id=product_id)
        )
        await db.commit()


async def seed_product_lead(
    product_id: UUID | None,
    telecaller: UUID | None,
    *,
    status: str = "working",
    call_follow_up: datetime | None = None,
    called: bool = False,
) -> UUID:
    async with db_session.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus(status),
            origin=LeadOrigin.DIRECT,
            assigned_telecaller_profile_uuid=telecaller,
            product_id=product_id,
        )
        db.add(lead)
        await db.flush()
        if called or call_follow_up is not None:
            db.add(
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=telecaller,
                    business_line="loans",
                    disposition=CallDisposition.CONNECTED,
                    interest_level=InterestLevel.WARM,
                    follow_up_at=call_follow_up,
                )
            )
        await db.commit()
        return lead.id


async def seed_product_task(
    lead_id: UUID,
    raiser: UUID,
    officer: UUID | None,
    *,
    status: str = "in_progress",
    due_at: datetime | None = None,
) -> UUID:
    async with db_session.AsyncSessionLocal() as db:
        task = Task(
            raised_by_staff_profile_uuid=raiser,
            assigned_employee_profile_uuid=officer,
            business_line="loans",
            task_type=TaskType.DOCUMENT_COLLECTION,
            lead_uuid=lead_id,
            status=TaskStatus(status),
            due_at=due_at,
        )
        db.add(task)
        await db.commit()
        return task.id


async def seed_application(lead_id: UUID, product_id: UUID) -> None:
    async with db_session.AsyncSessionLocal() as db:
        user = User(
            first_name="Synthetic",
            last_name="Client",
            mobile=unique_mobile(),
            email=unique_email(),
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = ClientProfile(
            auth_user_uuid=user.id, business_line="loans", customer_code=f"C-{uuid.uuid4().hex}"
        )
        db.add(profile)
        await db.flush()
        db.add(
            LoanApplication(
                lead_uuid=lead_id,
                client_profile_uuid=profile.id,
                business_line="loans",
                loan_type_id=product_id,
                amount_requested=250000,
            )
        )
        await db.commit()


def line_token(auth_uuid: UUID, profile_id: UUID, role: str) -> str:
    return create_access_token(
        {
            "sub": str(auth_uuid),
            "role": role,
            "business_line": "loans",
            "platform_scope": "false",
            "staff_profile_uuid": str(profile_id),
        }
    )


async def scoped_manager(client: AsyncClient, grants: list[dict]) -> tuple[dict, UUID]:
    """A Sub Admin with an active scoped grant set (session version 2)."""
    main_token, *_ = await _primary_admin(client)
    _, user_id, staff_id, _ = await _sub_admin(client)
    res = await client.put(
        f"/api/v1/admin/staff-access/{staff_id}/dashboard",
        headers=_headers(main_token),
        json={"expected_version": 0, "status": "active", "grants": grants},
    )
    assert res.status_code == 200, res.text
    token = _staff_token(user_id=user_id, profile_id=staff_id, role="sub_admin", session_version=2)
    return _headers(token), staff_id


async def product_world(client: AsyncClient) -> dict:
    """One loan product worked by a manager's teams and by outsiders."""
    product, other = await make_product(), await make_product("insurance")
    token, _, manager, _ = await _sub_admin(client)
    _, asha = await seed_line_staff("telecaller", first_name="Asha")
    _, bala = await seed_line_staff("telecaller", first_name="Bala")
    _, omar = await seed_line_staff("employee", first_name="Omar")
    _, outsider = await seed_line_staff("telecaller", first_name="Out")
    _, outsider_officer = await seed_line_staff("employee", first_name="Outo")
    for person in (asha, omar, outsider):
        await specialise(person, product.id)
    await seed_team(manager, [asha, bala])
    await seed_team(manager, [omar], member_role="employee")

    asha_open = await seed_product_lead(product.id, asha, called=True)
    await seed_product_lead(product.id, asha, status="converted")
    await seed_product_lead(product.id, bala)
    outsider_lead = await seed_product_lead(product.id, outsider, called=True)
    await seed_product_lead(product.id, None, status="new")
    await seed_product_lead(other.id, asha)
    soon = datetime.now(UTC) + timedelta(days=2)
    await seed_product_task(asha_open, asha, omar)
    await seed_product_task(asha_open, asha, omar, status="completed", due_at=soon)
    await seed_product_task(outsider_lead, outsider, outsider_officer)
    await seed_application(asha_open, product.id)
    await seed_application(outsider_lead, product.id)
    return {
        "product": product,
        "other": other,
        "manager_token": token,
        "asha": asha,
        "bala": bala,
        "omar": omar,
        "outsider": outsider,
        "outsider_officer": outsider_officer,
    }


def _staff(body: dict) -> dict[str, dict]:
    return {row["staff_profile_uuid"]: row for row in body["staff"]}


@pytest.mark.asyncio
async def test_admin_sees_every_lead_task_and_person(client: AsyncClient) -> None:
    world = await product_world(client)
    admin, *_ = await _primary_admin(client)
    res = await client.get(
        f"/api/v1/products/{world['product'].id}/dashboard", headers=_headers(admin)
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["scope"] == "platform" and body["range_days"] == 30
    assert body["product"]["label"] == world["product"].label
    assert body["leads"] == {
        "captured": 5,
        "open": 4,
        "converted": 1,
        "conversion_rate": 20.0,
        "served_by_fallback": 1,  # Bala holds a lead without the specialty
        "unassigned": 1,
    }
    assert body["tasks"] == {"open": 2, "completed": 1, "on_time_rate": 100.0}
    assert body["requests_kind"] == "applications"
    assert body["requests_by_status"] == [{"status": "new", "count": 2}]
    assert sum(point["captured"] for point in body["trend"]) == 5
    assert sum(point["converted"] for point in body["trend"]) == 1
    staff = _staff(body)
    asha, bala, omar = (str(world[key]) for key in ("asha", "bala", "omar"))
    assert (staff[asha]["assigned"], staff[asha]["contacted"], staff[asha]["converted"]) == (
        2,
        1,
        1,
    )
    assert staff[asha]["specialist"] is True and staff[bala]["specialist"] is False
    assert (staff[omar]["open_tasks"], staff[omar]["completed_tasks"]) == (1, 1)
    assert str(world["outsider"]) in staff and str(world["outsider_officer"]) in staff
    # Specialists first.
    assert body["staff"][0]["specialist"] is True


@pytest.mark.asyncio
async def test_team_manager_sees_only_own_team_members_and_work(client: AsyncClient) -> None:
    world = await product_world(client)
    res = await client.get(
        f"/api/v1/products/{world['product'].id}/dashboard",
        headers=_headers(world["manager_token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "team"
    assert body["leads"]["captured"] == 3  # Asha's two and Bala's one
    assert body["leads"]["open"] == 2
    assert body["leads"]["converted"] == 1
    assert body["leads"]["unassigned"] == 0
    assert body["tasks"] == {"open": 1, "completed": 1, "on_time_rate": 100.0}
    assert body["requests_by_status"] == [{"status": "new", "count": 1}]
    assert set(_staff(body)) == {str(world[key]) for key in ("asha", "bala", "omar")}

    # Another manager's team never sees the first team's numbers.
    other_token, _, other_manager, _ = await _sub_admin(client)
    _, carl = await seed_line_staff("telecaller", first_name="Carl")
    await seed_team(other_manager, [carl])
    other = await client.get(
        f"/api/v1/products/{world['product'].id}/dashboard", headers=_headers(other_token)
    )
    assert other.status_code == 200, other.text
    assert other.json()["leads"]["captured"] == 0
    assert other.json()["staff"] == []


@pytest.mark.asyncio
async def test_dashboard_denies_other_roles_and_real_estate_managers(client: AsyncClient) -> None:
    world = await product_world(client)
    path = f"/api/v1/products/{world['product'].id}/dashboard"
    tele_auth, tele = await seed_line_staff("telecaller")
    officer_auth, officer = await seed_line_staff("employee")
    for token in (
        line_token(tele_auth, tele, "telecaller"),
        line_token(officer_auth, officer, "employee"),
    ):
        assert (await client.get(path, headers=_headers(token))).status_code == 403

    from app.tests.test_agent_api import _agent_token, _seed_agent

    agent = await _seed_agent("loans")
    assert (await client.get(path, headers=_headers(_agent_token(*agent)))).status_code == 403
    from conftest import full_registration

    client_token, _ = await full_registration(client, lines=["loans"])
    assert (await client.get(path, headers=_headers(client_token))).status_code == 403

    # A scoped Team Manager whose grant covers only Real Estate.
    estate_headers, estate_manager = await scoped_manager(
        client,
        [{"assignment": "team_manager", "business_line": "real_estate", "actions": ["view"]}],
    )
    _, estate_member = await seed_line_staff("telecaller", "real_estate")
    await seed_team(estate_manager, [estate_member], business_line="real_estate")
    assert (await client.get(path, headers=estate_headers)).status_code == 403
    assert (await client.get("/api/v1/manager/products", headers=estate_headers)).status_code == 403

    # A legacy Sub Admin who manages only a Real Estate team.
    legacy_token, _, legacy_manager, _ = await _sub_admin(client)
    _, legacy_member = await seed_line_staff("telecaller", "real_estate")
    await seed_team(legacy_manager, [legacy_member], business_line="real_estate")
    assert (await client.get(path, headers=_headers(legacy_token))).status_code == 403

    # A scoped Loans Team Manager with a team is allowed.
    loans_headers, loans_manager = await scoped_manager(
        client, [{"assignment": "team_manager", "business_line": "loans", "actions": ["view"]}]
    )
    _, dina = await seed_line_staff("telecaller", first_name="Dina")
    await seed_product_lead(world["product"].id, dina)
    await seed_team(loans_manager, [dina])
    allowed = await client.get(path, headers=loans_headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["leads"]["captured"] == 1


@pytest.mark.asyncio
async def test_unknown_inactive_and_card_products(client: AsyncClient) -> None:
    admin, *_ = await _primary_admin(client)
    missing = await client.get(
        f"/api/v1/products/{uuid.uuid4()}/dashboard", headers=_headers(admin)
    )
    assert missing.status_code == 404
    retired = await make_product("credit_card", active=False)
    _, tele = await seed_line_staff("telecaller")
    await seed_product_lead(retired.id, tele)
    res = await client.get(
        f"/api/v1/products/{retired.id}/dashboard",
        headers=_headers(admin),
        params={"days": 7},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product"]["active"] is False
    assert body["requests_kind"] == "enquiries"
    assert body["range_days"] == 7 and len(body["trend"]) >= 1
    assert body["leads"]["captured"] == 1
    invalid = await client.get(
        f"/api/v1/products/{retired.id}/dashboard",
        headers=_headers(admin),
        params={"date_from": "2026-01-10", "date_to": "2026-01-01"},
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_manager_product_index_lists_team_products(client: AsyncClient) -> None:
    world = await product_world(client)
    res = await client.get("/api/v1/manager/products", headers=_headers(world["manager_token"]))
    assert res.status_code == 200, res.text
    rows = {row["product_id"]: row for row in res.json()["products"]}
    main = rows[str(world["product"].id)]
    assert (main["specialists"], main["open_leads"], main["open_tasks"]) == (2, 2, 1)
    other = rows[str(world["other"].id)]
    assert (other["specialists"], other["open_leads"]) == (0, 1)
    admin, *_ = await _primary_admin(client)
    assert (
        await client.get("/api/v1/manager/products", headers=_headers(admin))
    ).status_code == 403


@pytest.mark.asyncio
async def test_team_work_rows_carry_the_stored_product(client: AsyncClient) -> None:
    world = await product_world(client)
    teams = await client.get("/api/v1/manager/teams", headers=_headers(world["manager_token"]))
    by_role = {team["member_role"]: team["id"] for team in teams.json()["teams"]}
    leads = await client.get(
        f"/api/v1/manager/teams/{by_role['telecaller']}/work",
        params={"scope": "all"},
        headers=_headers(world["manager_token"]),
    )
    assert leads.status_code == 200, leads.text
    labels = {row["product_label"] for row in leads.json()["leads"]}
    assert labels == {world["product"].label, world["other"].label}
    tasks = await client.get(
        f"/api/v1/manager/teams/{by_role['employee']}/work",
        params={"scope": "all"},
        headers=_headers(world["manager_token"]),
    )
    assert {row["product_id"] for row in tasks.json()["tasks"]} == {str(world["product"].id)}


# ---------------------------------------------------------------------------
# Specialist homes: the caller's own work only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telecaller_home_counts_only_own_leads_by_product(client: AsyncClient) -> None:
    product, card = await make_product(), await make_product("credit_card")
    auth, me = await seed_line_staff("telecaller")
    _, colleague = await seed_line_staff("telecaller")
    await specialise(me, product.id)
    past = datetime.now(UTC) - timedelta(hours=2)
    await seed_product_lead(product.id, me, call_follow_up=past)
    await seed_product_lead(product.id, me)
    await seed_product_lead(product.id, me, status="converted")
    await seed_product_lead(card.id, me)  # arrived by fallback
    await seed_product_lead(product.id, colleague)
    res = await client.get(
        "/api/v1/telecaller/home", headers=_headers(line_token(auth, me, "telecaller"))
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["specialty"] == {
        "product_id": str(product.id),
        "label": product.label,
        "category": "loan",
        "active": True,
    }
    first = body["product_counts"][0]
    assert first["product_id"] == str(product.id)
    assert (first["open"], first["overdue"], first["converted_30d"]) == (2, 1, 1)
    fallback = next(row for row in body["product_counts"] if row["product_id"] == str(card.id))
    assert (fallback["open"], fallback["label"]) == (1, card.label)

    other_auth, unspecialised = await seed_line_staff("telecaller")
    plain = await client.get(
        "/api/v1/telecaller/home",
        headers=_headers(line_token(other_auth, unspecialised, "telecaller")),
    )
    assert plain.json()["specialty"] is None and plain.json()["product_counts"] == []


@pytest.mark.asyncio
async def test_officer_home_counts_only_own_tasks_by_product(client: AsyncClient) -> None:
    product = await make_product("insurance")
    auth, me = await seed_line_staff("employee")
    _, colleague = await seed_line_staff("employee")
    _, raiser = await seed_line_staff("telecaller")
    await specialise(me, product.id)
    lead = await seed_product_lead(product.id, raiser)
    past = datetime.now(UTC) - timedelta(hours=1)
    await seed_product_task(lead, raiser, me, status="assigned", due_at=past)
    await seed_product_task(lead, raiser, me)
    await seed_product_task(lead, raiser, me, status="completed")
    await seed_product_task(lead, raiser, colleague)
    res = await client.get(
        "/api/v1/employee/home", headers=_headers(line_token(auth, me, "employee"))
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["specialty"]["product_id"] == str(product.id)
    assert body["specialty"]["category"] == "insurance"
    row = body["product_counts"][0]
    assert row["product_id"] == str(product.id)
    assert (row["open"], row["overdue"], row["completed_30d"]) == (2, 1, 1)
