"""Batch 2 (CS-028): Agent bulk lead submit (POST /api/v1/agent/leads/bulk).

- 1–200 parsed rows per call; more is a 422 before any work.
- Per row: mobile normalised to E.164, name / email / description checked,
  requirement text mapped to an active loan product (loans) or a property
  type (real estate); later repeats of a mobile are ``duplicate_in_file``.
- ``dry_run`` validates only: nothing is created and no attempt is recorded.
- A real submit sends each valid row through the single-introduction path in
  its own transaction: duplicates and own-expired numbers get the CS-024
  reasons and are recorded as attempts, exactly like a single submit.
- Rate limited per Agent profile (submit and dry run separately); one audit
  entry with counts only per real submit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.db.session as db_session
from app.core.config import settings
from app.models.audit_log import AuditAction, AuditLog
from app.models.lead import Lead
from app.models.lead_intake_attempt import LeadIntakeAttempt
from app.models.loan import LoanType
from app.models.user import User
from app.services.agent_lead_bulk import RequirementCatalogue, normalise_indian_mobile
from app.tests.test_agent_api import (  # noqa: F401 — autouse fixture
    _agent_token,
    _isolate_eligible_telecallers,
    _seed_agent,
)
from app.tests.test_agent_dashboard_refinements import _seed_expired_lead
from conftest import unique_mobile

URL = "/api/v1/agent/leads/bulk"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _spaced(mobile: str) -> str:
    digits = mobile.removeprefix("+91")
    return f"{digits[:5]} {digits[5:]}"


async def _seed_product() -> tuple[str, str]:
    slug = f"bulk-{uuid.uuid4().hex[:8]}"
    label = f"Bulk Loan {uuid.uuid4().hex[:6]}"
    async with db_session.AsyncSessionLocal() as db:
        db.add(LoanType(name=slug, label=label, active=True))
        await db.commit()
    return slug, label


async def _leads_for(mobiles: list[str]) -> list[Lead]:
    async with db_session.AsyncSessionLocal() as db:
        return list((await db.scalars(select(Lead).where(Lead.mobile.in_(mobiles)))).all())


async def _attempts(agent_uuid: str) -> list[LeadIntakeAttempt]:
    async with db_session.AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(LeadIntakeAttempt).where(
                        LeadIntakeAttempt.actor_uuid == uuid.UUID(agent_uuid)
                    )
                )
            ).all()
        )


async def _register(mobile: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(
            User(
                first_name="Already",
                last_name="Registered",
                mobile=mobile,
                email=f"bulk_{uuid.uuid4().hex[:12]}@example.com",
                password_hash="x",
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+919876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("9876543210", "+919876543210"),
        ("98765 43210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
        ("(98765) 43.210", "+919876543210"),
        (9876543210, "+919876543210"),
        (919876543210, "+919876543210"),
        ("5876543210", None),  # Indian mobiles start 6-9
        ("98765432", None),
        ("+449876543210", None),
        ("09876543210", None),
        ("98765432101", None),
        ("９８７６５４３２１０", None),  # full-width digits
        ("", None),
        (None, None),
    ],
)
def test_mobile_normalisation(raw: object, expected: str | None) -> None:
    assert normalise_indian_mobile(raw) == expected  # type: ignore[arg-type]


def test_requirement_matching_per_line() -> None:
    home = LoanType(name="home-loan", label="Home Loan")
    car = LoanType(name="car-loan", label="Car Loan")
    loans = RequirementCatalogue("loans", [home, car])
    assert loans.match("home loan").requirement == {"product_slug": "home-loan"}
    assert loans.match("HOME-LOAN").label == "Home Loan"
    assert loans.match("  Car   Loan ").requirement == {"product_slug": "car-loan"}
    for wrong in ("Villa", "Gold loan", "home"):
        with pytest.raises(ValueError):
            loans.match(wrong)

    property_types = RequirementCatalogue("real_estate", [])
    assert property_types.match("Villas").requirement == {"property_type": "villa"}
    assert property_types.match("gated_community_apartment").label == ("Gated community apartment")
    assert property_types.match("Locked commercial space").requirement == {
        "property_type": "locked_space"
    }
    assert property_types.match("individual houses").requirement == {
        "property_type": "individual_house"
    }
    for wrong in ("Home Loan", "castle", "3 BHK"):
        with pytest.raises(ValueError):
            property_types.match(wrong)


def test_ambiguous_product_labels_need_the_product_code() -> None:
    first = LoanType(name="bl-a", label="Business Loan")
    second = LoanType(name="bl-b", label="Business Loan")
    loans = RequirementCatalogue("loans", [first, second])
    with pytest.raises(ValueError, match="more than one"):
        loans.match("Business loan")
    assert loans.match("bl-b").requirement == {"product_slug": "bl-b"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_validates_without_creating_or_recording(client: AsyncClient) -> None:
    slug, label = await _seed_product()
    auth_uuid, agent_uuid = await _seed_agent("loans")
    good, registered, wrong_line, too_long = (unique_mobile() for _ in range(4))
    await _register(registered)
    rows = [
        {"sno": 1, "name": "Good", "mobile": _spaced(good), "requirement": label},
        {"sno": "2", "name": "", "mobile": "12345", "email": "nope"},
        {"sno": 3, "name": "Repeat", "mobile": good},
        {"sno": 4, "name": "Wrong line", "mobile": wrong_line, "requirement": "Villa"},
        {"sno": 5, "name": "Too long", "mobile": too_long, "description": "x" * 1001},
        {"name": "Registered elsewhere", "mobile": int(registered.removeprefix("+"))},
    ]
    res = await client.post(
        URL,
        json={"dry_run": True, "rows": rows},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    outcomes = [row["outcome"] for row in body["rows"]]
    assert outcomes == [
        "ready",
        "invalid",
        "duplicate_in_file",
        "invalid",
        "invalid",
        "ready",
    ]
    first, second, third, fourth, fifth, sixth = body["rows"]
    assert first["sno"] == "1" and first["mobile"] == good
    assert first["requirement_label"] == label
    assert {error["field"] for error in second["errors"]} == {"name", "mobile", "email"}
    assert second["mobile"] is None
    assert third["duplicate_of_row_index"] == 0
    assert [error["field"] for error in fourth["errors"]] == ["requirement"]
    assert [error["field"] for error in fifth["errors"]] == ["description"]
    # A dry run never checks who holds a number: the registered one reads ready.
    assert sixth["mobile"] == registered
    assert body["totals"] == {
        "rows": 6,
        "ready": 2,
        "created": 0,
        "already_introduced": 0,
        "duplicate": 0,
        "not_eligible": 0,
        "duplicate_in_file": 1,
        "invalid": 3,
        "unavailable": 0,
    }
    assert await _leads_for([good, registered, wrong_line, too_long]) == []
    assert await _attempts(agent_uuid) == []
    assert slug


@pytest.mark.asyncio
async def test_submit_reports_every_outcome_like_single_submit(client: AsyncClient) -> None:
    slug, label = await _seed_product()
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    new_mobile, registered = unique_mobile(), unique_mobile()
    await _register(registered)
    existing = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": (own := unique_mobile()), "name": "Already mine"},
        headers=headers,
    )
    assert existing.status_code == 201, existing.text
    _expired_id, expired_mobile = await _seed_expired_lead(agent_uuid)
    started = datetime.now(UTC)

    rows = [
        {
            "sno": "A1",
            "name": "  New Person ",
            "mobile": _spaced(new_mobile),
            "email": "New.Person@Example.com",
            "requirement": slug,
            "description": "Wants a home loan",
        },
        {"sno": "A2", "name": "Taken", "mobile": registered},
        {"sno": "A3", "name": "Bad", "mobile": "000"},
        {"sno": "A4", "name": "Again", "mobile": new_mobile.removeprefix("+")},
        {"sno": "A5", "name": "Already mine", "mobile": own},
        {"sno": "A6", "name": "Expired", "mobile": expired_mobile},
    ]
    res = await client.post(URL, json={"dry_run": False, "rows": rows}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    created, duplicate, invalid, in_file, mine, expired = body["rows"]

    assert created["outcome"] == "created" and created["lead_id"]
    assert created["requirement_label"] == label
    assert duplicate["outcome"] == "duplicate"
    assert duplicate["reason"] == "already_linked"
    assert duplicate["reason_label"] == "Already registered or linked to an existing enquiry"
    assert duplicate["lead_id"] is None
    assert invalid["outcome"] == "invalid"
    assert in_file["outcome"] == "duplicate_in_file"
    assert mine["outcome"] == "already_introduced"
    assert mine["lead_id"] == existing.json()["id"]
    assert expired["outcome"] == "not_eligible"
    assert expired["reason"] == "own_lead_window_ended"
    assert expired["reason_label"] == "Your earlier lead for this number expired"
    assert body["totals"]["created"] == 1
    assert body["totals"]["rows"] == 6

    [lead] = await _leads_for([new_mobile])
    assert lead.name == "New Person"
    assert lead.origin_agent_profile_uuid == uuid.UUID(agent_uuid)
    assert lead.requirement == {
        "email": "new.person@example.com",
        "notes": "Wants a home loan",
        "product_slug": slug,
        "interest_title": label,
    }
    # Rejections are recorded exactly as a single submit records them.
    reasons = sorted(attempt.reason_code for attempt in await _attempts(agent_uuid))
    assert reasons == ["already_linked", "own_lead_window_ended"]

    async with db_session.AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.AGENT_LEADS_BULK_SUBMITTED,
                AuditLog.entity_uuid == uuid.UUID(agent_uuid),
                AuditLog.created_at >= started,
            )
        )
    assert audit is not None
    assert audit.actor_uuid == uuid.UUID(auth_uuid)
    assert audit.detail == body["totals"]
    flattened = str(audit.detail)
    for secret in (new_mobile, registered, "new.person@example.com", "New Person"):
        assert secret not in flattened


@pytest.mark.asyncio
async def test_one_failing_row_does_not_roll_back_the_others(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.agent as agent_service

    auth_uuid, agent_uuid = await _seed_agent("loans")
    first, broken, last = unique_mobile(), unique_mobile(), unique_mobile()
    original = agent_service.capture_agent_lead_with_outcome

    async def _flaky(**kwargs):  # noqa: ANN003, ANN202
        if kwargs["mobile"] == broken:
            raise RuntimeError("simulated database failure")
        return await original(**kwargs)

    monkeypatch.setattr(agent_service, "capture_agent_lead_with_outcome", _flaky)
    res = await client.post(
        URL,
        json={
            "dry_run": False,
            "rows": [
                {"name": "First", "mobile": first},
                {"name": "Broken", "mobile": broken},
                {"name": "Last", "mobile": last},
            ],
        },
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 200, res.text
    assert [row["outcome"] for row in res.json()["rows"]] == ["created", "unavailable", "created"]
    stored = {lead.mobile for lead in await _leads_for([first, broken, last])}
    assert stored == {first, last}


@pytest.mark.asyncio
async def test_wrong_line_requirements_are_invalid(client: AsyncClient) -> None:
    loans_auth, loans_agent = await _seed_agent("loans")
    res = await client.post(
        URL,
        json={
            "dry_run": True,
            "rows": [{"name": "A", "mobile": unique_mobile(), "requirement": "Villa"}],
        },
        headers=_headers(_agent_token(loans_auth, loans_agent)),
    )
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0]["outcome"] == "invalid"

    slug, label = await _seed_product()
    re_auth, re_agent = await _seed_agent("real_estate")
    re_headers = _headers(_agent_token(re_auth, re_agent, "real_estate"))
    res = await client.post(
        URL,
        json={
            "dry_run": True,
            "rows": [
                {"name": "B", "mobile": unique_mobile(), "requirement": label},
                {"name": "C", "mobile": unique_mobile(), "requirement": slug},
                {"name": "D", "mobile": unique_mobile(), "requirement": "Villas"},
            ],
        },
        headers=re_headers,
    )
    assert res.status_code == 200, res.text
    rows = res.json()["rows"]
    assert [row["outcome"] for row in rows] == ["invalid", "invalid", "ready"]
    assert rows[2]["requirement_label"] == "Villa"

    # Submitted for real, the property type lands on the lead with its label.
    mobile = unique_mobile()
    res = await client.post(
        URL,
        json={"dry_run": False, "rows": [{"name": "E", "mobile": mobile, "requirement": "plot"}]},
        headers=re_headers,
    )
    assert res.json()["rows"][0]["outcome"] == "created", res.text
    [lead] = await _leads_for([mobile])
    assert lead.requirement == {"property_type": "plot", "property_type_label": "Plot"}


@pytest.mark.asyncio
async def test_more_than_200_rows_or_unknown_columns_are_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "AGENT_LEAD_BULK_SUBMITS_PER_HOUR", 1)
    monkeypatch.setattr(settings, "AGENT_LEAD_BULK_DRY_RUNS_PER_HOUR", 1)
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    mobiles = [unique_mobile() for _ in range(201)]
    too_many = await client.post(
        URL,
        json={"dry_run": False, "rows": [{"name": "N", "mobile": m} for m in mobiles]},
        headers=headers,
    )
    assert too_many.status_code == 422, too_many.text
    assert await _leads_for(mobiles) == []

    for body in (
        {"dry_run": False, "rows": []},
        {"rows": [{"name": "N", "mobile": unique_mobile()}]},
        {"dry_run": True, "rows": [{"name": "N", "mobile": unique_mobile(), "pan": "X"}]},
    ):
        res = await client.post(URL, json=body, headers=headers)
        assert res.status_code == 422, res.text

    # Rejected before any work: neither hourly budget (1 each here) was used.
    for dry_run in (False, True):
        res = await client.post(
            URL,
            json={"dry_run": dry_run, "rows": [{"name": "N", "mobile": unique_mobile()}]},
            headers=headers,
        )
        assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_bulk_submits_are_rate_limited_per_agent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "AGENT_LEAD_BULK_SUBMITS_PER_HOUR", 2)
    monkeypatch.setattr(settings, "AGENT_LEAD_BULK_DRY_RUNS_PER_HOUR", 1)
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))

    def _body(dry_run: bool) -> dict:
        return {"dry_run": dry_run, "rows": [{"name": "R", "mobile": unique_mobile()}]}

    assert (await client.post(URL, json=_body(False), headers=headers)).status_code == 200
    assert (await client.post(URL, json=_body(False), headers=headers)).status_code == 200
    limited = await client.post(URL, json=_body(False), headers=headers)
    assert limited.status_code == 429, limited.text
    # Dry runs have their own budget.
    assert (await client.post(URL, json=_body(True), headers=headers)).status_code == 200
    assert (await client.post(URL, json=_body(True), headers=headers)).status_code == 429

    # Another Agent is unaffected.
    other_auth, other_agent = await _seed_agent("loans")
    other = await client.post(
        URL, json=_body(False), headers=_headers(_agent_token(other_auth, other_agent))
    )
    assert other.status_code == 200, other.text


@pytest.mark.asyncio
async def test_only_agents_may_bulk_submit(client: AsyncClient) -> None:
    from app.models.profile import StaffRole
    from app.tests.contest_support import headers, seed_staff, token_for

    user, profile = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    res = await client.post(
        URL,
        json={"dry_run": True, "rows": [{"name": "X", "mobile": unique_mobile()}]},
        headers=headers(
            token_for(user, "telecaller", business_line="loans", staff_profile=profile)
        ),
    )
    assert res.status_code == 403, res.text
