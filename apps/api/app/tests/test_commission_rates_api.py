"""CS-028 per-loan-product commission rates: maker-checker API, the loans
Agent's read, the eligible-deal pre-fill, and absence from public reads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

import app.db.session as db_session
from app.models.audit_log import AuditAction, AuditLog
from app.models.loan import LoanApplication, LoanType
from app.models.notification import Notification, NotificationType
from app.models.profile import StaffRole
from app.services.commission_rates import suggest_commission
from app.tests.contest_support import headers, seed_agent, seed_staff, token_for
from conftest import full_registration

pytestmark = pytest.mark.asyncio

URL = "/api/v1/commission-rates"


async def _product(*, active: bool = True, category: str = "loan", **fields) -> LoanType:
    async with db_session.AsyncSessionLocal() as db:
        product = LoanType(
            name=f"rate-{uuid.uuid4().hex[:8]}",
            label=f"Rate Loan {uuid.uuid4().hex[:6]}",
            active=active,
            category=category,
            **fields,
        )
        db.add(product)
        await db.commit()
        return product


async def _sub_admin() -> tuple[dict[str, str], uuid.UUID]:
    user, profile = await seed_staff(StaffRole.SUB_ADMIN, first_name="Maker")
    return (
        headers(token_for(user, "sub_admin", platform_scope="true", staff_profile=profile)),
        user.id,
    )


async def _admin(platform_scope: str = "true") -> tuple[dict[str, str], uuid.UUID]:
    user, profile = await seed_staff(StaffRole.ADMIN, first_name="Checker")
    return (
        headers(token_for(user, "admin", platform_scope=platform_scope, staff_profile=profile)),
        user.id,
    )


async def _loans_agent(line: str = "loans") -> dict[str, str]:
    user, agent = await seed_agent(line)
    return headers(token_for(user, "agent", business_line=line, agent_profile=agent))


def _percent(bps: int, note: str | None = None) -> dict:
    return {"kind": "percent", "percent_bps": bps, **({"note": note} if note else {})}


async def _audit_actions(rate_id: str) -> list[str]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_uuid == uuid.UUID(rate_id))
            .order_by(AuditLog.created_at)
        )
        return [str(action) for action in rows]


async def _notified(user_uuid: uuid.UUID, kind: NotificationType, since: datetime) -> bool:
    async with db_session.AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(Notification.id).where(
                    Notification.user_uuid == user_uuid,
                    Notification.type == kind,
                    Notification.created_at >= since,
                )
            )
            is not None
        )


# ---------------------------------------------------------------------------
# Maker-checker
# ---------------------------------------------------------------------------


async def test_sub_admin_proposal_awaits_admin_approval(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.commission_rates as service

    fanout: list[dict] = []

    async def _capture(**kwargs: object) -> None:
        fanout.append(kwargs)

    # notify_admins caps its fan-out, so the shared test database's many
    # Admins make "this Admin got it" flaky; assert the call instead.
    monkeypatch.setattr(service, "notify_admins", _capture)
    product = await _product()
    maker, maker_id = await _sub_admin()
    admin, _admin_id = await _admin()
    started = datetime.now(UTC)

    res = await client.put(f"{URL}/{product.id}", json=_percent(150, "On disbursal"), headers=maker)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["current"] is None
    pending = body["pending"]
    assert pending["status"] == "pending_approval"
    assert pending["percent_bps"] == 150 and pending["amount_paise"] is None
    assert pending["note"] == "On disbursal"
    assert pending["created_by_role"] == "sub_admin"
    assert pending["is_mine"] is True
    assert pending["created_by_name"] == "Maker Sub_Admin"
    [notice] = fanout
    assert notice["notification_type"] == NotificationType.COMMISSION_RATE_SUBMITTED
    assert notice["exclude_user_uuid"] == maker_id
    assert product.label in str(notice["body"])

    approved = await client.post(f"{URL}/{pending['id']}/approve", json={}, headers=admin)
    assert approved.status_code == 200, approved.text
    current = approved.json()["current"]
    assert current["id"] == pending["id"]
    assert current["status"] == "approved"
    assert current["checker_name"] == "Checker Admin"
    assert current["is_mine"] is False
    assert approved.json()["pending"] is None
    assert await _notified(maker_id, NotificationType.COMMISSION_RATE_REVIEWED, started)
    assert await _audit_actions(pending["id"]) == [
        AuditAction.COMMISSION_RATE_PROPOSED.value,
        AuditAction.COMMISSION_RATE_APPROVED.value,
    ]


async def test_approval_supersedes_the_previous_rate(client: AsyncClient) -> None:
    product = await _product()
    maker, _ = await _sub_admin()
    admin, _ = await _admin()
    first = await client.put(
        f"{URL}/{product.id}", json={"kind": "fixed", "amount_paise": 500_000}, headers=admin
    )
    assert first.status_code == 200, first.text
    old_id = first.json()["current"]["id"]

    proposal = await client.put(f"{URL}/{product.id}", json=_percent(200), headers=maker)
    pending_id = proposal.json()["pending"]["id"]
    # The approved rate stays current while the proposal waits.
    assert proposal.json()["current"]["id"] == old_id

    approved = await client.post(f"{URL}/{pending_id}/approve", headers=admin)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["current"]["id"] == pending_id
    [superseded] = [row for row in body["history"] if row["id"] == old_id]
    assert superseded["status"] == "superseded"


async def test_admin_entry_is_approved_immediately(client: AsyncClient) -> None:
    product = await _product()
    admin, _admin_id = await _admin()
    maker, _ = await _sub_admin()
    proposal = await client.put(f"{URL}/{product.id}", json=_percent(90), headers=maker)
    pending_id = proposal.json()["pending"]["id"]

    res = await client.put(
        f"{URL}/{product.id}",
        json={"kind": "fixed", "amount_paise": 2_500_00, "note": "Flat fee"},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    current = res.json()["current"]
    assert current["status"] == "approved"
    assert current["created_by_role"] == "admin"
    assert current["checker_name"] == current["created_by_name"] == "Checker Admin"
    assert current["amount_paise"] == 2_500_00
    # A waiting Sub Admin proposal is left for the Admin to decide.
    assert res.json()["pending"]["id"] == pending_id
    assert await _audit_actions(current["id"]) == [AuditAction.COMMISSION_RATE_SET.value]


async def test_reject_needs_a_note(client: AsyncClient) -> None:
    product = await _product()
    maker, maker_id = await _sub_admin()
    admin, _ = await _admin()
    pending_id = (
        await client.put(f"{URL}/{product.id}", json=_percent(100), headers=maker)
    ).json()["pending"]["id"]
    started = datetime.now(UTC)

    for body in ({}, {"note": "   "}):
        res = await client.post(f"{URL}/{pending_id}/reject", json=body, headers=admin)
        assert res.status_code == 422, res.text
    res = await client.post(
        f"{URL}/{pending_id}/reject", json={"note": "Too high for this product"}, headers=admin
    )
    assert res.status_code == 200, res.text
    [rejected] = res.json()["history"]
    assert rejected["status"] == "rejected"
    assert rejected["review_note"] == "Too high for this product"
    assert res.json()["current"] is None and res.json()["pending"] is None
    assert await _notified(maker_id, NotificationType.COMMISSION_RATE_REVIEWED, started)
    # A decided rate cannot be decided again.
    again = await client.post(f"{URL}/{pending_id}/approve", headers=admin)
    assert again.status_code == 409, again.text


async def test_maker_cannot_check_their_own_proposal(client: AsyncClient) -> None:
    product = await _product()
    user, profile = await seed_staff(StaffRole.SUB_ADMIN, first_name="Dual")
    as_sub_admin = headers(
        token_for(user, "sub_admin", platform_scope="true", staff_profile=profile)
    )
    pending_id = (
        await client.put(f"{URL}/{product.id}", json=_percent(100), headers=as_sub_admin)
    ).json()["pending"]["id"]

    # The Sub Admin role may not review at all...
    assert (
        await client.post(f"{URL}/{pending_id}/approve", headers=as_sub_admin)
    ).status_code == 403
    # ...and the same person holding an Admin token still may not check it.
    as_admin = headers(token_for(user, "admin", platform_scope="true", staff_profile=profile))
    for action, body in (("approve", {}), ("reject", {"note": "Mine"})):
        res = await client.post(f"{URL}/{pending_id}/{action}", json=body, headers=as_admin)
        assert res.status_code == 403, res.text


async def test_proposals_replace_own_and_respect_others(client: AsyncClient) -> None:
    product = await _product()
    maker, _ = await _sub_admin()
    other, _ = await _sub_admin()
    first = (await client.put(f"{URL}/{product.id}", json=_percent(100), headers=maker)).json()
    second = await client.put(f"{URL}/{product.id}", json=_percent(120), headers=maker)
    assert second.status_code == 200, second.text
    assert second.json()["pending"]["percent_bps"] == 120
    [replaced] = second.json()["history"]
    assert replaced["id"] == first["pending"]["id"]
    assert replaced["status"] == "withdrawn"

    blocked = await client.put(f"{URL}/{product.id}", json=_percent(130), headers=other)
    assert blocked.status_code == 409, blocked.text


async def test_maker_withdraws_their_pending_proposal(client: AsyncClient) -> None:
    product = await _product()
    maker, _ = await _sub_admin()
    other, _ = await _sub_admin()
    admin, _ = await _admin()
    pending_id = (
        await client.put(f"{URL}/{product.id}", json=_percent(100), headers=maker)
    ).json()["pending"]["id"]

    assert (await client.post(f"{URL}/{pending_id}/withdraw", headers=other)).status_code == 403
    assert (await client.post(f"{URL}/{pending_id}/withdraw", headers=admin)).status_code == 403
    res = await client.post(f"{URL}/{pending_id}/withdraw", headers=maker)
    assert res.status_code == 200, res.text
    assert res.json()["pending"] is None
    assert res.json()["history"][0]["status"] == "withdrawn"
    assert (await client.post(f"{URL}/{pending_id}/withdraw", headers=maker)).status_code == 409
    assert (await client.post(f"{URL}/{pending_id}/approve", headers=admin)).status_code == 409


async def test_staff_routes_are_for_sub_admins_and_platform_admins(client: AsyncClient) -> None:
    product = await _product()
    line_admin, _ = await _admin(platform_scope="line")
    agent = await _loans_agent()
    token, _mobile = await full_registration(client, lines=["loans"])
    client_headers = {"Authorization": f"Bearer {token}"}
    tc_user, tc = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    telecaller = headers(token_for(tc_user, "telecaller", business_line="loans", staff_profile=tc))
    for denied in (line_admin, agent, client_headers, telecaller):
        assert (await client.get(URL, headers=denied)).status_code == 403
        res = await client.put(f"{URL}/{product.id}", json=_percent(100), headers=denied)
        assert res.status_code == 403
    assert (await client.get(URL)).status_code == 401


async def test_input_validation_and_loan_products_only(client: AsyncClient) -> None:
    product = await _product()
    card = await _product(category="credit_card")
    admin, _ = await _admin()
    for body in (
        {"kind": "percent", "amount_paise": 100},
        {"kind": "percent", "percent_bps": 0},
        {"kind": "percent", "percent_bps": 10_001},
        {"kind": "percent", "percent_bps": 100, "amount_paise": 100},
        {"kind": "fixed", "amount_paise": 0},
        {"kind": "fixed", "amount_paise": 10_000_000_001},
        {"kind": "fixed", "amount_paise": 100, "note": "x" * 281},
        {"kind": "flat", "amount_paise": 100},
        {"kind": "fixed", "amount_paise": 100, "extra": True},
    ):
        res = await client.put(f"{URL}/{product.id}", json=body, headers=admin)
        assert res.status_code == 422, (body, res.text)
    assert (
        await client.put(f"{URL}/{card.id}", json=_percent(100), headers=admin)
    ).status_code == 404
    assert (
        await client.put(f"{URL}/{uuid.uuid4()}", json=_percent(100), headers=admin)
    ).status_code == 404


# ---------------------------------------------------------------------------
# Who reads rates
# ---------------------------------------------------------------------------


async def test_loans_agent_sees_only_approved_rates_of_active_products(
    client: AsyncClient,
) -> None:
    approved = await _product()
    pending_only = await _product()
    inactive = await _product()
    admin, _ = await _admin()
    maker, _ = await _sub_admin()
    await client.put(f"{URL}/{approved.id}", json=_percent(175, "Indicative"), headers=admin)
    await client.put(f"{URL}/{pending_only.id}", json=_percent(300), headers=maker)
    await client.put(f"{URL}/{inactive.id}", json=_percent(400), headers=admin)
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(update(LoanType).where(LoanType.id == inactive.id).values(active=False))
        await db.commit()

    res = await client.get("/api/v1/agent/commission-rates", headers=await _loans_agent())
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    rates = res.json()["rates"]
    assert rates[approved.name]["percent_bps"] == 175
    assert rates[approved.name]["note"] == "Indicative"
    assert rates[approved.name]["product_label"] == approved.label
    assert rates[approved.name]["approved_at"] is not None
    assert pending_only.name not in rates
    assert inactive.name not in rates

    re_agent = await client.get(
        "/api/v1/agent/commission-rates", headers=await _loans_agent("real_estate")
    )
    assert re_agent.status_code == 200 and re_agent.json() == {"rates": {}}

    tc_user, tc = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    telecaller = headers(token_for(tc_user, "telecaller", business_line="loans", staff_profile=tc))
    assert (
        await client.get("/api/v1/agent/commission-rates", headers=telecaller)
    ).status_code == 403


async def test_rates_never_reach_public_or_client_reads(client: AsyncClient) -> None:
    marker = f"RATE-NOTE-{uuid.uuid4().hex[:10]}"
    product = await _product(
        public_visible=True,
        public_summary="A public loan.",
        public_description="Publicly described.",
    )
    admin, _ = await _admin()
    res = await client.put(f"{URL}/{product.id}", json=_percent(777, marker), headers=admin)
    assert res.status_code == 200, res.text

    token, _mobile = await full_registration(client, lines=["loans"])
    client_headers = {"Authorization": f"Bearer {token}"}
    for path, request_headers, expected_status in (
        (f"/api/v1/public/financial-products?q={product.label}", {}, 200),
        (f"/api/v1/public/financial-products/{product.name}", {}, 200),
        ("/api/v1/loans/loan-types", client_headers, 200),
        ("/api/v1/agent/commission-rates", client_headers, 403),
        (URL, client_headers, 403),
    ):
        read = await client.get(path, headers=request_headers)
        assert read.status_code == expected_status, (path, read.text)
        assert marker not in read.text, path
        assert "percent_bps" not in read.text, path
    # The product itself is public, so the reads above did include it.
    public = await client.get(f"/api/v1/public/financial-products/{product.name}")
    assert public.json()["slug"] == product.name


# ---------------------------------------------------------------------------
# Commission entry pre-fill
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Percent of the sanctioned amount, integer paise, half up.
        (
            {
                "kind": "percent",
                "percent_bps": 150,
                "amount_paise": None,
                "amount_sanctioned": Decimal("1234567.89"),
                "amount_requested": Decimal("1"),
            },
            (1_851_852, "sanctioned", 123_456_789),
        ),
        # Requested amount when nothing was sanctioned.
        (
            {
                "kind": "percent",
                "percent_bps": 100,
                "amount_paise": None,
                "amount_sanctioned": None,
                "amount_requested": Decimal("100000"),
            },
            (100_000, "requested", 10_000_000),
        ),
        # Half a paisa rounds up; just under half rounds to nothing.
        (
            {
                "kind": "percent",
                "percent_bps": 5_000,
                "amount_paise": None,
                "amount_sanctioned": Decimal("0.01"),
                "amount_requested": None,
            },
            (1, "sanctioned", 1),
        ),
        (
            {
                "kind": "percent",
                "percent_bps": 4_999,
                "amount_paise": None,
                "amount_sanctioned": Decimal("0.01"),
                "amount_requested": None,
            },
            (None, "sanctioned", 1),
        ),
        # Capped at the per-commission ceiling.
        (
            {
                "kind": "percent",
                "percent_bps": 10_000,
                "amount_paise": None,
                "amount_sanctioned": Decimal("999999999999.99"),
                "amount_requested": None,
            },
            (10_000_000_000, "sanctioned", 99_999_999_999_999),
        ),
        # No usable amount: no suggestion.
        (
            {
                "kind": "percent",
                "percent_bps": 100,
                "amount_paise": None,
                "amount_sanctioned": None,
                "amount_requested": None,
            },
            (None, None, None),
        ),
        (
            {
                "kind": "fixed",
                "percent_bps": None,
                "amount_paise": 2_500_00,
                "amount_sanctioned": Decimal("1"),
                "amount_requested": None,
            },
            (2_500_00, "fixed", None),
        ),
    ],
)
def test_suggestion_maths(kwargs: dict, expected: tuple) -> None:
    assert suggest_commission(**kwargs) == expected


async def test_eligible_deals_carry_the_rate_and_suggestion(client: AsyncClient) -> None:
    from app.tests.test_commission_api import (
        _seed_agent,
        _seed_lead,
        _seed_loan_application,
        _seed_property_deal,
    )

    admin, _ = await _admin()
    _, agent_profile_uuid, _ = await _seed_agent("loans")
    percent_loan = await _seed_loan_application(
        lead_id=await _seed_lead(
            business_line="loans", origin_agent_profile_uuid=agent_profile_uuid
        )
    )
    plain_loan = await _seed_loan_application(
        lead_id=await _seed_lead(
            business_line="loans", origin_agent_profile_uuid=agent_profile_uuid
        )
    )
    _, re_agent_uuid, _ = await _seed_agent("real_estate")
    deal = await _seed_property_deal(
        lead_id=await _seed_lead(
            business_line="real_estate", origin_agent_profile_uuid=re_agent_uuid
        )
    )
    async with db_session.AsyncSessionLocal() as db:
        application = await db.get(LoanApplication, uuid.UUID(percent_loan))
        application.amount_sanctioned = Decimal("2500000.00")
        await db.commit()
        loan_type_id = application.loan_type_id

    res = await client.put(
        f"{URL}/{loan_type_id}", json=_percent(125, "Of sanction"), headers=admin
    )
    assert res.status_code == 200, res.text

    eligible = await client.get("/api/v1/admin/commissions/eligible?limit=200", headers=admin)
    assert eligible.status_code == 200, eligible.text
    rows = {row["deal_uuid"]: row for row in eligible.json()["deals"]}

    with_rate = rows[percent_loan]
    assert with_rate["loan_type_id"] == str(loan_type_id)
    assert with_rate["commission_rate"]["percent_bps"] == 125
    assert with_rate["commission_rate"]["note"] == "Of sanction"
    assert with_rate["suggestion_basis"] == "sanctioned"
    assert with_rate["basis_amount_paise"] == 250_000_000
    assert with_rate["suggested_amount_paise"] == 3_125_000

    without_rate = rows[plain_loan]
    assert without_rate["product_label"] == "Test Loan Type"
    assert without_rate["commission_rate"] is None
    assert without_rate["suggested_amount_paise"] is None

    property_row = rows[deal]
    assert property_row["commission_rate"] is None
    assert property_row["loan_type_id"] is None
    assert property_row["suggested_amount_paise"] is None


async def test_deleting_an_unused_product_removes_its_rates(client: AsyncClient) -> None:
    from sqlalchemy import func

    from app.models.commission_rate import ProductCommissionRate

    product = await _product()
    admin, _ = await _admin()
    maker, _ = await _sub_admin()
    approved = await client.put(f"{URL}/{product.id}", json=_percent(100), headers=admin)
    assert approved.status_code == 200, approved.text
    assert approved.json()["current"]["percent_bps"] == 100
    proposed = await client.put(f"{URL}/{product.id}", json=_percent(120), headers=maker)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["pending"]["percent_bps"] == 120

    res = await client.delete(f"/api/v1/admin/loan-types/{product.id}", headers=admin)
    assert res.status_code == 204, res.text
    async with db_session.AsyncSessionLocal() as db:
        remaining = await db.scalar(
            select(func.count())
            .select_from(ProductCommissionRate)
            .where(ProductCommissionRate.loan_type_id == product.id)
        )
    assert remaining == 0
