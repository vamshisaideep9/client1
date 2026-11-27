"""Client feedback round 3, slice 1: what an Agent sees about their leads.

- ``GET /agent/leads/bulk/products`` lists exactly the Requirement choices a
  bulk upload accepts: active products of every category on the Loans line,
  grouped (loans, credit cards, insurance), or the property types on Real
  Estate. Inactive products are never listed.
- Agent lead reads carry the lead's product label and who works it: the
  assigned Telecaller and the Officer of the latest non-cancelled task with an
  assignee, as name, role label and staff code. They are shown even when the
  Agent's ``lead_history.staff_names`` rule hides names in the history, and
  never carry a staff phone number or email.
- The confined ``agent_lead_assignees`` function answers only the calling
  Agent's own leads on their line.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.loan import LoanType
from app.models.profile import StaffProfile, StaffRole
from app.models.task import Task, TaskStatus, TaskType
from app.tests.test_agent_dashboard_history import (
    _agent,
    _agent_rules,
    _agent_token,
    _call_as,
    _headers,
    _session,
    _staff,
)
from conftest import unique_mobile

pytestmark = pytest.mark.asyncio

PRODUCTS_URL = "/api/v1/agent/leads/bulk/products"
BULK_URL = "/api/v1/agent/leads/bulk"


async def _products(*specs: tuple[str, bool]) -> list[LoanType]:
    """One product per (category, active) spec, with unique slug and label."""
    async with _session() as db:
        rows = [
            LoanType(
                name=f"r3-{category}-{uuid.uuid4().hex[:8]}",
                label=f"R3 {category} {uuid.uuid4().hex[:6]}",
                category=category,
                active=active,
            )
            for category, active in specs
        ]
        db.add_all(rows)
        await db.commit()
        return rows


async def test_bulk_products_lists_the_active_catalogue_by_category(client: AsyncClient) -> None:
    loan, card, insurance, retired = await _products(
        ("loan", True), ("credit_card", True), ("insurance", True), ("loan", False)
    )
    async with _session() as db:
        agent = await _agent(db, "loans")
        await db.commit()
    headers = _headers(_agent_token(str(agent.auth_user_uuid), str(agent.id)))

    res = await client.get(PRODUCTS_URL, headers=headers)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["business_line"] == "loans"
    groups = {group["category"]: group for group in body["groups"]}
    assert [group["category"] for group in body["groups"]] == [
        category for category in ("loan", "credit_card", "insurance") if category in groups
    ]
    assert groups["loan"]["label"] == "Loans"
    assert groups["credit_card"]["label"] == "Credit cards"
    assert groups["insurance"]["label"] == "Insurance"
    listed = {
        (group["category"], product["code"], product["label"])
        for group in body["groups"]
        for product in group["products"]
    }
    assert ("loan", loan.name, loan.label) in listed
    assert ("credit_card", card.name, card.label) in listed
    assert ("insurance", insurance.name, insurance.label) in listed
    assert all(code != retired.name for _, code, _ in listed)

    # Every listed choice is accepted by the upload itself; the retired one is not.
    res = await client.post(
        BULK_URL,
        json={
            "dry_run": True,
            "rows": [
                {"name": "A", "mobile": unique_mobile(), "requirement": card.label},
                {"name": "B", "mobile": unique_mobile(), "requirement": insurance.name},
                {"name": "C", "mobile": unique_mobile(), "requirement": retired.label},
            ],
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert [row["outcome"] for row in rows] == ["ready", "ready", "invalid"]
    assert rows[2]["errors"][0]["message"] == (
        "Use the name or code of one of your active products."
    )


async def test_bulk_products_for_real_estate_are_property_types(client: AsyncClient) -> None:
    await _products(("loan", True))
    async with _session() as db:
        agent = await _agent(db, "real_estate")
        await db.commit()
    res = await client.get(
        PRODUCTS_URL,
        headers=_headers(_agent_token(str(agent.auth_user_uuid), str(agent.id), "real_estate")),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["business_line"] == "real_estate"
    (group,) = body["groups"]
    assert group["category"] == "property"
    assert group["label"] == "Property types"
    assert {"code": "villa", "label": "Villa"} in group["products"]
    assert {"code": "plot", "label": "Plot"} in group["products"]


async def test_bulk_products_is_agent_only(client: AsyncClient) -> None:
    from app.tests.contest_support import headers, seed_staff, token_for

    user, profile = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    res = await client.get(
        PRODUCTS_URL,
        headers=headers(
            token_for(user, "telecaller", business_line="loans", staff_profile=profile)
        ),
    )
    assert res.status_code == 403, res.text
    assert (await client.get(PRODUCTS_URL)).status_code == 401


# ---------------------------------------------------------------------------
# Assigned staff on the Agent's lead reads
# ---------------------------------------------------------------------------


async def _task(
    db,
    lead: Lead,
    raised_by: StaffProfile,
    officer: StaffProfile | None,
    status: TaskStatus,
    created_at: datetime,
) -> Task:
    task = Task(
        lead_uuid=lead.id,
        business_line=lead.business_line,
        task_type=TaskType.DOCUMENT_COLLECTION,
        raised_by_staff_profile_uuid=raised_by.id,
        assigned_employee_profile_uuid=officer.id if officer else None,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(task)
    await db.flush()
    return task


async def _assigned_world() -> dict:
    (product,) = await _products(("credit_card", True))
    async with _session() as db:
        agent = await _agent(db, "loans")
        other = await _agent(db, "loans")
        telecaller = await _staff(db, StaffRole.TELECALLER, "Tara", "Caller", "loans")
        first_officer = await _staff(db, StaffRole.EMPLOYEE, "Omar", "Early", "loans")
        officer = await _staff(db, StaffRole.EMPLOYEE, "Olga", "Field", "loans")
        cancelled_officer = await _staff(db, StaffRole.EMPLOYEE, "Carl", "Cancelled", "loans")
        lead = Lead(
            name="Assigned Lead",
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.WORKING,
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=agent.id,
            assigned_telecaller_profile_uuid=telecaller.id,
            product_id=product.id,
        )
        waiting = Lead(
            name="Waiting Lead",
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.NEW,
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=agent.id,
        )
        db.add_all([lead, waiting])
        await db.flush()
        await _task(
            db,
            lead,
            telecaller,
            first_officer,
            TaskStatus.COMPLETED,
            datetime(2026, 9, 1, tzinfo=UTC),
        )
        await _task(
            db, lead, telecaller, officer, TaskStatus.IN_PROGRESS, datetime(2026, 9, 2, tzinfo=UTC)
        )
        # A later cancelled task and a later unassigned one do not replace the Officer.
        await _task(
            db,
            lead,
            telecaller,
            cancelled_officer,
            TaskStatus.CANCELLED,
            datetime(2026, 9, 3, tzinfo=UTC),
        )
        await _task(
            db, lead, telecaller, None, TaskStatus.UNASSIGNED, datetime(2026, 9, 4, tzinfo=UTC)
        )
        await db.commit()
        staff_mobiles = []
        for staff in (telecaller, officer):
            await db.refresh(staff, ["user"])
            staff_mobiles.append(staff.user.mobile)
        return {
            "agent": agent,
            "other": other,
            "lead": lead,
            "waiting": waiting,
            "product": product,
            "telecaller": telecaller,
            "officer": officer,
            "staff_mobiles": staff_mobiles,
        }


def _expect_assigned(body: dict, world: dict) -> None:
    assert body["product_label"] == world["product"].label
    assert body["telecaller"] == {
        "name": "Tara Caller",
        "role_label": "Telecaller",
        "staff_code": world["telecaller"].staff_code,
    }
    assert body["officer"] == {
        "name": "Olga Field",
        "role_label": "Officer",
        "staff_code": world["officer"].staff_code,
    }


async def test_agent_lead_reads_show_who_works_the_lead(client: AsyncClient) -> None:
    world = await _assigned_world()
    agent = world["agent"]
    headers = _headers(_agent_token(str(agent.auth_user_uuid), str(agent.id)))

    res = await client.get("/api/v1/agent/leads", headers=headers)
    assert res.status_code == 200, res.text
    by_id = {row["id"]: row for row in res.json()}
    _expect_assigned(by_id[str(world["lead"].id)], world)
    waiting = by_id[str(world["waiting"].id)]
    assert waiting["telecaller"] is None
    assert waiting["officer"] is None
    assert waiting["product_label"] is None

    detail = await client.get(f"/api/v1/agent/leads/{world['lead'].id}", headers=headers)
    assert detail.status_code == 200, detail.text
    _expect_assigned(detail.json(), world)

    for text in (res.text, detail.text):
        for mobile in world["staff_mobiles"]:
            assert mobile not in text
        assert str(world["telecaller"].id) not in text
        assert str(world["officer"].id) not in text
        assert "Omar" not in text and "Carl" not in text


async def test_assigned_staff_ignore_the_history_staff_name_rule(client: AsyncClient) -> None:
    world = await _assigned_world()
    agent = world["agent"]
    headers = _headers(_agent_token(str(agent.auth_user_uuid), str(agent.id)))
    async with _agent_rules(("lead_history", "staff_names")):
        res = await client.get(f"/api/v1/agent/leads/{world['lead'].id}", headers=headers)
        assert res.status_code == 200, res.text
        _expect_assigned(res.json(), world)


async def test_assignees_are_only_for_the_originating_agent_and_line(client: AsyncClient) -> None:
    world = await _assigned_world()
    other = world["other"]
    other_headers = _headers(_agent_token(str(other.auth_user_uuid), str(other.id)))
    res = await client.get(f"/api/v1/agent/leads/{world['lead'].id}", headers=other_headers)
    assert res.status_code == 404

    agent = world["agent"]
    lead_id = str(world["lead"].id)
    owner = {
        "app.role": "agent",
        "app.auth_user_uuid": str(agent.auth_user_uuid),
        "app.agent_profile_uuid": str(agent.id),
        "app.business_line": "loans",
    }
    sql = "SELECT * FROM agent_lead_assignees(ARRAY[CAST(:id AS uuid)])"
    (row,) = await _call_as(sql, {"id": lead_id}, owner)
    assert row.telecaller_staff_code == world["telecaller"].staff_code

    refused = (
        # Another Agent, a forged profile claim, the wrong line, another role.
        {
            **owner,
            "app.auth_user_uuid": str(other.auth_user_uuid),
            "app.agent_profile_uuid": str(other.id),
        },
        {**owner, "app.auth_user_uuid": str(other.auth_user_uuid)},
        {**owner, "app.business_line": "real_estate"},
        {**owner, "app.role": "telecaller"},
        {**owner, "app.agent_profile_uuid": ""},
    )
    for context in refused:
        assert await _call_as(sql, {"id": lead_id}, context) == []
