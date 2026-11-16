"""CS-022 Agent dashboard reads.

Commission history with client/deal details and filters, the IST previous-month
paid total, the payout trail behind a commission transaction, and lead history.
Covers isolation between Agents and business lines, the Admin's Agent field
rules, and that the confined functions refuse every other request context.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, text

from app.core.security import create_access_token
from app.models.audit_log import AuditAction, AuditLog
from app.models.commission import Commission, CommissionStatus
from app.models.enquiry import Enquiry, EnquiryStatus
from app.models.field_visibility import (
    FieldTargetRole,
    FieldVisibilityConfig,
    FieldVisibilityMode,
)
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity
from app.models.loan import Bank, LoanApplication, LoanStatus, LoanType
from app.models.payout import Payout, PayoutDestination, PayoutStatus, PayoutType
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.property import Property
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.site_visit import SiteVisit, SiteVisitStatus, SiteVisitTimeSlot
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services import agent_dashboard
from conftest import unique_mobile

pytestmark = pytest.mark.asyncio

# 10 Nov 2026, 11:30 IST: the previous calendar month is October 2026.
_NOW = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
_OCT_START = datetime(2026, 9, 30, 18, 30, tzinfo=UTC)  # 1 Oct 00:00 IST
_NOV_START = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)  # 1 Nov 00:00 IST
_SECOND = timedelta(seconds=1)


def _session():
    import app.db.session as _session_mod

    return _session_mod.AsyncSessionLocal()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _agent_token(user: str, profile: str, line: str = "loans") -> str:
    return create_access_token(
        {
            "sub": user,
            "role": "agent",
            "business_line": line,
            "agent_profile_uuid": profile,
            "platform_scope": "false",
        }
    )


async def _user(db, first: str, last: str) -> User:
    user = User(
        first_name=first,
        last_name=last,
        mobile=unique_mobile(),
        email=f"u_{uuid.uuid4().hex[:12]}@example.com",
        password_hash="x",
    )
    db.add(user)
    await db.flush()
    return user


async def _agent(db, line: str, *, user: User | None = None, active: bool = True) -> AgentProfile:
    user = user or await _user(db, "Test", "Agent")
    agent = AgentProfile(
        auth_user_uuid=user.id,
        agent_code=f"AG-{uuid.uuid4().hex[:8]}",
        business_line=line,
        status=ProfileStatus.ACTIVE if active else ProfileStatus.INACTIVE,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _staff(db, role: StaffRole, first: str, last: str, line: str | None) -> StaffProfile:
    user = await _user(db, first, last)
    staff = StaffProfile(
        auth_user_uuid=user.id,
        role=role,
        scope=ProfileScope.LINE if line else ProfileScope.PLATFORM,
        business_line=line,
        staff_code=f"ST-{uuid.uuid4().hex[:8]}",
        status=ProfileStatus.ACTIVE,
    )
    db.add(staff)
    await db.flush()
    return staff


async def _client_profile(db, line: str) -> ClientProfile:
    user = await _user(db, "Client", "Person")
    profile = ClientProfile(
        auth_user_uuid=user.id,
        business_line=line,
        customer_code=f"CL{uuid.uuid4().hex[:8]}",
        status=ProfileStatus.ACTIVE,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _lead(db, agent: AgentProfile, line: str, name: str) -> Lead:
    lead = Lead(
        name=name,
        mobile=unique_mobile(),
        business_line=line,
        status=LeadStatus.CONVERTED,
        origin=LeadOrigin.AGENT,
        origin_agent_profile_uuid=agent.id,
    )
    db.add(lead)
    await db.flush()
    return lead


async def _loan(
    db,
    lead: Lead,
    client: ClientProfile,
    line: str,
    loan_type: LoanType,
    bank: Bank | None,
    *,
    status: LoanStatus = LoanStatus.DISBURSED,
    sanctioned: int | None = 2_500_000,
) -> LoanApplication:
    loan = LoanApplication(
        lead_uuid=lead.id,
        client_profile_uuid=client.id,
        business_line=line,
        loan_type_id=loan_type.id,
        bank_id=bank.id if bank else None,
        amount_requested=3_000_000,
        amount_sanctioned=sanctioned,
        status=status,
        status_reason="internal bank note",
        interest_rate=8.5,
        opened_at=datetime(2026, 9, 1, tzinfo=UTC),
        disbursed_at=datetime(2026, 9, 20, tzinfo=UTC) if status == LoanStatus.DISBURSED else None,
    )
    db.add(loan)
    await db.flush()
    return loan


def _listing(title: str, *, active: bool = False) -> Property:
    return Property(
        business_line="real_estate",
        active=active,
        title=title,
        type="Apartment",
        location="Hidden Locality, City",
        price_display="₹90 L",
        category="apartments",
        city="City",
        locality="Hidden Locality",
        pincode="560001",
        price_paise=9_000_000_000,
        bhk=3,
        area_sqft=1500,
        amenities=[],
        age_years=0,
        rera_applicability="unsure",
        rera_verification_status="not_reviewed",
        details={},
    )


async def _commission(
    db,
    *,
    agent: AgentProfile,
    line: str,
    lead: Lead,
    loan: LoanApplication | PropertyDeal,
    amount: int,
    created_at: datetime,
    entered_by: User,
    paid_at: datetime | None = None,
    maker: StaffProfile | None = None,
    checker: StaffProfile | None = None,
) -> tuple[Commission, Transaction | None, Payout | None]:
    commission = Commission(
        agent_auth_user_uuid=agent.auth_user_uuid,
        agent_profile_uuid=agent.id,
        business_line=line,
        lead_uuid=lead.id,
        loan_application_uuid=loan.id if isinstance(loan, LoanApplication) else None,
        property_deal_uuid=loan.id if isinstance(loan, PropertyDeal) else None,
        agreed_amount_paise=amount,
        status=CommissionStatus.PENDING,
        entered_by_uuid=entered_by.id,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(commission)
    await db.flush()
    if paid_at is None:
        return commission, None, None

    assert maker is not None
    txn = Transaction(
        user_uuid=agent.auth_user_uuid,
        business_line=line,
        type=TransactionType.COMMISSION,
        status=TransactionStatus.PAID,
        amount_paise=amount,
        currency="INR",
        description="Commission payout",
        created_at=paid_at,
        updated_at=paid_at,
    )
    db.add(txn)
    await db.flush()
    payout = Payout(
        recipient_user_uuid=agent.auth_user_uuid,
        business_line=line,
        type=PayoutType.COMMISSION,
        amount_paise=amount,
        currency="INR",
        status=PayoutStatus.PAID,
        destination_type=PayoutDestination.VPA,
        destination_hint="98******10@okhdfc",
        idempotency_key=uuid.uuid4().hex,
        maker_user_uuid=maker.auth_user_uuid,
        checker_user_uuid=checker.auth_user_uuid if checker else None,
        gateway_payout_id=f"pout_secret_{uuid.uuid4().hex[:12]}",
        ledger_transaction_id=txn.id,
        created_at=paid_at - timedelta(days=2),
    )
    db.add(payout)
    await db.flush()
    commission.status = CommissionStatus.PAID
    commission.payout_uuid = payout.id
    commission.payout_txn_uuid = txn.id
    db.add(
        AuditLog(
            actor_uuid=(checker or maker).auth_user_uuid,
            actor_role="admin",
            action=AuditAction.PAYOUT_APPROVED,
            entity_type="payout",
            entity_uuid=payout.id,
            business_line=line,
            detail={"amount_paise": amount},
            created_at=paid_at - timedelta(days=1),
        )
    )
    await db.flush()
    return commission, txn, payout


async def _world() -> dict:
    """A loans Agent with five commissions around the IST month boundary,
    plus a second loans Agent and a cross-line commission for the same account."""
    async with _session() as db:
        admin = await _user(db, "Entry", "Admin")
        maker = await _staff(db, StaffRole.SUB_ADMIN, "Maker", "Person", None)
        checker = await _staff(db, StaffRole.ADMIN, "Checker", "Person", None)
        home = LoanType(
            name=f"home_{uuid.uuid4().hex[:8]}", label=f"Home Loan {uuid.uuid4().hex[:4]}"
        )
        car = LoanType(name=f"car_{uuid.uuid4().hex[:8]}", label=f"Car Loan {uuid.uuid4().hex[:4]}")
        hdfc = Bank(name=f"HDFC Bank {uuid.uuid4().hex[:6]}")
        sbi = Bank(name=f"SBI {uuid.uuid4().hex[:6]}")
        db.add_all([home, car, hdfc, sbi])
        await db.flush()

        agent = await _agent(db, "loans")
        rows = {}
        specs = (
            # key, lead name, loan type, bank, amount, created, paid_at
            (
                "oct_start",
                "Asha Rao",
                home,
                hdfc,
                40_000,
                datetime(2026, 9, 25, tzinfo=UTC),
                _OCT_START,
            ),
            (
                "sep_end",
                "Bina Iyer",
                home,
                sbi,
                1_000,
                datetime(2026, 9, 10, tzinfo=UTC),
                _OCT_START - _SECOND,
            ),
            (
                "oct_end",
                "Chitra Das",
                home,
                hdfc,
                2_000,
                datetime(2026, 10, 5, tzinfo=UTC),
                _NOV_START - _SECOND,
            ),
            (
                "nov_start",
                "Deepa Nair",
                home,
                sbi,
                4_000,
                datetime(2026, 10, 20, tzinfo=UTC),
                _NOV_START,
            ),
            ("pending", "Vikram Shah", car, sbi, 15_000, datetime(2026, 11, 2, tzinfo=UTC), None),
        )
        for key, name, loan_type, bank, amount, created, paid_at in specs:
            lead = await _lead(db, agent, "loans", name)
            # One active application per client: each deal has its own client.
            loan = await _loan(
                db,
                lead,
                await _client_profile(db, "loans"),
                "loans",
                loan_type,
                bank,
                status=LoanStatus.DISBURSED if paid_at else LoanStatus.SANCTIONED,
            )
            commission, txn, payout = await _commission(
                db,
                agent=agent,
                line="loans",
                lead=lead,
                loan=loan,
                amount=amount,
                created_at=created,
                entered_by=admin,
                paid_at=paid_at,
                maker=maker,
                checker=checker,
            )
            rows[key] = {"commission": commission, "lead": lead, "loan": loan, "txn": txn}

        # A second Agent on the same line.
        other = await _agent(db, "loans")
        other_lead = await _lead(db, other, "loans", "Other Client")
        other_loan = await _loan(
            db, other_lead, await _client_profile(db, "loans"), "loans", home, hdfc
        )
        other_commission, other_txn, _ = await _commission(
            db,
            agent=other,
            line="loans",
            lead=other_lead,
            loan=other_loan,
            amount=99_000,
            created_at=datetime(2026, 10, 3, tzinfo=UTC),
            entered_by=admin,
            paid_at=datetime(2026, 10, 12, tzinfo=UTC),
            maker=maker,
            checker=checker,
        )

        # The same account's (inactive) real-estate profile: another line.
        agent_user = await db.get(User, agent.auth_user_uuid)
        re_agent = await _agent(db, "real_estate", user=agent_user, active=False)
        re_client = await _client_profile(db, "real_estate")
        re_lead = await _lead(db, re_agent, "real_estate", "Cross Line")
        re_listing = _listing("Cross Line Villa")
        db.add(re_listing)
        await db.flush()
        re_loan = PropertyDeal(
            lead_uuid=re_lead.id,
            client_profile_uuid=re_client.id,
            property_id=re_listing.id,
            business_line="real_estate",
            status=PropertyDealStatus.CLOSED,
        )
        db.add(re_loan)
        await db.flush()
        re_commission, _, _ = await _commission(
            db,
            agent=re_agent,
            line="real_estate",
            lead=re_lead,
            loan=re_loan,
            amount=77_000,
            created_at=datetime(2026, 10, 3, tzinfo=UTC),
            entered_by=admin,
        )
        await db.commit()
        return {
            "agent": agent,
            "token": _agent_token(str(agent.auth_user_uuid), str(agent.id)),
            "rows": rows,
            "home": home,
            "car": car,
            "hdfc": hdfc,
            "sbi": sbi,
            "other": other,
            "other_token": _agent_token(str(other.auth_user_uuid), str(other.id)),
            "other_commission": other_commission,
            "other_txn": other_txn,
            "re_commission": re_commission,
            "maker": maker,
            "checker": checker,
        }


@contextlib.asynccontextmanager
async def _agent_rules(*denied: tuple[str, str]) -> AsyncIterator[None]:
    """Temporarily switch Agent field rules off; always restores defaults."""

    async def clear() -> None:
        async with _session() as db:
            for entity, field_key in denied:
                await db.execute(
                    delete(FieldVisibilityConfig).where(
                        FieldVisibilityConfig.target_role == FieldTargetRole.AGENT,
                        FieldVisibilityConfig.entity == entity,
                        FieldVisibilityConfig.field_key == field_key,
                    )
                )
            await db.commit()

    await clear()
    async with _session() as db:
        for entity, field_key in denied:
            db.add(
                FieldVisibilityConfig(
                    target_role=FieldTargetRole.AGENT,
                    entity=entity,
                    field_key=field_key,
                    mode=FieldVisibilityMode.DENY,
                )
            )
        await db.commit()
    try:
        yield
    finally:
        await clear()


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_dashboard, "_utcnow", lambda: _NOW)


# ---------------------------------------------------------------------------
# Commission history
# ---------------------------------------------------------------------------


async def test_previous_month_is_the_ist_calendar_month() -> None:
    first, last, start, end = agent_dashboard.previous_month(_NOW)
    assert (first, last) == (date(2026, 10, 1), date(2026, 10, 31))
    assert start.astimezone(UTC) == _OCT_START
    assert end.astimezone(UTC) == _NOV_START
    # 1 Nov 03:00 IST is still 31 Oct in UTC, but the month is already November.
    first, _, _, _ = agent_dashboard.previous_month(datetime(2026, 10, 31, 21, 30, tzinfo=UTC))
    assert first == date(2026, 10, 1)
    # January rolls back into December of the previous year.
    first, last, _, _ = agent_dashboard.previous_month(datetime(2027, 1, 5, tzinfo=UTC))
    assert (first, last) == (date(2026, 12, 1), date(2026, 12, 31))


async def test_earnings_rows_carry_client_deal_and_ist_last_month_total(
    client: AsyncClient, frozen_now: None
) -> None:
    world = await _world()
    res = await client.get("/api/v1/agent/earnings", headers=_headers(world["token"]))
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()

    ids = {row["id"] for row in body["rows"]}
    assert ids == {str(entry["commission"].id) for entry in world["rows"].values()}
    totals = body["totals"]
    # Paid at exactly 1 Oct 00:00 IST and at 31 Oct 23:59:59 IST count; the
    # second before October and 1 Nov 00:00 IST do not.
    assert totals["last_month_paid_amount_paise"] == 42_000
    assert totals["last_month_start"] == "2026-10-01"
    assert totals["last_month_end"] == "2026-10-31"
    assert totals["paid_amount_paise"] == 47_000
    assert totals["pending_amount_paise"] == 15_000
    assert totals["total_amount_paise"] == 62_000
    assert body["hidden_fields"] == []

    row = next(
        r for r in body["rows"] if r["id"] == str(world["rows"]["oct_start"]["commission"].id)
    )
    assert row["client_name"] == "Asha Rao"
    assert row["lead_uuid"] == str(world["rows"]["oct_start"]["lead"].id)
    assert row["lead_status"] == "converted"
    assert row["product_label"] == world["home"].label
    assert row["product_uuid"] == str(world["home"].id)
    assert row["bank_name"] == world["hdfc"].name
    assert row["deal_status"] == "disbursed"
    assert row["deal_amount"] == "2500000.00"
    assert row["status"] == "paid"
    assert row["paid_at"].startswith("2026-09-30T18:30:00")
    assert row["property_title"] is None
    # Internal loan fields never reach the Agent.
    assert "status_reason" not in res.text
    assert "internal bank note" not in res.text


async def test_earnings_filters(client: AsyncClient, frozen_now: None) -> None:
    world = await _world()
    rows = world["rows"]

    async def ids(query: str) -> set[str]:
        res = await client.get(
            "/api/v1/agent/earnings",
            params=dict(pair.split("=", 1) for pair in query.split("&")),
            headers=_headers(world["token"]),
        )
        assert res.status_code == 200, res.text
        # Filters narrow the rows, never the totals.
        assert res.json()["totals"]["total_amount_paise"] == 62_000
        return {row["id"] for row in res.json()["rows"]}

    def cid(*keys: str) -> set[str]:
        return {str(rows[key]["commission"].id) for key in keys}

    assert await ids("status=pending") == cid("pending")
    assert await ids(f"product_id={world['car'].id}") == cid("pending")
    assert await ids(f"bank_id={world['hdfc'].id}") == cid("oct_start", "oct_end")
    assert await ids("amount_min_paise=2000&amount_max_paise=15000") == cid(
        "oct_end", "nov_start", "pending"
    )
    # IST calendar days on the entry date.
    assert await ids("date_from=2026-10-01&date_to=2026-10-31") == cid("oct_end", "nov_start")
    assert await ids("q=vikram") == cid("pending")
    # Bank names carry a unique suffix; search is case-insensitive.
    sbi_suffix = world["sbi"].name.split()[-1].upper()
    assert await ids(f"q={sbi_suffix}") == cid("sep_end", "nov_start", "pending")
    assert await ids(f"q={str(rows['oct_end']['lead'].id)[:8]}") == cid("oct_end")
    assert await ids("deal_type=property_deal") == set()
    assert await ids("property_category=villas") == set()

    for bad in (
        "amount_min_paise=5000&amount_max_paise=10",
        "date_from=2026-11-02&date_to=2026-11-01",
        "status=refunded",
        "amount_min_paise=-1",
    ):
        res = await client.get(f"/api/v1/agent/earnings?{bad}", headers=_headers(world["token"]))
        assert res.status_code == 422, bad


async def test_earnings_isolated_between_agents_and_lines(
    client: AsyncClient, frozen_now: None
) -> None:
    world = await _world()
    mine = await client.get("/api/v1/agent/earnings", headers=_headers(world["token"]))
    mine_ids = {row["id"] for row in mine.json()["rows"]}
    assert str(world["other_commission"].id) not in mine_ids
    # Same account, other line (its real-estate profile) never appears.
    assert str(world["re_commission"].id) not in mine_ids

    theirs = await client.get("/api/v1/agent/earnings", headers=_headers(world["other_token"]))
    assert {row["id"] for row in theirs.json()["rows"]} == {str(world["other_commission"].id)}

    # A token whose line does not match the commission line sees nothing.
    agent = world["agent"]
    mismatched = _agent_token(str(agent.auth_user_uuid), str(agent.id), "real_estate")
    res = await client.get("/api/v1/agent/earnings", headers=_headers(mismatched))
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == []
    assert res.json()["totals"]["total_amount_paise"] == 0


async def test_hidden_client_name_is_null_and_not_searchable(
    client: AsyncClient, frozen_now: None
) -> None:
    world = await _world()
    async with _agent_rules(("lead", "name"), ("deal", "amount")):
        res = await client.get("/api/v1/agent/earnings", headers=_headers(world["token"]))
        body = res.json()
        assert sorted(body["hidden_fields"]) == ["client_name", "deal_amount"]
        assert all(row["client_name"] is None for row in body["rows"])
        assert all(row["deal_amount"] is None for row in body["rows"])
        assert "Asha Rao" not in res.text
        search = await client.get("/api/v1/agent/earnings?q=asha", headers=_headers(world["token"]))
        assert search.json()["rows"] == []


# ---------------------------------------------------------------------------
# Transaction detail
# ---------------------------------------------------------------------------


async def test_transaction_detail_shows_payout_trail_and_the_commission_it_paid(
    client: AsyncClient,
) -> None:
    world = await _world()
    entry = world["rows"]["oct_end"]
    res = await client.get(
        f"/api/v1/agent/transactions/{entry['txn'].id}", headers=_headers(world["token"])
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["amount_paise"] == 2_000
    payout = body["payout"]
    assert payout["method"] == "vpa"
    assert payout["destination_hint"] == "98******10@okhdfc"
    assert payout["status"] == "paid"
    assert payout["requested_at"] is not None
    assert payout["approved_at"] is not None
    assert payout["paid_at"].startswith("2026-10-31T18:29:59")
    assert payout["requested_by"] == {"name": "Maker Person", "role": "sub_admin"}
    assert payout["approved_by"] == {"name": "Checker Person", "role": "admin"}
    assert payout["approval_mode"] == "maker_checker"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["commission_id"] == str(entry["commission"].id)
    assert item["client_name"] == "Chitra Das"
    assert item["product_label"] == world["home"].label
    assert item["deal_status"] == "disbursed"
    # Provider plumbing stays Admin-only.
    for secret in ("pout_secret_", "idempotency", "gateway", "fingerprint"):
        assert secret not in res.text

    async with _agent_rules(("payout", "staff_names")):
        hidden = await client.get(
            f"/api/v1/agent/transactions/{entry['txn'].id}", headers=_headers(world["token"])
        )
        payout = hidden.json()["payout"]
        assert payout["requested_by"] == {"name": None, "role": "sub_admin"}
        assert payout["approved_by"] == {"name": None, "role": "admin"}
        assert "staff_names" in hidden.json()["hidden_fields"]
        assert "Maker Person" not in hidden.text


async def test_transaction_detail_is_owner_only(client: AsyncClient) -> None:
    world = await _world()
    own = world["rows"]["oct_start"]["txn"].id
    # Another Agent cannot open it, and cannot open an unknown id either.
    for txn_id in (own, uuid.uuid4()):
        res = await client.get(
            f"/api/v1/agent/transactions/{txn_id}", headers=_headers(world["other_token"])
        )
        assert res.status_code == 404, res.text
    # The owner cannot open someone else's.
    res = await client.get(
        f"/api/v1/agent/transactions/{world['other_txn'].id}", headers=_headers(world["token"])
    )
    assert res.status_code == 404, res.text


# ---------------------------------------------------------------------------
# Lead history
# ---------------------------------------------------------------------------


async def _loans_history_world() -> dict:
    async with _session() as db:
        agent = await _agent(db, "loans")
        other = await _agent(db, "loans")
        telecaller = await _staff(db, StaffRole.TELECALLER, "Tara", "Caller", "loans")
        client = await _client_profile(db, "loans")
        loan_type = LoanType(name=f"pl_{uuid.uuid4().hex[:8]}", label="Personal Loan")
        bank = Bank(name=f"Axis {uuid.uuid4().hex[:6]}")
        db.add_all([loan_type, bank])
        await db.flush()
        lead = await _lead(db, agent, "loans", "History Lead")
        lead.created_at = datetime(2026, 9, 1, tzinfo=UTC)
        loan = await _loan(db, lead, client, "loans", loan_type, bank)
        db.add_all(
            [
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=telecaller.id,
                    business_line="loans",
                    disposition=CallDisposition.CONNECTED,
                    interest_level=InterestLevel.HOT,
                    notes="Wants a quick sanction",
                    follow_up_at=datetime(2026, 9, 5, tzinfo=UTC),
                    created_at=datetime(2026, 9, 3, tzinfo=UTC),
                ),
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=telecaller.id,
                    business_line="loans",
                    disposition=CallDisposition.NO_ANSWER,
                    created_at=datetime(2026, 9, 2, tzinfo=UTC),
                ),
                AuditLog(
                    action=AuditAction.LEAD_ASSIGNED,
                    entity_type="lead",
                    entity_uuid=lead.id,
                    business_line="loans",
                    detail={
                        "mode": "automatic",
                        "telecaller_staff_profile_uuid": str(telecaller.id),
                    },
                    created_at=datetime(2026, 9, 1, 1, tzinfo=UTC),
                ),
                AuditLog(
                    action=AuditAction.LOAN_APPLICATION_UPDATED,
                    entity_type="loan_application",
                    entity_uuid=loan.id,
                    business_line="loans",
                    detail={"previous_status": "sanctioned", "status": "disbursed", "fields": []},
                    created_at=datetime(2026, 9, 20, tzinfo=UTC),
                ),
                # A field-only edit (no status change) is not a timeline event.
                AuditLog(
                    action=AuditAction.LOAN_APPLICATION_UPDATED,
                    entity_type="loan_application",
                    entity_uuid=loan.id,
                    business_line="loans",
                    detail={"previous_status": "disbursed", "status": "disbursed"},
                    created_at=datetime(2026, 9, 21, tzinfo=UTC),
                ),
                # Payout plumbing on an unrelated entity never appears.
                AuditLog(
                    action=AuditAction.PAYOUT_APPROVED,
                    entity_type="payout",
                    entity_uuid=loan.id,
                    business_line="loans",
                    detail={},
                    created_at=datetime(2026, 9, 22, tzinfo=UTC),
                ),
            ]
        )
        await db.commit()
        return {
            "lead": lead,
            "loan": loan,
            "token": _agent_token(str(agent.auth_user_uuid), str(agent.id)),
            "other_token": _agent_token(str(other.auth_user_uuid), str(other.id)),
            "agent": agent,
        }


async def test_lead_history_shows_requests_calls_and_timeline(client: AsyncClient) -> None:
    world = await _loans_history_world()
    res = await client.get(
        f"/api/v1/agent/leads/{world['lead'].id}/history", headers=_headers(world["token"])
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["status"] == "converted"
    assert body["hidden_fields"] == []

    (application,) = body["applications"]
    assert application["id"] == str(world["loan"].id)
    assert application["product_label"] == "Personal Loan"
    assert application["status"] == "disbursed"
    assert application["amount_sanctioned"] == "2500000.00"
    assert "status_reason" not in application and "interest_rate" not in application
    assert "internal bank note" not in res.text

    assert [call["disposition"] for call in body["calls"]] == ["connected", "no_answer"]
    assert body["calls"][0]["notes"] == "Wants a quick sanction"
    assert body["calls"][0]["interest_level"] == "hot"
    assert body["calls"][0]["staff_name"] == "Tara Caller"

    events = [(e["event"], e["to_status"]) for e in body["timeline"]]
    assert events == [
        ("introduced", None),
        ("lead_assigned", None),
        ("loan_application_updated", "disbursed"),
    ]
    assert body["timeline"][2]["request_id"] == str(world["loan"].id)
    assert body["timeline"][2]["from_status"] == "sanctioned"
    assert "telecaller_staff_profile_uuid" not in res.text


async def test_lead_history_follows_agent_field_rules(client: AsyncClient) -> None:
    world = await _loans_history_world()
    async with _agent_rules(
        ("lead_history", "call_notes"), ("lead_history", "staff_names"), ("deal", "amount")
    ):
        res = await client.get(
            f"/api/v1/agent/leads/{world['lead'].id}/history", headers=_headers(world["token"])
        )
        body = res.json()
        assert sorted(body["hidden_fields"]) == ["call_notes", "deal_amount", "staff_names"]
        assert all(call["notes"] is None for call in body["calls"])
        assert all(call["staff_name"] is None for call in body["calls"])
        assert body["applications"][0]["amount_sanctioned"] is None
        assert "Wants a quick sanction" not in res.text
        assert "Tara" not in res.text


async def test_lead_history_is_only_for_the_originating_agent(client: AsyncClient) -> None:
    world = await _loans_history_world()
    url = f"/api/v1/agent/leads/{world['lead'].id}/history"
    assert (await client.get(url, headers=_headers(world["other_token"]))).status_code == 404
    unknown = f"/api/v1/agent/leads/{uuid.uuid4()}/history"
    assert (await client.get(unknown, headers=_headers(world["token"]))).status_code == 404
    # The originating Agent's token on the wrong line reads nothing.
    agent = world["agent"]
    wrong_line = _agent_token(str(agent.auth_user_uuid), str(agent.id), "real_estate")
    assert (await client.get(url, headers=_headers(wrong_line))).status_code == 404


async def test_history_does_not_widen_full_row_routes(client: AsyncClient) -> None:
    """The reach is a confined function, not a table policy: the RLS-only
    request routes still return nothing of the Agent's leads."""
    world = await _loans_history_world()
    headers = _headers(world["token"])
    for url in ("/api/v1/loans/applications", "/api/v1/loans/enquiries", "/api/v1/property-deals"):
        res = await client.get(url, headers=headers)
        assert res.status_code == 200, (url, res.text)
        payload = res.json()
        listed = next(iter(payload.values()))
        assert listed == [], url
    res = await client.get(f"/api/v1/loans/applications/{world['loan'].id}", headers=headers)
    assert res.status_code == 404


async def test_real_estate_history_has_deals_visits_and_enquiries(client: AsyncClient) -> None:
    async with _session() as db:
        agent = await _agent(db, "real_estate")
        client_profile = await _client_profile(db, "real_estate")
        client_user_uuid = client_profile.auth_user_uuid
        listing = _listing("Lakeview 3BHK")
        db.add(listing)
        await db.flush()
        lead = await _lead(db, agent, "real_estate", "Estate Lead")
        visit = SiteVisit(
            user_uuid=client_user_uuid,
            business_line="real_estate",
            lead_uuid=lead.id,
            property_ref=str(listing.id),
            title="Lakeview 3BHK",
            locality="Hidden Locality",
            city="City",
            contact_name="Private Contact",
            contact_mobile="+919800000001",
            preferred_date=date(2026, 10, 2),
            preferred_time_slot=SiteVisitTimeSlot.MORNING,
            message="Private visit message",
            status=SiteVisitStatus.DONE,
        )
        enquiry = Enquiry(
            user_uuid=client_user_uuid,
            business_line="real_estate",
            lead_uuid=lead.id,
            property_ref=str(listing.id),
            title="Lakeview 3BHK",
            locality="Hidden Locality",
            city="City",
            contact_name="Private Contact",
            contact_mobile="+919800000001",
            message="Private enquiry message",
            status=EnquiryStatus.CONTACTED,
        )
        db.add_all([visit, enquiry])
        await db.flush()
        deal = PropertyDeal(
            lead_uuid=lead.id,
            client_profile_uuid=client_profile.id,
            property_id=listing.id,
            business_line="real_estate",
            site_visit_uuid=visit.id,
            price_quoted=9_000_000,
            booking_amount=100_000,
            status=PropertyDealStatus.BOOKED,
            status_reason="private negotiation note",
        )
        db.add(deal)
        await db.commit()
        token = _agent_token(str(agent.auth_user_uuid), str(agent.id), "real_estate")

    res = await client.get(f"/api/v1/agent/leads/{lead.id}/history", headers=_headers(token))
    assert res.status_code == 200, res.text
    body = res.json()
    (deal_row,) = body["deals"]
    # The listing is unpublished; the Agent still sees which property it was.
    assert deal_row["property_title"] == "Lakeview 3BHK"
    assert deal_row["property_category"] == "apartments"
    assert deal_row["status"] == "booked"
    assert deal_row["price_quoted"] == "9000000.00"
    (visit_row,) = body["site_visits"]
    assert visit_row["preferred_time_slot"] == "morning"
    assert visit_row["status"] == "done"
    (enquiry_row,) = body["enquiries"]
    assert enquiry_row["status"] == "contacted"
    for private in (
        "Private Contact",
        "+919800000001",
        "Private visit message",
        "Private enquiry message",
        "private negotiation note",
    ):
        assert private not in res.text


# ---------------------------------------------------------------------------
# The confined functions re-check the caller themselves
# ---------------------------------------------------------------------------


async def _call_as(sql: str, params: dict, settings: dict[str, str]):
    async with _session() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        for key, value in settings.items():
            await db.execute(text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value})
        result = await db.execute(text(sql), params)
        rows = result.all()
        await db.rollback()
        return rows


async def test_confined_functions_refuse_other_contexts() -> None:
    world = await _world()
    agent = world["agent"]
    lead_id = str(world["rows"]["oct_start"]["lead"].id)
    txn_id = str(world["rows"]["oct_start"]["txn"].id)
    telecaller = {
        "app.role": "telecaller",
        "app.auth_user_uuid": str(agent.auth_user_uuid),
        "app.staff_profile_uuid": str(uuid.uuid4()),
        "app.agent_profile_uuid": str(agent.id),
        "app.business_line": "loans",
    }
    owner = {
        "app.role": "agent",
        "app.auth_user_uuid": str(agent.auth_user_uuid),
        "app.agent_profile_uuid": str(agent.id),
        "app.business_line": "loans",
    }
    other = world["other"]
    other_agent = {
        "app.role": "agent",
        "app.auth_user_uuid": str(other.auth_user_uuid),
        "app.agent_profile_uuid": str(other.id),
        "app.business_line": "loans",
    }
    # A forged profile claim for someone else's Agent profile.
    forged = {**other_agent, "app.agent_profile_uuid": str(agent.id)}

    assert len(await _call_as("SELECT * FROM agent_commission_ledger()", {}, owner)) == 5
    for context in (telecaller, other_agent, forged):
        rows = await _call_as("SELECT * FROM agent_commission_ledger()", {}, context)
        assert {row.commission_uuid for row in rows}.isdisjoint(
            {entry["commission"].id for entry in world["rows"].values()}
        )
        (history,) = await _call_as(
            "SELECT agent_lead_history(CAST(:id AS uuid))", {"id": lead_id}, context
        )
        assert history[0] is None
        (detail,) = await _call_as(
            "SELECT agent_transaction_detail(CAST(:id AS uuid))", {"id": txn_id}, context
        )
        assert detail[0] is None
