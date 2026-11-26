"""Lead reference numbers (LD-00000123): assignment, exposure, search and secrecy.

Requires running Postgres + Redis (the database-backed tests skip without
them; run them in the API container, never trust a host-side skip).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

import app.db.session as db_session
from app.core.lead_reference import format_lead_ref, parse_lead_ref
from app.models.lead import Lead
from app.tests.test_agent_api import (
    _agent_token,
    _isolate_eligible_telecallers,  # noqa: F401 — autouse fixture for this module
    _seed_agent,
)
from app.tests.test_commission_api import (
    _make_admin,
    _seed_lead,
)
from app.tests.test_commission_api import (
    _seed_loan_application as _seed_commission_loan,
)
from app.tests.test_commission_payout_api import _payout_body, _seed_commission
from app.tests.test_fee_cashback_api import _seed_loan_application as _seed_cashback_loan
from app.tests.test_telecaller_api import (
    _seed_assigned_lead,
    _seed_telecaller,
    _telecaller_token,
)
from conftest import unique_mobile

_REF = r"^LD-\d{8,}$"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _lead_number(lead_id: str) -> int:
    async with db_session.AsyncSessionLocal() as db:
        number = await db.scalar(select(Lead.lead_number).where(Lead.id == uuid.UUID(lead_id)))
    assert number is not None
    return number


async def _lead_number_by_mobile(mobile: str) -> int:
    async with db_session.AsyncSessionLocal() as db:
        number = await db.scalar(select(Lead.lead_number).where(Lead.mobile == mobile))
    assert number is not None
    return number


# ---------------------------------------------------------------------------
# Formatting and tolerant parsing (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "expected"),
    [(1, "LD-00000001"), (123, "LD-00000123"), (99_999_999, "LD-99999999")],
)
def test_format_pads_to_eight_digits(number: int, expected: str) -> None:
    assert format_lead_ref(number) == expected


def test_format_grows_past_eight_digits() -> None:
    assert format_lead_ref(123_456_789) == "LD-123456789"


@pytest.mark.parametrize(
    "value",
    ["LD-00000123", "ld-123", "Ld-0123", "LD 123", "LD123", "123", " 00000123 ", "ld-000000123"],
)
def test_parse_accepts_tolerant_forms(value: str) -> None:
    assert parse_lead_ref(value) == 123


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "LD-",
        "LD-0",
        "0",
        "-5",
        "LD--12",
        "AB-123",
        "LD-12a",
        "12 34",
        "1" * 19,
        "9" * 40,
    ],
)
def test_parse_rejects_non_references(value: str) -> None:
    assert parse_lead_ref(value) is None


# ---------------------------------------------------------------------------
# Migration backfill: creation order, id tiebreak, batching, resumption
# ---------------------------------------------------------------------------


async def test_backfill_numbers_rows_in_creation_order_across_batches() -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    migration = ScriptDirectory.from_config(config).get_revision("0d26342db0ba").module
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # Inserted out of order; two rows share a created_at and fall back to id.
    rows = [
        ("00000000-0000-0000-0000-000000000005", base + timedelta(days=4)),
        ("00000000-0000-0000-0000-000000000001", base),
        ("00000000-0000-0000-0000-000000000004", base + timedelta(days=2)),
        ("00000000-0000-0000-0000-000000000003", base + timedelta(days=2)),
        ("00000000-0000-0000-0000-000000000002", base + timedelta(days=1)),
    ]

    async with db_session.AsyncSessionLocal() as db:
        connection = await db.connection()

        def run(sync_connection) -> tuple[int, int, list[tuple[str, int]]]:
            # An unqualified ``leads`` in the migration resolves to this temp
            # shadow table, never the real one.
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE leads (id uuid PRIMARY KEY, created_at timestamptz "
                    "NOT NULL, lead_number bigint) ON COMMIT DROP"
                )
            )
            for lead_id, created in rows:
                sync_connection.execute(
                    text("INSERT INTO leads (id, created_at) VALUES (:id, :created)"),
                    {"id": lead_id, "created": created},
                )
            first = migration._number_pending_leads(sync_connection, assigned=0, batch_size=2)
            # A later arrival is numbered after the existing rows on a resumed run.
            sync_connection.execute(
                text("INSERT INTO leads (id, created_at) VALUES (:id, :created)"),
                {"id": "00000000-0000-0000-0000-000000000000", "created": base},
            )
            second = migration._number_pending_leads(
                sync_connection,
                assigned=migration._highest_assigned(sync_connection),
                batch_size=2,
            )
            numbered = sync_connection.execute(
                text("SELECT id::text, lead_number FROM leads ORDER BY lead_number")
            ).all()
            return first, second, [(row[0], row[1]) for row in numbered]

        first, second, numbered = await connection.run_sync(run)
        await db.rollback()

    assert first == 5
    assert second == 6
    assert numbered == [
        ("00000000-0000-0000-0000-000000000001", 1),
        ("00000000-0000-0000-0000-000000000002", 2),
        ("00000000-0000-0000-0000-000000000003", 3),
        ("00000000-0000-0000-0000-000000000004", 4),
        ("00000000-0000-0000-0000-000000000005", 5),
        ("00000000-0000-0000-0000-000000000000", 6),
    ]


# ---------------------------------------------------------------------------
# Assignment on every creation path; the public surface never sees it
# ---------------------------------------------------------------------------


async def test_public_form_assigns_a_number_and_never_returns_it(client: AsyncClient) -> None:
    first_mobile, second_mobile = unique_mobile(), unique_mobile()
    for mobile in (first_mobile, second_mobile):
        res = await client.post(
            "/api/v1/leads",
            json={"name": "Visitor", "mobile": mobile, "topic": "loans", "origin": "contact"},
        )
        assert res.status_code == 202, res.text
        # PublicLeadResponse stays exactly {ok: true}: no reference, no count.
        assert res.json() == {"ok": True}
        assert "LD-" not in res.text

    first, second = (
        await _lead_number_by_mobile(first_mobile),
        await _lead_number_by_mobile(second_mobile),
    )
    assert 0 < first < second


async def test_public_chat_receipt_carries_no_lead_reference(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/leads/chat-inquiries",
        json={
            "name": "Chat Visitor",
            "mobile": unique_mobile(),
            "idempotency_key": str(uuid.uuid4()),
            "flow": "residential",
            "action": "visit",
            "answers": ["Buy property", "Independent villa", "Under ₹60 lakh"],
            "location": "Test locality",
        },
    )
    assert res.status_code in (200, 201, 202), res.text
    assert set(res.json()) == {"reference"}
    assert "LD-" not in res.text and "lead_number" not in res.text


async def test_agent_create_assigns_the_next_number_and_returns_its_ref(
    client: AsyncClient,
) -> None:
    previous = await _seed_lead(business_line="loans", origin_agent_profile_uuid=None)
    auth_uuid, profile_uuid = await _seed_agent("loans")
    res = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), "name": "Introduced Lead"},
        headers=_headers(_agent_token(auth_uuid, profile_uuid)),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    number = await _lead_number(body["id"])
    assert body["lead_ref"] == format_lead_ref(number)
    assert number > await _lead_number(previous)


async def test_lead_number_is_immutable_even_for_the_owner_role() -> None:
    lead_id = await _seed_lead(business_line="loans", origin_agent_profile_uuid=None)
    async with db_session.AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError, match="lead_number is immutable"):
            await db.execute(
                update(Lead).where(Lead.id == uuid.UUID(lead_id)).values(lead_number=1)
            )
        await db.rollback()


# ---------------------------------------------------------------------------
# Search: tolerant, exact, and never wider than the caller's scope
# ---------------------------------------------------------------------------


async def test_agent_search_finds_own_lead_in_tolerant_forms(client: AsyncClient) -> None:
    auth_uuid, profile_uuid = await _seed_agent("loans")
    token = _agent_token(auth_uuid, profile_uuid)
    created = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), "name": "Searchable"},
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]
    number = await _lead_number(lead_id)

    for term in (format_lead_ref(number), f"ld-{number}", str(number)):
        res = await client.get(
            "/api/v1/agent/leads", params={"lead_ref": term}, headers=_headers(token)
        )
        assert res.status_code == 200, res.text
        assert [row["id"] for row in res.json()] == [lead_id], term
        assert res.json()[0]["lead_ref"] == format_lead_ref(number)

    # A blank filter is no filter.
    res = await client.get("/api/v1/agent/leads", params={"lead_ref": " "}, headers=_headers(token))
    assert res.status_code == 200
    assert lead_id in {row["id"] for row in res.json()}

    res = await client.get(
        "/api/v1/agent/leads", params={"lead_ref": "LD-12x"}, headers=_headers(token)
    )
    assert res.status_code == 422
    assert res.json()["detail"] == "Enter a lead reference such as LD-00000123."

    # Authentication is decided before the reference is parsed.
    anonymous = await client.get("/api/v1/agent/leads", params={"lead_ref": "LD-12x"})
    assert anonymous.status_code == 401


async def test_reference_of_another_agent_or_line_returns_nothing(client: AsyncClient) -> None:
    owner_auth, owner_profile = await _seed_agent("loans")
    other_auth, other_profile = await _seed_agent("loans")
    _, estate_profile = await _seed_agent("real_estate")
    owned = await _seed_lead(business_line="loans", origin_agent_profile_uuid=owner_profile)
    estate_lead = await _seed_lead(
        business_line="real_estate", origin_agent_profile_uuid=estate_profile
    )
    owned_ref = format_lead_ref(await _lead_number(owned))
    estate_ref = format_lead_ref(await _lead_number(estate_lead))

    other = await client.get(
        "/api/v1/agent/leads",
        params={"lead_ref": owned_ref},
        headers=_headers(_agent_token(other_auth, other_profile)),
    )
    assert other.status_code == 200 and other.json() == []

    cross_line = await client.get(
        "/api/v1/agent/leads",
        params={"lead_ref": estate_ref},
        headers=_headers(_agent_token(owner_auth, owner_profile)),
    )
    assert cross_line.status_code == 200 and cross_line.json() == []

    # The owner still finds their own lead by the same reference.
    own = await client.get(
        "/api/v1/agent/leads",
        params={"lead_ref": owned_ref},
        headers=_headers(_agent_token(owner_auth, owner_profile)),
    )
    assert [row["id"] for row in own.json()] == [owned]


async def test_telecaller_list_detail_and_scoped_search(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_telecaller("loans")
    _, other_staff = await _seed_telecaller("loans")
    _, estate_staff = await _seed_telecaller("real_estate")
    mine = await _seed_assigned_lead("loans", staff_uuid)
    colleagues = await _seed_assigned_lead("loans", other_staff)
    estate = await _seed_assigned_lead("real_estate", estate_staff)
    token = _telecaller_token(auth_uuid, staff_uuid)
    mine_ref = format_lead_ref(await _lead_number(mine))

    listed = await client.get("/api/v1/telecaller/leads", headers=_headers(token))
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if item["id"] == mine)
    assert row["lead_ref"] == mine_ref

    detail = await client.get(f"/api/v1/telecaller/leads/{mine}", headers=_headers(token))
    assert detail.status_code == 200 and detail.json()["lead_ref"] == mine_ref

    found = await client.get(
        "/api/v1/telecaller/leads", params={"lead_ref": mine_ref.lower()}, headers=_headers(token)
    )
    assert [item["id"] for item in found.json()] == [mine]

    for other in (colleagues, estate):
        res = await client.get(
            "/api/v1/telecaller/leads",
            params={"lead_ref": format_lead_ref(await _lead_number(other))},
            headers=_headers(token),
        )
        assert res.status_code == 200 and res.json() == [], other


async def test_team_manager_search_stays_inside_the_team(client: AsyncClient) -> None:
    from app.tests.test_team_manager_api import _seed_lead as _seed_team_lead
    from app.tests.test_team_manager_api import _telecaller_team

    token, _, _, team_id, asha, _, outsider = await _telecaller_team(client)
    member_lead = await _seed_team_lead(asha)
    outsider_lead = await _seed_team_lead(outsider)
    member_ref = format_lead_ref(await _lead_number(str(member_lead)))
    outsider_ref = format_lead_ref(await _lead_number(str(outsider_lead)))

    for path in (
        f"/api/v1/manager/teams/{team_id}/work",
        f"/api/v1/manager/teams/{team_id}/members/{asha}/work",
    ):
        found = await client.get(path, params={"lead_ref": member_ref}, headers=_headers(token))
        assert found.status_code == 200, found.text
        assert [(row["id"], row["lead_ref"]) for row in found.json()["leads"]] == [
            (str(member_lead), member_ref)
        ]
        hidden = await client.get(path, params={"lead_ref": outsider_ref}, headers=_headers(token))
        assert hidden.status_code == 200 and hidden.json()["leads"] == []

    detail = await client.get(
        f"/api/v1/manager/teams/{team_id}/leads/{member_lead}", headers=_headers(token)
    )
    assert detail.status_code == 200 and detail.json()["lead"]["lead_ref"] == member_ref


async def test_admin_assigned_list_search_and_details(client: AsyncClient) -> None:
    admin_token, _ = await _make_admin(client)
    _, staff_uuid = await _seed_telecaller("loans")
    lead_id = await _seed_assigned_lead("loans", staff_uuid)
    ref = format_lead_ref(await _lead_number(lead_id))

    res = await client.get(
        "/api/v1/admin/leads/assigned", params={"lead_ref": ref}, headers=_headers(admin_token)
    )
    assert res.status_code == 200, res.text
    assert [(row["id"], row["lead_ref"]) for row in res.json()] == [(lead_id, ref)]

    details = await client.get(
        f"/api/v1/admin/leads/{lead_id}/details", headers=_headers(admin_token)
    )
    assert details.status_code == 200 and details.json()["lead_ref"] == ref


# ---------------------------------------------------------------------------
# Money surfaces: commissions, fee cashbacks, payouts, Agent ledger
# ---------------------------------------------------------------------------


async def test_commission_surfaces_and_payout_carry_the_lead_ref(client: AsyncClient) -> None:
    maker_token, maker_uid = await _make_admin(client)
    checker_token, _ = await _make_admin(client)

    # Eligible queue and the created commission.
    _, queue_agent = await _seed_agent("loans")
    queue_lead = await _seed_lead(business_line="loans", origin_agent_profile_uuid=queue_agent)
    queue_loan = await _seed_commission_loan(lead_id=queue_lead)
    queue_ref = format_lead_ref(await _lead_number(queue_lead))
    eligible = await client.get(
        "/api/v1/admin/commissions/eligible", params={"limit": 200}, headers=_headers(maker_token)
    )
    assert eligible.status_code == 200, eligible.text
    deal = next(d for d in eligible.json()["deals"] if d["deal_uuid"] == queue_loan)
    assert deal["lead_ref"] == queue_ref
    created = await client.post(
        "/api/v1/admin/commissions",
        headers=_headers(maker_token),
        json={"deal_type": "loan_application", "deal_uuid": queue_loan, "agreed_amount_paise": 1},
    )
    assert created.status_code == 201, created.text
    assert created.json()["lead_ref"] == queue_ref

    # Payout, covered items, settlement and the Agent's own views.
    agent_uid, agent_profile = await _seed_agent("loans")
    commission_id = await _seed_commission(
        agent_auth_user_uuid=agent_uid,
        agent_profile_uuid=agent_profile,
        business_line="loans",
        entered_by_uuid=maker_uid,
    )
    async with db_session.AsyncSessionLocal() as db:
        lead_number = await db.scalar(
            text(
                "SELECT l.lead_number FROM commissions c JOIN leads l ON l.id = c.lead_uuid "
                "WHERE c.id = :id"
            ),
            {"id": commission_id},
        )
    ref = format_lead_ref(lead_number)

    listed = await client.get(
        "/api/v1/admin/commissions",
        params={"agent_profile_uuid": agent_profile},
        headers=_headers(maker_token),
    )
    row = next(c for c in listed.json()["commissions"] if c["id"] == commission_id)
    assert row["lead_ref"] == ref

    paid = await client.post(
        f"/api/v1/admin/commissions/{commission_id}/payout",
        headers=_headers(maker_token),
        json=_payout_body(),
    )
    assert paid.status_code == 201, paid.text
    payout_id = paid.json()["payout_id"]

    payouts = await client.get(
        "/api/v1/payouts", params={"limit": 500}, headers=_headers(maker_token)
    )
    payout = next(p for p in payouts.json()["payouts"] if p["id"] == payout_id)
    assert payout["lead_refs"] == [ref]

    items = await client.get(
        f"/api/v1/admin/commissions/payouts/{payout_id}/items", headers=_headers(maker_token)
    )
    assert items.status_code == 200, items.text
    assert [item["lead_ref"] for item in items.json()] == [ref]

    approved = await client.post(
        f"/api/v1/payouts/{payout_id}/approve", headers=_headers(checker_token)
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["lead_refs"] == [ref]

    agent_token = _agent_token(agent_uid, agent_profile)
    earnings = await client.get("/api/v1/agent/earnings", headers=_headers(agent_token))
    assert earnings.status_code == 200, earnings.text
    earning = next(r for r in earnings.json()["rows"] if r["id"] == commission_id)
    assert earning["lead_ref"] == ref
    searched = await client.get(
        "/api/v1/agent/earnings", params={"q": f"ld-{lead_number}"}, headers=_headers(agent_token)
    )
    assert [r["id"] for r in searched.json()["rows"]] == [commission_id]

    transaction_id = earning["payout_txn_uuid"]
    assert transaction_id is not None
    detail = await client.get(
        f"/api/v1/agent/transactions/{transaction_id}", headers=_headers(agent_token)
    )
    assert detail.status_code == 200, detail.text
    assert [item["lead_ref"] for item in detail.json()["items"]] == [ref]


async def test_fee_cashback_surfaces_carry_the_lead_ref(client: AsyncClient) -> None:
    admin_token, _ = await _make_admin(client)
    loan_id, _ = await _seed_cashback_loan(processing_fee=3000.00)
    async with db_session.AsyncSessionLocal() as db:
        lead_number = await db.scalar(
            text(
                "SELECT l.lead_number FROM loan_applications a JOIN leads l "
                "ON l.id = a.lead_uuid WHERE a.id = :id"
            ),
            {"id": loan_id},
        )
    ref = format_lead_ref(lead_number)

    eligible = await client.get(
        "/api/v1/admin/fee-cashbacks/eligible", params={"limit": 200}, headers=_headers(admin_token)
    )
    row = next(a for a in eligible.json()["applications"] if a["loan_application_uuid"] == loan_id)
    assert row["lead_ref"] == ref

    created = await client.post(
        "/api/v1/admin/fee-cashbacks",
        headers=_headers(admin_token),
        json={"loan_application_uuid": loan_id, "amount_paise": 100_000},
    )
    assert created.status_code == 201, created.text
    assert created.json()["lead_ref"] == ref

    paid = await client.post(
        f"/api/v1/admin/fee-cashbacks/{created.json()['id']}/payout",
        headers=_headers(admin_token),
        json=_payout_body(),
    )
    assert paid.status_code == 201, paid.text
    payouts = await client.get(
        "/api/v1/payouts", params={"limit": 500}, headers=_headers(admin_token)
    )
    payout = next(p for p in payouts.json()["payouts"] if p["id"] == paid.json()["payout_id"])
    assert payout["lead_refs"] == [ref]


async def test_client_facing_lead_details_do_not_carry_the_reference() -> None:
    from app.schemas.lead_details import LeadDetailsRead
    from app.schemas.leads import PublicLeadResponse

    assert "lead_ref" not in LeadDetailsRead.model_fields
    assert set(PublicLeadResponse.model_fields) == {"ok"}
