"""Public lead endpoint tests (docs/specs/public-leads-endpoint.md).

Covers: classified insert, enrich-on-conflict, validation rejects, per-mobile
rate cap, and honeypot drop.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text

import app.db.session as db_session
from app.cache.redis_keys import lead_rate_ip_key, lead_rate_mobile_key
from app.core.config import settings
from app.models.chat_inquiry import ChatInquiry
from app.models.lead import Lead
from app.models.user import User
from app.tests.test_leads_rls import _seed_telecaller_staff_profile
from conftest import unique_email, unique_mobile

# ASGITransport stamps every request with this client host.
_TEST_IP = "127.0.0.1"
_CHAT_PATH = "/api/v1/leads/chat-inquiries"


def _chat_payload(**overrides) -> dict:
    return {
        "name": "Test Visitor",
        "mobile": unique_mobile(),
        "idempotency_key": str(uuid.uuid4()),
        "flow": "residential",
        "action": "visit",
        "answers": ["Buy property", "Independent villa", "Under ₹60 lakh"],
        "location": "Test locality",
        **overrides,
    }


def _payload(mobile: str | None = None, **overrides) -> dict:
    base = {
        "name": "Test Visitor",
        "mobile": mobile or unique_mobile(),
        "topic": "loans",
        "origin": "contact",
    }
    base.update(overrides)
    return base


async def _get_lead(mobile: str) -> Lead | None:
    # Attribute access at call time, not from-import: conftest swaps in a
    # NullPool sessionmaker per test session (see _patch_db_null_pool).
    async with db_session.AsyncSessionLocal() as session:
        return await session.scalar(select(Lead).where(Lead.mobile == mobile))


async def _seed_property(*, active: bool) -> str:
    from app.models.property import Property

    async with db_session.AsyncSessionLocal() as session:
        property_listing = Property(
            business_line="real_estate",
            active=active,
            title="Canonical Public Villa",
            type="Villa",
            location="Jubilee Hills, Hyderabad",
            price_display="₹2 Cr",
            category="villas",
            city="Hyderabad",
            locality="Jubilee Hills",
            pincode="500033",
            price_paise=2_000_000_000,
            bhk=4,
            area_sqft=2600,
            amenities=[],
            age_years=0,
            rera_applicability="unsure",
            rera_verification_status="not_reviewed",
            details={},
        )
        session.add(property_listing)
        await session.commit()
        return str(property_listing.id)


async def _delete_property(property_id: str) -> None:
    from app.models.property import Property

    async with db_session.AsyncSessionLocal() as session:
        await session.execute(delete(Property).where(Property.id == uuid.UUID(property_id)))
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_ip_window():
    """Every test shares the ASGI test IP; isolate the per-IP counter."""
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.delete(lead_rate_ip_key(_TEST_IP))
    try:
        yield
    finally:
        await r.delete(lead_rate_ip_key(_TEST_IP))
        await r.aclose()


async def test_create_lead_persists_row(client: AsyncClient) -> None:
    mobile = unique_mobile()
    resp = await client.post(
        "/api/v1/leads",
        json=_payload(mobile, product="Personal Loan", message="Need 5 lakh"),
    )
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}

    lead = await _get_lead(mobile)
    assert lead is not None
    assert lead.name == "Test Visitor"
    assert lead.business_line == "loans"
    assert lead.requirement["page"] == "contact"
    assert lead.requirement["product"] == "Personal Loan"
    assert lead.requirement["message"] == "Need 5 lakh"


async def test_chat_concurrent_retry_and_assigned_lead_are_preserved(client: AsyncClient) -> None:
    payload = _chat_payload()
    staff = await _seed_telecaller_staff_profile("real_estate")
    async with db_session.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=payload["mobile"],
            name="Previously assigned",
            origin="direct",
            status="assigned",
            business_line="real_estate",
            assigned_telecaller_profile_uuid=uuid.UUID(staff),
            requirement={"notes": "Existing notes"},
        )
        db.add(lead)
        await db.commit()
        lead_id = lead.id

    first, duplicate = await asyncio.gather(
        client.post(_CHAT_PATH, json=payload), client.post(_CHAT_PATH, json=payload)
    )
    assert first.status_code == duplicate.status_code == 201
    assert first.json() == duplicate.json()
    reference = uuid.UUID(first.json()["reference"])
    new_request = await client.post(
        _CHAT_PATH, json={**payload, "idempotency_key": str(uuid.uuid4())}
    )
    assert new_request.status_code == 201
    assert new_request.json()["reference"] != str(reference)

    async with db_session.AsyncSessionLocal() as db:
        lead = await db.get(Lead, lead_id)
        assert lead is not None
        assert lead.name == "Previously assigned"
        assert lead.requirement == {"notes": "Existing notes"}
        assert str(lead.assigned_telecaller_profile_uuid) == staff
        inquiries = (
            await db.scalars(select(ChatInquiry).where(ChatInquiry.lead_id == lead_id))
        ).all()
        assert len(inquiries) == 2
        assert all(
            inquiry.preferences["What type of home do you prefer?"] == "Independent villa"
            for inquiry in inquiries
        )
        assert all(inquiry.location == "Test locality" for inquiry in inquiries)

    async with db_session.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        query = select(ChatInquiry.reference).where(ChatInquiry.lead_id == lead_id)
        await db.execute(
            text(
                "SELECT set_config('app.role', 'telecaller', true), "
                "set_config('app.staff_profile_uuid', :staff, true), "
                "set_config('app.business_line', 'real_estate', true)"
            ),
            {"staff": staff},
        )
        assert len((await db.scalars(query)).all()) == 2
        await db.execute(text("SELECT set_config('app.business_line', 'loans', true)"))
        assert (await db.scalars(query)).all() == []
        await db.execute(
            text(
                "SELECT set_config('app.business_line', 'real_estate', true), "
                "set_config('app.staff_profile_uuid', '', true)"
            )
        )
        assert (await db.scalars(query)).all() == []
        await db.execute(text("SELECT set_config('app.platform_scope', 'true', true)"))
        assert (await db.scalars(query)).all() == []
        await db.execute(text("SELECT set_config('app.role', 'admin', true)"))
        assert len((await db.scalars(query)).all()) == 2


async def test_chat_rejects_invalid_answers_without_echo(client: AsyncClient) -> None:
    invalid = _chat_payload()
    response = await client.post(_CHAT_PATH, json={**invalid, "answers": ["arbitrary"] * 3})
    assert response.status_code == 422
    assert "arbitrary" not in response.text
    response = await client.post(_CHAT_PATH, json={**invalid, "mobile": "private input"})
    assert response.status_code == 422
    assert "private input" not in response.text
    assert await _get_lead(invalid["mobile"]) is None


async def test_account_erasure_removes_chat_contact_details(client: AsyncClient) -> None:
    payload = _chat_payload()
    async with db_session.AsyncSessionLocal() as db:
        account = User(
            first_name="Test",
            last_name="Visitor",
            email=unique_email(),
            mobile=payload["mobile"],
            password_hash="unused",
        )
        db.add(account)
        await db.commit()
        account_id = account.id

    response = await client.post(_CHAT_PATH, json=payload)
    assert response.status_code == 201
    reference = uuid.UUID(response.json()["reference"])
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        await db.execute(
            text("SELECT set_config('app.auth_user_uuid', :owner, true)"),
            {"owner": str(account_id)},
        )
        await db.scalar(select(func.erase_account_chat_inquiries(account_id)))
        await db.commit()

    async with db_session.AsyncSessionLocal() as db:
        assert await db.get(ChatInquiry, reference) is None


async def test_chat_catalog_respects_publication_and_credit_card_slug(client: AsyncClient) -> None:
    from app.models.loan import LoanType

    async with db_session.AsyncSessionLocal() as db:
        products = (
            await db.scalars(
                select(LoanType).where(LoanType.name.in_(["credit-cards", "health-insurance"]))
            )
        ).all()
        assert {p.name for p in products} == {"credit-cards", "health-insurance"}
        original = {
            p.id: (p.active, p.public_visible, p.public_summary, p.public_description)
            for p in products
        }
        for product in products:
            product.active = True
            product.public_visible = product.name == "credit-cards"
            product.public_summary = "Test summary"
            product.public_description = "Test description"
        await db.commit()
    try:
        response = await client.get(f"{_CHAT_PATH}/flows")
        assert response.status_code == 200
        flows = {item["id"]: item for item in response.json()}
        assert flows["credit-card"]["browse_href"] == "/loans/credit-card"
        assert "health-insurance" not in flows
        assert all(len(item["questions"]) == 3 for item in flows.values())
        response = await client.post(
            _CHAT_PATH,
            json=_chat_payload(
                flow="health-insurance", action="quote", answers=["Not sure yet"] * 3
            ),
        )
        assert response.status_code == 422
    finally:
        async with db_session.AsyncSessionLocal() as db:
            for product_id, fields in original.items():
                product = await db.get(LoanType, product_id)
                (
                    product.active,
                    product.public_visible,
                    product.public_summary,
                    product.public_description,
                ) = fields
            await db.commit()


async def test_property_lead_uses_canonical_listing_facts(client: AsyncClient) -> None:
    property_id = await _seed_property(active=True)
    mobile = unique_mobile()
    try:
        resp = await client.post(
            "/api/v1/leads",
            json=_payload(
                mobile,
                topic="real_estate",
                property_ref=property_id,
                product="Spoofed browser title",
            ),
        )
        assert resp.status_code == 202

        lead = await _get_lead(mobile)
        assert lead is not None
        assert lead.requirement["property_ref"] == property_id
        assert lead.requirement["property_title"] == "Canonical Public Villa"
        assert lead.requirement["property_location"] == "Jubilee Hills, Hyderabad"
        assert lead.requirement["product"] == ("Canonical Public Villa, Jubilee Hills, Hyderabad")
    finally:
        await _delete_property(property_id)


async def test_inactive_property_lead_stays_non_enumerating(client: AsyncClient) -> None:
    property_id = await _seed_property(active=False)
    mobile = unique_mobile()
    try:
        resp = await client.post(
            "/api/v1/leads",
            json=_payload(
                mobile,
                topic="real_estate",
                property_ref=property_id,
                product="Hidden title",
            ),
        )
        assert resp.status_code == 202
        lead = await _get_lead(mobile)
        assert lead is not None
        assert "property_ref" not in lead.requirement
        assert "product" not in lead.requirement
    finally:
        await _delete_property(property_id)


async def test_create_lead_enriches_open_existing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.leads as leads_service

    async def no_assignment(*_args, **_kwargs):
        return None

    monkeypatch.setattr(leads_service, "auto_assign_locked_lead", no_assignment)
    mobile = unique_mobile()
    assert (
        await client.post("/api/v1/leads", json=_payload(mobile, topic="loans"))
    ).status_code == 202
    # A second same-line request enriches the open, unassigned workflow.
    resp = await client.post(
        "/api/v1/leads",
        json=_payload(
            mobile,
            topic="loans",
            email="visitor@example.com",
            message="Call after 6pm",
        ),
    )
    assert resp.status_code == 202

    lead = await _get_lead(mobile)
    assert lead is not None
    assert lead.business_line == "loans"
    assert lead.requirement["email"] == "visitor@example.com"
    assert lead.requirement["message"] == "Call after 6pm"


@pytest.mark.parametrize(
    "bad",
    [
        {"mobile": "98765"},  # not E.164
        {"topic": "crypto"},  # outside whitelist
        {"topic": "agent"},  # partner enquiries are not operational leads
        {"origin": "https://evil.example"},  # outside whitelist
        {"name": ""},  # blank
        {"message": "x" * 1001},  # over cap
    ],
)
async def test_create_lead_validation_rejects(client: AsyncClient, bad: dict) -> None:
    resp = await client.post("/api/v1/leads", json=_payload(**bad))
    assert resp.status_code == 422


async def test_per_mobile_cap_trips(client: AsyncClient) -> None:
    mobile = unique_mobile()
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    original = settings.LEAD_RATE_LIMIT_PER_MOBILE
    settings.LEAD_RATE_LIMIT_PER_MOBILE = 2
    try:
        assert (await client.post("/api/v1/leads", json=_payload(mobile))).status_code == 202
        assert (await client.post("/api/v1/leads", json=_payload(mobile))).status_code == 202
        assert (await client.post("/api/v1/leads", json=_payload(mobile))).status_code == 429
    finally:
        settings.LEAD_RATE_LIMIT_PER_MOBILE = original
        await r.delete(lead_rate_mobile_key(mobile))
        await r.aclose()


async def test_honeypot_answers_202_without_writing(client: AsyncClient) -> None:
    mobile = unique_mobile()
    resp = await client.post(
        "/api/v1/leads", json=_payload(mobile, company="Definitely A Real Business Ltd")
    )
    assert resp.status_code == 202
    assert await _get_lead(mobile) is None
