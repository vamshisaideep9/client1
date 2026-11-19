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

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.models.lead import Lead, LeadStatus
from app.models.property import Property, PropertySubtype
from app.schemas.agent import AgentLeadCreate, AgentLeadUpdate, normalise_lead_email
from app.services.lead_details import DetailActor, to_read
from app.tests.test_agent_api import (  # noqa: F401 — autouse fixture
    _agent_token,
    _isolate_eligible_telecallers,
    _seed_agent,
)
from conftest import unique_mobile


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
