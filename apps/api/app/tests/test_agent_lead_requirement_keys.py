"""Batch 2 (CS-028): Agent lead form fields.

The Agent lead form now records an optional email and, on the real-estate
line, a property type. Both live under ``requirement.*`` so the detail-
ownership ledger, Admin field visibility and the existing reads apply:

- ``requirement.email``: optional, trimmed, lower-cased, at most 254 chars;
  the originating Agent may change or remove it while the lead is editable;
  only a platform Admin's lead-details read carries it.
- ``requirement.property_type`` (+ ``property_type_label`` snapshot): a
  ``PropertySubtype`` value, real-estate Agents only; it may sit beside a
  specific listing (they must agree) but never beside a loan product.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from app.models.lead import Lead, LeadStatus
from app.models.property import Property, PropertySubtype
from app.schemas.agent import AgentLeadCreate, AgentLeadUpdate, normalise_lead_email
from app.services.lead_details import DetailActor, to_read, visible_requirement
from app.tests.test_agent_api import (  # noqa: F401 — autouse fixture
    _agent_token,
    _isolate_eligible_telecallers,
    _seed_agent,
)
from conftest import full_registration, unique_mobile


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_property(subtype: PropertySubtype | None) -> str:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        listing = Property(
            business_line="real_estate",
            active=True,
            title=f"Lead form villa {uuid.uuid4().hex[:6]}",
            type="Villa",
            location="Gachibowli, Hyderabad",
            price_display="₹1.2 Cr",
            category="villas",
            property_subtype=subtype,
            city="Hyderabad",
            locality="Gachibowli",
            pincode="500032",
            price_paise=1_200_000_000,
            bhk=3,
            area_sqft=1800,
            amenities=[],
            age_years=0,
            rera_applicability="unsure",
            rera_verification_status="not_reviewed",
            details={},
        )
        db.add(listing)
        await db.commit()
        return str(listing.id)


async def _load_lead(lead_id: str) -> Lead:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        return lead


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _create(requirement: dict) -> AgentLeadCreate:
    return AgentLeadCreate(mobile="+919876543210", name="Ravi", requirement=requirement)


def test_email_is_trimmed_lower_cased_and_optional() -> None:
    assert _create({"email": "  Ravi.Kumar@Example.COM "}).requirement == {
        "email": "ravi.kumar@example.com"
    }
    # Blank or null means "no email"; an empty requirement collapses to None.
    assert _create({"email": "   "}).requirement is None
    assert _create({"email": None, "notes": "Call after 6"}).requirement == {
        "notes": "Call after 6"
    }
    assert normalise_lead_email(None) is None


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "a@b", "two@@example.com", 42, f"{'a' * 250}@example.com"],
)
def test_invalid_email_is_rejected(email: object) -> None:
    with pytest.raises(ValidationError):
        _create({"email": email})


def test_property_type_must_be_a_known_subtype() -> None:
    assert _create({"property_type": " Villa "}).requirement == {"property_type": "villa"}
    for bad in ("castle", "", 3, "villa house"):
        with pytest.raises(ValidationError):
            _create({"property_type": bad})
    # Null means "no property type".
    assert _create({"property_type": None, "notes": "x"}).requirement == {"notes": "x"}


def test_property_fields_and_product_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="not both"):
        _create({"product_slug": "home-loan", "property_type": "villa"})
    with pytest.raises(ValidationError, match="not both"):
        _create({"product_slug": "home-loan", "property_id": str(uuid.uuid4())})
    # A specific listing may sit beside a property type.
    property_id = str(uuid.uuid4())
    assert _create({"property_id": property_id, "property_type": "plot"}).requirement == {
        "property_id": property_id,
        "property_type": "plot",
    }


def test_unknown_requirement_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="may only contain"):
        _create({"budget": "1 crore"})
    with pytest.raises(ValidationError, match="may only contain"):
        _create({"property_type_label": "Villa"})


def test_agent_update_may_change_only_notes_and_email() -> None:
    assert AgentLeadUpdate(requirement={"email": " A@B.co "}).requirement == {"email": "a@b.co"}
    assert AgentLeadUpdate(requirement={"email": None}).requirement == {"email": None}
    assert AgentLeadUpdate(requirement={"notes": "x", "email": "a@b.co"}).requirement
    for body in ({"property_type": "villa"}, {"product_slug": "x"}, {}, {"email": "bad"}):
        with pytest.raises(ValidationError):
            AgentLeadUpdate(requirement=body)


def test_lead_details_read_shows_email_only_to_admin() -> None:
    now = datetime.now(UTC)
    lead = Lead(
        id=uuid.uuid4(),
        mobile="+919876543210",
        business_line="real_estate",
        status=LeadStatus.NEW,
        name="Ravi",
        requirement={
            "notes": "Weekend visit",
            "email": "ravi@example.com",
            "property_type": "villa",
            "property_type_label": "Villa",
            "property_id": str(uuid.uuid4()),
        },
        detail_ownership={},
        updated_at=now,
    )
    admin = to_read(lead, DetailActor("admin", uuid.uuid4(), uuid.uuid4()))
    client = to_read(lead, DetailActor("client", uuid.uuid4(), uuid.uuid4()))
    assert admin.requirement == {
        "notes": "Weekend visit",
        "email": "ravi@example.com",
        "property_type": "villa",
        "property_type_label": "Villa",
    }
    assert client.requirement == {
        "notes": "Weekend visit",
        "property_type": "villa",
        "property_type_label": "Villa",
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loans_agent_records_email_and_product(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.loan import LoanType

    slug = f"lead-form-{uuid.uuid4().hex[:8]}"
    async with _session_mod.AsyncSessionLocal() as db:
        db.add(LoanType(name=slug, label="Lead Form Home Loan", active=True))
        await db.commit()
    auth_uuid, agent_uuid = await _seed_agent("loans")
    res = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Ravi Kumar",
            "requirement": {
                "email": "Ravi.K@Example.com",
                "product_slug": slug,
                "notes": "Needs 40 lakh",
            },
        },
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 201, res.text
    requirement = res.json()["requirement"]
    assert requirement["email"] == "ravi.k@example.com"
    assert requirement["interest_title"] == "Lead Form Home Loan"
    assert requirement["notes"] == "Needs 40 lakh"

    lead = await _load_lead(res.json()["id"])
    assert lead.detail_ownership["requirement.email"] == {
        "role": "agent",
        "subject_uuid": agent_uuid,
    }


@pytest.mark.asyncio
async def test_real_estate_agent_records_property_type(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("real_estate")
    headers = _headers(_agent_token(auth_uuid, agent_uuid, "real_estate"))
    res = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Meera",
            "requirement": {"property_type": "gated_community_apartment"},
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["requirement"] == {
        "property_type": "gated_community_apartment",
        "property_type_label": "Gated community apartment",
    }
    lead = await _load_lead(res.json()["id"])
    assert lead.detail_ownership["requirement.property_type"]["role"] == "agent"
    assert lead.detail_ownership["requirement.property_type_label"]["role"] == "agent"


@pytest.mark.asyncio
async def test_property_type_with_listing_must_agree(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("real_estate")
    headers = _headers(_agent_token(auth_uuid, agent_uuid, "real_estate"))
    villa = await _seed_property(PropertySubtype.VILLA)

    mismatch = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Mismatch",
            "requirement": {"property_id": villa, "property_type": "plot"},
        },
        headers=headers,
    )
    assert mismatch.status_code == 422, mismatch.text

    match = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Match",
            "requirement": {"property_id": villa, "property_type": "villa"},
        },
        headers=headers,
    )
    assert match.status_code == 201, match.text
    body = match.json()["requirement"]
    assert body["property_type_label"] == "Villa"
    assert body["interest_title"].startswith("Lead form villa")


@pytest.mark.asyncio
async def test_loans_agent_cannot_name_a_property_type(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    res = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Wrong line",
            "requirement": {"property_type": "villa"},
        },
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_agent_edits_and_removes_their_lead_email(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    created = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": unique_mobile(),
            "name": "Editable",
            "requirement": {"notes": "First note", "email": "old@example.com"},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]

    changed = await client.patch(
        f"/api/v1/agent/leads/{lead_id}",
        json={"requirement": {"email": " New@Example.com "}},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["requirement"]["email"] == "new@example.com"
    # Editing only the email leaves the notes alone.
    assert changed.json()["requirement"]["notes"] == "First note"

    removed = await client.patch(
        f"/api/v1/agent/leads/{lead_id}",
        json={"requirement": {"email": None}},
        headers=headers,
    )
    assert removed.status_code == 200, removed.text
    assert "email" not in removed.json()["requirement"]

    fixed = await client.patch(
        f"/api/v1/agent/leads/{lead_id}",
        json={"requirement": {"product_slug": "anything"}},
        headers=headers,
    )
    assert fixed.status_code == 422, fixed.text


# ---------------------------------------------------------------------------
# Requirement visibility by role (one shared allowlist: visible_requirement)
# ---------------------------------------------------------------------------


def _mixed_lead(agent_uuid: uuid.UUID) -> Lead:
    agent = {"role": "agent", "subject_uuid": str(agent_uuid)}
    return Lead(
        id=uuid.uuid4(),
        mobile="+919876543210",
        business_line="loans",
        status=LeadStatus.ASSIGNED,
        requirement={
            "notes": "Agent note",
            "email": "person@example.com",
            "product_slug": "home-loan",
            "interest_title": "Home Loan",
            "message": "Public form message",
            "page": "home",
            "budget": "legacy free text",
        },
        detail_ownership={
            "requirement.notes": agent,
            "requirement.email": agent,
            "requirement.product_slug": agent,
            "requirement.interest_title": agent,
            "requirement.message": {"role": "unclaimed", "subject_uuid": None},
            "requirement.page": {"role": "system", "subject_uuid": None},
            "requirement.budget": {"role": "legacy_locked", "subject_uuid": None},
        },
    )


def test_role_matrix_of_the_shared_requirement_allowlist() -> None:
    agent_uuid = uuid.uuid4()
    lead = _mixed_lead(agent_uuid)
    assert visible_requirement(lead, "agent", agent_profile_uuid=agent_uuid) == {
        "notes": "Agent note",
        "email": "person@example.com",
        "product_slug": "home-loan",
        "interest_title": "Home Loan",
    }
    # Another Agent, or an Agent read without a profile, owns nothing here.
    assert visible_requirement(lead, "agent", agent_profile_uuid=uuid.uuid4()) is None
    assert visible_requirement(lead, "agent") is None
    # The assigned Telecaller works with every known key; unknown keys never pass.
    assert visible_requirement(lead, "telecaller") == {
        "notes": "Agent note",
        "email": "person@example.com",
        "product_slug": "home-loan",
        "interest_title": "Home Loan",
        "message": "Public form message",
        "page": "home",
    }
    assert visible_requirement(lead, "admin") == {
        "notes": "Agent note",
        "email": "person@example.com",
        "interest_title": "Home Loan",
    }
    assert visible_requirement(lead, "client") == {
        "notes": "Agent note",
        "interest_title": "Home Loan",
    }


@pytest.mark.asyncio
async def test_legacy_ownership_backfill_preserves_the_originating_agents_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the original backfill against pre-ledger rows, then use today's read.

    The transaction-local table shadows leads; the rest of the historical
    migration's DDL is captured rather than reapplied to the current database.
    An existing public enquiry must not become readable merely when claimed.
    """
    import app.db.session as session_module

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    migration = ScriptDirectory.from_config(config).get_revision("bb23cc45dd67").module
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", lambda sql: statements.append(str(sql)))
    monkeypatch.setattr(migration.op, "add_column", lambda *_args, **_kwargs: None)
    migration.upgrade()
    [backfill] = [sql for sql in statements if sql.lstrip().startswith("UPDATE leads AS l")]

    agent_uuid = uuid.uuid4()
    async with session_module.AsyncSessionLocal() as db:
        await db.execute(
            text(
                "CREATE TEMP TABLE leads (id integer, name text, "
                "origin_agent_profile_uuid uuid, client_profile_uuid uuid, "
                "requirement jsonb, detail_ownership jsonb) ON COMMIT DROP"
            )
        )
        await db.execute(
            text(
                "INSERT INTO leads VALUES "
                "(1, 'Legacy introduction', :agent, NULL, CAST(:own AS jsonb), '{}'), "
                "(2, 'Public enquiry', NULL, NULL, CAST(:public AS jsonb), '{}')"
            ),
            {
                "agent": agent_uuid,
                "own": json.dumps(
                    {"notes": "Original Agent note", "budget": "Unknown legacy detail"}
                ),
                "public": json.dumps({"notes": "Public note", "email": "public@example.com"}),
            },
        )
        await db.execute(text(backfill))
        rows = (await db.execute(text("SELECT * FROM leads ORDER BY id"))).mappings().all()
        original = Lead(
            origin_agent_profile_uuid=agent_uuid,
            requirement=rows[0]["requirement"],
            detail_ownership=rows[0]["detail_ownership"],
        )
        assert visible_requirement(original, "agent", agent_profile_uuid=agent_uuid) == {
            "notes": "Original Agent note"
        }
        assert visible_requirement(original, "agent", agent_profile_uuid=uuid.uuid4()) is None
        # Claiming the row after the backfill does not transfer its old fields.
        claimed = Lead(
            origin_agent_profile_uuid=agent_uuid,
            requirement=rows[1]["requirement"],
            detail_ownership=rows[1]["detail_ownership"],
        )
        assert visible_requirement(claimed, "agent", agent_profile_uuid=agent_uuid) is None
        await db.rollback()


@pytest.mark.asyncio
async def test_claiming_agent_never_reads_keys_others_recorded(client: AsyncClient) -> None:
    """An Agent attaching to an existing open enquiry sees only what they wrote."""
    import app.db.session as _session_mod
    from app.models.loan import LoanType

    slug = f"claim-{uuid.uuid4().hex[:8]}"
    mobile = unique_mobile()
    async with _session_mod.AsyncSessionLocal() as db:
        db.add(LoanType(name=slug, label="Claim Loan", active=True))
        db.add(
            Lead(
                mobile=mobile,
                business_line="loans",
                origin="direct",
                status=LeadStatus.RELEASED,
                requirement={
                    "email": "client-entered@example.com",
                    "notes": "Telecaller note",
                    "message": "Please call after 6",
                    "page": "home-loan",
                },
                detail_ownership={
                    "requirement.email": {"role": "client", "subject_uuid": str(uuid.uuid4())},
                    "requirement.notes": {
                        "role": "telecaller",
                        "subject_uuid": str(uuid.uuid4()),
                    },
                    "requirement.message": {"role": "unclaimed", "subject_uuid": None},
                    "requirement.page": {"role": "system", "subject_uuid": None},
                },
            )
        )
        await db.commit()

    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    res = await client.post(
        "/api/v1/agent/leads",
        json={
            "mobile": mobile,
            "name": "Claimed",
            "requirement": {"email": "agent-typed@example.com", "product_slug": slug},
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    expected = {"product_slug": slug, "interest_title": "Claim Loan"}
    assert res.json()["requirement"] == expected
    listed = await client.get("/api/v1/agent/leads", headers=headers)
    row = next(item for item in listed.json() if item["id"] == res.json()["id"])
    assert row["requirement"] == expected
    detail = await client.get(f"/api/v1/agent/leads/{res.json()['id']}", headers=headers)
    assert detail.json()["requirement"] == expected
    # The client-owned email was neither shown nor overwritten.
    stored = await _load_lead(res.json()["id"])
    assert stored.requirement["email"] == "client-entered@example.com"


@pytest.mark.asyncio
async def test_email_reaches_assigned_telecaller_and_admin_only(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.profile import StaffRole
    from app.models.task import Task, TaskStatus, TaskType
    from app.tests.contest_support import headers, seed_staff, token_for

    email = f"lead-{uuid.uuid4().hex[:8]}@example.com"
    tc_user, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    other_user, other = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    emp_user, employee = await seed_staff(StaffRole.EMPLOYEE, business_line="loans")
    admin_user, admin_profile = await seed_staff(StaffRole.ADMIN)
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            name="Contactable",
            business_line="loans",
            origin="direct",
            status=LeadStatus.ASSIGNED,
            assigned_telecaller_profile_uuid=telecaller.id,
            requirement={"email": email, "message": "Call me"},
            detail_ownership={
                "requirement.email": {"role": "unclaimed", "subject_uuid": None},
                "requirement.message": {"role": "unclaimed", "subject_uuid": None},
            },
        )
        db.add(lead)
        await db.flush()
        task = Task(
            raised_by_staff_profile_uuid=telecaller.id,
            assigned_employee_profile_uuid=employee.id,
            business_line="loans",
            task_type=TaskType.DOCUMENT_COLLECTION,
            lead_uuid=lead.id,
            status=TaskStatus.ASSIGNED,
        )
        db.add(task)
        await db.commit()
        lead_id, task_id = str(lead.id), str(task.id)

    tc_headers = headers(
        token_for(tc_user, "telecaller", business_line="loans", staff_profile=telecaller)
    )
    detail = await client.get(f"/api/v1/telecaller/leads/{lead_id}", headers=tc_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["requirement"] == {"email": email, "message": "Call me"}
    listed = await client.get("/api/v1/telecaller/leads", headers=tc_headers)
    row = next(item for item in listed.json() if item["id"] == lead_id)
    assert row["requirement"]["email"] == email

    other_headers = headers(
        token_for(other_user, "telecaller", business_line="loans", staff_profile=other)
    )
    hidden = await client.get(f"/api/v1/telecaller/leads/{lead_id}", headers=other_headers)
    assert hidden.status_code == 404
    other_list = await client.get("/api/v1/telecaller/leads", headers=other_headers)
    assert email not in other_list.text

    emp_headers = headers(
        token_for(emp_user, "employee", business_line="loans", staff_profile=employee)
    )
    task_read = await client.get(f"/api/v1/employee/tasks/{task_id}", headers=emp_headers)
    assert task_read.status_code == 200, task_read.text
    assert email not in task_read.text

    admin_headers = headers(
        token_for(admin_user, "admin", platform_scope="true", staff_profile=admin_profile)
    )
    admin_read = await client.get(f"/api/v1/admin/leads/{lead_id}/details", headers=admin_headers)
    assert admin_read.status_code == 200, admin_read.text
    assert admin_read.json()["requirement"] == {"email": email}


@pytest.mark.asyncio
async def test_client_never_reads_the_email_on_their_journey(client: AsyncClient) -> None:
    from sqlalchemy import select

    import app.db.session as _session_mod

    token, mobile = await full_registration(client, lines=["loans"])
    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.scalar(
            select(Lead).where(Lead.mobile == mobile, Lead.business_line == "loans")
        )
        assert lead is not None
        lead.requirement = {"email": "client@example.com", "notes": "Own note"}
        await db.commit()

    res = await client.get(
        "/api/v1/client/lead-details/loans", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["requirement"] == {"notes": "Own note"}
    assert "client@example.com" not in res.text


@pytest.mark.asyncio
async def test_agent_cannot_edit_an_email_another_party_owns(client: AsyncClient) -> None:
    """The ledger still decides: an email recorded by someone else (here the
    public form, owned by the unclaimed enquiry) stays theirs."""
    import app.db.session as _session_mod

    auth_uuid, agent_uuid = await _seed_agent("loans")
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            name="Owned elsewhere",
            business_line="loans",
            origin="agent",
            origin_agent_profile_uuid=uuid.UUID(agent_uuid),
            status=LeadStatus.NEW,
            requirement={"email": "owner@example.com"},
            detail_ownership={
                "name": {"role": "agent", "subject_uuid": agent_uuid},
                "requirement.email": {"role": "client", "subject_uuid": str(uuid.uuid4())},
            },
        )
        db.add(lead)
        await db.commit()
        lead_id = str(lead.id)

    res = await client.patch(
        f"/api/v1/agent/leads/{lead_id}",
        json={"requirement": {"email": "agent@example.com"}},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 409, res.text
    assert (await _load_lead(lead_id)).requirement == {"email": "owner@example.com"}
