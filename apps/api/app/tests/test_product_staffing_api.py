"""GET /api/v1/admin/product-staffing: who covers each product (platform Admin only)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update

import app.db.session as db_session
from app.models.user import User, UserStatus
from app.tests.test_admin_hierarchy_api import _headers, _primary_admin, _sub_admin
from app.tests.test_product_dashboard_api import (
    line_token,
    make_product,
    scoped_manager,
    seed_product_lead,
    seed_product_task,
    specialise,
)
from app.tests.test_staff_teams_api import seed_line_staff

PATH = "/api/v1/admin/product-staffing"


@pytest.mark.asyncio
async def test_staffing_lists_specialists_counts_and_coverage(client: AsyncClient) -> None:
    full, telecaller_only, officer_only, nobody = (
        await make_product(),
        await make_product("credit_card"),
        await make_product("insurance"),
        await make_product(active=False),
    )
    tele_auth, tele = await seed_line_staff("telecaller", first_name="Tara")
    _, officer = await seed_line_staff("employee", "both", first_name="Omkar")
    _, card_tele = await seed_line_staff("telecaller", first_name="Cara")
    insurance_auth, insurance_officer = await seed_line_staff("employee", first_name="Ivan")
    suspended_auth, suspended = await seed_line_staff("telecaller", first_name="Sid")
    _, free_loans = await seed_line_staff("telecaller", first_name="Free")
    _, estate = await seed_line_staff("employee", "real_estate", first_name="Esta")
    for person, product in (
        (tele, full),
        (officer, full),
        (card_tele, telecaller_only),
        (insurance_officer, officer_only),
        (suspended, officer_only),
    ):
        await specialise(person, product.id)
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == suspended_auth).values(status=UserStatus.SUSPENDED)
        )
        await db.commit()

    lead = await seed_product_lead(full.id, tele)
    await seed_product_lead(full.id, None, status="new")
    await seed_product_lead(full.id, None, status="released")
    await seed_product_lead(full.id, tele, status="converted")
    await seed_product_task(lead, tele, officer)
    await seed_product_task(lead, tele, None, status="unassigned")
    await seed_product_task(lead, tele, officer, status="completed")

    admin, *_ = await _primary_admin(client)
    res = await client.get(PATH, headers=_headers(admin))
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    rows = {row["product_id"]: row for row in body["products"]}

    row = rows[str(full.id)]
    assert row["coverage"] == "full"
    assert [p["staff_profile_uuid"] for p in row["telecallers"]] == [str(tele)]
    assert row["telecallers"][0]["auth_user_uuid"] == str(tele_auth)
    assert row["telecallers"][0]["status"] == "active"
    assert [p["staff_profile_uuid"] for p in row["officers"]] == [str(officer)]
    assert row["officers"][0]["business_line"] == "both"
    assert (row["open_leads"], row["unassigned_leads"], row["open_tasks"]) == (3, 2, 2)
    assert "mobile" not in row["telecallers"][0] and "email" not in row["telecallers"][0]

    assert rows[str(telecaller_only.id)]["coverage"] == "no_officer"
    insurance = rows[str(officer_only.id)]
    assert insurance["coverage"] == "no_telecaller"
    # A suspended specialist is listed but does not cover the product.
    assert {p["status"] for p in insurance["telecallers"]} == {"suspended"}
    assert rows[str(nobody.id)]["coverage"] == "none"
    assert rows[str(nobody.id)]["active"] is False

    available = {person["staff_profile_uuid"] for person in body["available"]}
    assert str(free_loans) in available
    assert str(tele) not in available and str(estate) not in available
    lines = {item["business_line"]: item for item in body["summary"]["unspecialised"]}
    assert lines["loans"]["telecallers"] >= 1 and lines["real_estate"]["officers"] >= 1
    assert body["summary"]["products"] == len(body["products"])
    assert body["summary"]["fully_covered"] >= 1
    assert insurance_auth  # the Officer's account id is what the Assign action patches


@pytest.mark.asyncio
async def test_staffing_is_platform_admin_only(client: AsyncClient) -> None:
    legacy, *_ = await _sub_admin(client)
    assert (await client.get(PATH, headers=_headers(legacy))).status_code == 403
    scoped, _ = await scoped_manager(
        client, [{"assignment": "team_manager", "business_line": "loans", "actions": ["view"]}]
    )
    assert (await client.get(PATH, headers=scoped)).status_code == 403
    for role in ("telecaller", "employee"):
        auth, profile = await seed_line_staff(role)
        token = line_token(auth, profile, role)
        assert (await client.get(PATH, headers=_headers(token))).status_code == 403
