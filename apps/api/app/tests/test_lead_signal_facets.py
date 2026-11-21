"""CS-023: product, property and transaction filters (migration f1b3d5a7c9e2).

Covers, end to end:

* ``lead_list_signals`` / ``team_lead_signals`` return one entry per loan
  application and property deal on the lead's line, and the loan-transaction
  summary only to callers with ``loan_txn_history`` reach (assigned
  Telecaller; manager through the Telecaller); Agents only for leads they
  introduced, without referral codes, calls or transactions;
* transaction summary correctness (count, distinct trimmed banks, min/max,
  first/last date) and the Admin's Telecaller field rules on it;
* list responses (Telecaller leads, Employee tasks, team work) carry ids and
  enums only — no application or deal amounts;
* each new analytics filter per role narrows, one application must match all
  loan filters at once, and invalid role / line / field-rule pairs are 422;
* team analytics: the same names, and lead source now works for managers;
* Admin reports: property subtype, amount range, product filters on the
  leads report, and "Referred by client" matching the staff lists.

Requires the Docker stack with migrations applied; auto-skips without Redis.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token
from app.tests.test_admin_hierarchy_api import _headers, _sub_admin
from app.tests.test_staff_teams_api import seed_line_staff, seed_team
from conftest import unique_mobile

# --- Seeding -------------------------------------------------------------------


async def _staff(role: str, line: str = "loans") -> tuple[uuid.UUID, uuid.UUID]:
    return await seed_line_staff(role, line)


async def _agent(line: str = "loans") -> tuple[uuid.UUID, uuid.UUID]:
    import app.db.session as session_mod
    from app.models.profile import AgentProfile, ProfileStatus
    from app.models.user import User

    async with session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Facet",
            last_name="Agent",
            mobile=unique_mobile(),
            email=f"fa_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = AgentProfile(
            auth_user_uuid=user.id,
            agent_code=f"AG-{uuid.uuid4().hex[:8]}",
            business_line=line,
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return user.id, profile.id


async def _lead(
    line: str = "loans",
    *,
    telecaller: uuid.UUID | None = None,
    agent: uuid.UUID | None = None,
    status: str = "working",
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus

    async with session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            name="Facet Lead",
            mobile=unique_mobile(),
            business_line=line,
            status=LeadStatus(status),
            origin=LeadOrigin.AGENT if agent else LeadOrigin.DIRECT,
            origin_agent_profile_uuid=agent,
            assigned_telecaller_profile_uuid=telecaller,
        )
        db.add(lead)
        await db.commit()
        return lead.id


async def _client_profile(db: Any, line: str) -> uuid.UUID:
    from app.models.profile import ClientProfile, ProfileStatus
    from app.models.user import User

    user = User(
        first_name="Facet",
        last_name="Client",
        mobile=unique_mobile(),
        email=f"fc_{uuid.uuid4().hex[:12]}@example.com",
        password_hash="x",
    )
    db.add(user)
    await db.flush()
    profile = ClientProfile(
        auth_user_uuid=user.id,
        business_line=line,
        customer_code=f"CL{uuid.uuid4().hex[:8]}",
        status=ProfileStatus.ACTIVE,
    )
    db.add(profile)
    await db.flush()
    return profile.id


async def _catalogue() -> tuple[uuid.UUID, uuid.UUID]:
    """A fresh loan type and bank. Returns (loan_type_id, bank_id)."""
    import app.db.session as session_mod
    from app.models.loan import Bank, LoanType

    async with session_mod.AsyncSessionLocal() as db:
        loan_type = LoanType(name=f"lt_{uuid.uuid4().hex[:8]}", label="Facet Loan")
        bank = Bank(name=f"Facet Bank {uuid.uuid4().hex[:8]}")
        db.add_all([loan_type, bank])
        await db.commit()
        return loan_type.id, bank.id


async def _loan(
    lead_id: uuid.UUID,
    loan_type_id: uuid.UUID,
    bank_id: uuid.UUID | None,
    *,
    status: str = "new",
    amount: int = 500_000,
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.loan import LoanApplication, LoanStatus

    async with session_mod.AsyncSessionLocal() as db:
        application = LoanApplication(
            lead_uuid=lead_id,
            client_profile_uuid=await _client_profile(db, "loans"),
            business_line="loans",
            loan_type_id=loan_type_id,
            bank_id=bank_id,
            amount_requested=amount,
            status=LoanStatus(status),
        )
        db.add(application)
        await db.commit()
        return application.id


async def _txn(application_id: uuid.UUID, bank: str, amount: str, on: date) -> None:
    import app.db.session as session_mod
    from app.models.loan import LoanTxnHistory

    async with session_mod.AsyncSessionLocal() as db:
        db.add(
            LoanTxnHistory(
                loan_application_uuid=application_id,
                business_line="loans",
                bank_name=bank,
                amount=Decimal(amount),
                interest_rate=Decimal("8.5"),
                txn_date=on,
            )
        )
        await db.commit()


async def _deal(
    lead_id: uuid.UUID,
    *,
    category: str = "apartments",
    subtype: str | None = "gated_community_apartment",
    status: str = "new",
    price: int = 8_000_000,
    active: bool = True,
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.property import Property
    from app.models.property_deal import PropertyDeal, PropertyDealStatus

    async with session_mod.AsyncSessionLocal() as db:
        prop = Property(
            business_line="real_estate",
            active=active,
            title=f"Facet Property {uuid.uuid4().hex[:8]}",
            type="Apartment",
            location="Facet Locality, Facet City",
            price_display="₹80 L",
            category=category,
            property_subtype=subtype,
            city="Facet City",
            locality="Facet Locality",
            pincode="560001",
            price_paise=80_000_000,
            bhk=2,
            area_sqft=1100,
            furnishing="furnished",
            construction_status="ready",
            amenities=[],
            age_years=1,
            rera_number=f"RERA/FACET/{uuid.uuid4().hex[:8]}",
            details={},
        )
        client_profile = await _client_profile(db, "real_estate")
        db.add(prop)
        await db.flush()
        deal = PropertyDeal(
            lead_uuid=lead_id,
            client_profile_uuid=client_profile,
            property_id=prop.id,
            business_line="real_estate",
            status=PropertyDealStatus(status),
            price_quoted=price,
        )
        db.add(deal)
        await db.commit()
        return deal.id


async def _task(
    lead_id: uuid.UUID, raiser: uuid.UUID, employee: uuid.UUID, line: str = "loans"
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.task import Task, TaskStatus, TaskType

    async with session_mod.AsyncSessionLocal() as db:
        task = Task(
            lead_uuid=lead_id,
            business_line=line,
            task_type=TaskType.DOCUMENT_COLLECTION,
            status=TaskStatus.ASSIGNED,
            raised_by_staff_profile_uuid=raiser,
            assigned_employee_profile_uuid=employee,
        )
        db.add(task)
        await db.commit()
        return task.id


async def _commission(
    agent_auth: uuid.UUID,
    agent_profile: uuid.UUID,
    lead_id: uuid.UUID,
    *,
    loan: uuid.UUID | None = None,
    deal: uuid.UUID | None = None,
    line: str = "loans",
    paise: int = 50_000,
    status: str = "pending",
) -> uuid.UUID:
    import app.db.session as session_mod
    from app.models.commission import Commission, CommissionStatus
    from app.models.user import User

    async with session_mod.AsyncSessionLocal() as db:
        admin = User(
            first_name="Facet",
            last_name="Admin",
            mobile=unique_mobile(),
            email=f"fadm_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(admin)
        await db.flush()
        commission = Commission(
            agent_auth_user_uuid=agent_auth,
            agent_profile_uuid=agent_profile,
            business_line=line,
            lead_uuid=lead_id,
            loan_application_uuid=loan,
            property_deal_uuid=deal,
            agreed_amount_paise=paise,
            entered_by_uuid=admin.id,
        )
        db.add(commission)
        await db.flush()
        if status != "pending":
            await db.execute(
                text(
                    "UPDATE commissions SET status = CAST(:status AS commission_status) "
                    "WHERE id = :id"
                ),
                {"status": status, "id": commission.id},
            )
        await db.commit()
        _ = CommissionStatus
        return commission.id


async def _referral_by_account(lead_id: uuid.UUID) -> str:
    """The lead's client signed up through a referral link (no mobile match)."""
    import app.db.session as session_mod
    from app.models.lead import Lead
    from app.models.profile import ClientProfile
    from app.models.referral import Referral, ReferralCode
    from app.models.user import User

    code = "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(8))
    async with session_mod.AsyncSessionLocal() as db:
        referrer = User(
            first_name="Ref",
            last_name="Errer",
            mobile=unique_mobile(),
            email=f"fref_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(referrer)
        await db.flush()
        db.add(ReferralCode(auth_user_uuid=referrer.id, code=code))
        lead = await db.get(Lead, lead_id)
        client_profile_id = await _client_profile(db, lead.business_line)
        lead.client_profile_uuid = client_profile_id
        client = await db.get(ClientProfile, client_profile_id)
        db.add(
            Referral(
                referrer_auth_user_uuid=referrer.id,
                referred_mobile=unique_mobile(),
                referred_auth_user_uuid=client.auth_user_uuid,
            )
        )
        await db.commit()
    return code


class _Rule:
    """Temporarily set one Admin field rule; restores the previous state."""

    def __init__(self, role: str, entity: str, field_key: str, mode: str = "deny") -> None:
        self.args = (role, entity, field_key, mode)
        self.previous: str | None = None

    async def __aenter__(self) -> None:
        import app.db.session as session_mod
        from app.models.field_visibility import (
            FieldTargetRole,
            FieldVisibilityConfig,
            FieldVisibilityMode,
        )

        role, entity, field_key, mode = self.args
        async with session_mod.AsyncSessionLocal() as db:
            row = await db.scalar(
                select(FieldVisibilityConfig).where(
                    FieldVisibilityConfig.target_role == FieldTargetRole(role),
                    FieldVisibilityConfig.entity == entity,
                    FieldVisibilityConfig.field_key == field_key,
                )
            )
            self.previous = row.mode.value if row else None
            if row is None:
                db.add(
                    FieldVisibilityConfig(
                        target_role=FieldTargetRole(role),
                        entity=entity,
                        field_key=field_key,
                        mode=FieldVisibilityMode(mode),
                    )
                )
            else:
                row.mode = FieldVisibilityMode(mode)
            await db.commit()

    async def __aexit__(self, *_exc: object) -> None:
        import app.db.session as session_mod
        from app.models.field_visibility import (
            FieldTargetRole,
            FieldVisibilityConfig,
            FieldVisibilityMode,
        )

        role, entity, field_key, _mode = self.args
        async with session_mod.AsyncSessionLocal() as db:
            row = await db.scalar(
                select(FieldVisibilityConfig).where(
                    FieldVisibilityConfig.target_role == FieldTargetRole(role),
                    FieldVisibilityConfig.entity == entity,
                    FieldVisibilityConfig.field_key == field_key,
                )
            )
            if self.previous is None:
                await db.delete(row)
            else:
                row.mode = FieldVisibilityMode(self.previous)
            await db.commit()


def _token(auth: uuid.UUID, role: str, line: str = "loans", **claims: Any) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(auth),
            "role": role,
            "business_line": line,
            "platform_scope": "false",
            **{key: str(value) for key, value in claims.items()},
        }
    )
    return {"Authorization": f"Bearer {token}"}


async def _signals_as(
    function: str, lead_ids: list[uuid.UUID], *, context: dict[str, str]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Call a signals function as api_user with an RLS context."""
    engine = create_async_engine(
        settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432"),
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )
    settings_sql = ", ".join(
        f"set_config('app.{key}', :{key}, true)"
        for key in (
            "auth_user_uuid",
            "role",
            "business_line",
            "client_profile_uuid",
            "agent_profile_uuid",
            "staff_profile_uuid",
            "platform_scope",
        )
    )
    values = {
        "auth_user_uuid": str(uuid.uuid4()),
        "business_line": "loans",
        "client_profile_uuid": "",
        "agent_profile_uuid": "",
        "staff_profile_uuid": "",
        "platform_scope": "false",
        **context,
    }
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(text(f"SELECT {settings_sql}"), values)
            result = await conn.execute(
                text(f"SELECT * FROM {function}(CAST(:ids AS uuid[]))"),
                {"ids": [str(lead_id) for lead_id in lead_ids]},
            )
            return {row["lead_uuid"]: dict(row) for row in result.mappings()}
    finally:
        await engine.dispose()


def _kpis(body: dict) -> dict[str, float | None]:
    return {kpi["key"]: kpi["value"] for kpi in body["kpis"]}


# --- lead_list_signals ----------------------------------------------------------


@pytest.mark.asyncio
async def test_telecaller_signals_carry_items_and_transaction_summary(
    client: AsyncClient,
) -> None:
    _, tele = await _staff("telecaller")
    lead = await _lead(telecaller=tele)
    loan_type, bank = await _catalogue()
    first = await _loan(lead, loan_type, bank, status="sanctioned", amount=700_000)
    second = await _loan(lead, loan_type, None, status="new", amount=200_000)
    await _txn(first, "  HDFC Bank ", "250000.50", date(2026, 3, 1))
    await _txn(first, "HDFC Bank", "100000.00", date(2026, 1, 15))
    await _txn(second, "Axis Bank", "900000.00", date(2026, 5, 9))
    await _txn(second, "   ", "50000.00", date(2026, 2, 1))

    rows = await _signals_as(
        "lead_list_signals",
        [lead],
        context={"role": "telecaller", "staff_profile_uuid": str(tele)},
    )

    row = rows[lead]
    loans = {item["id"]: item for item in row["loan_items"]}
    assert set(loans) == {str(first), str(second)}
    assert loans[str(first)]["loan_type_id"] == str(loan_type)
    assert loans[str(first)]["bank_id"] == str(bank)
    assert loans[str(first)]["status"] == "sanctioned"
    assert loans[str(second)]["bank_id"] is None
    assert row["deal_items"] == []
    assert row["txn_count"] == 4
    # Trimmed, de-duplicated, blank names left out, alphabetical.
    assert row["txn_bank_names"] == ["Axis Bank", "HDFC Bank"]
    assert (row["txn_amount_min"], row["txn_amount_max"]) == (
        Decimal("50000.00"),
        Decimal("900000.00"),
    )
    assert (row["txn_first_date"], row["txn_last_date"]) == (date(2026, 1, 15), date(2026, 5, 9))
    # Latest first, one entry per transaction (blank bank names as null).
    assert [(i["txn_date"], i["bank_name"], i["amount"]) for i in row["txn_items"]] == [
        ("2026-05-09", "Axis Bank", 900000.0),
        ("2026-03-01", "HDFC Bank", 250000.5),
        ("2026-02-01", None, 50000.0),
        ("2026-01-15", "HDFC Bank", 100000.0),
    ]


@pytest.mark.asyncio
async def test_lead_without_transactions_has_zero_count(client: AsyncClient) -> None:
    _, tele = await _staff("telecaller")
    lead = await _lead(telecaller=tele)

    row = (
        await _signals_as(
            "lead_list_signals",
            [lead],
            context={"role": "telecaller", "staff_profile_uuid": str(tele)},
        )
    )[lead]

    assert (row["txn_count"], row["txn_bank_names"], row["txn_amount_min"]) == (0, [], None)


@pytest.mark.asyncio
async def test_employee_gets_items_but_no_transactions(client: AsyncClient) -> None:
    _, tele = await _staff("telecaller")
    _, employee = await _staff("employee")
    _, other_employee = await _staff("employee")
    lead = await _lead(telecaller=tele)
    loan_type, bank = await _catalogue()
    application = await _loan(lead, loan_type, bank)
    await _txn(application, "HDFC Bank", "1000.00", date(2026, 1, 1))
    await _task(lead, tele, employee)

    rows = await _signals_as(
        "lead_list_signals",
        [lead],
        context={"role": "employee", "staff_profile_uuid": str(employee)},
    )
    outsider = await _signals_as(
        "lead_list_signals",
        [lead],
        context={"role": "employee", "staff_profile_uuid": str(other_employee)},
    )

    assert [item["loan_type_id"] for item in rows[lead]["loan_items"]] == [str(loan_type)]
    assert rows[lead]["txn_count"] is None
    assert rows[lead]["txn_bank_names"] is None
    assert outsider == {}


@pytest.mark.asyncio
async def test_agent_gets_items_for_own_leads_only_without_codes_calls_or_transactions(
    client: AsyncClient,
) -> None:
    agent_auth, agent = await _agent()
    other_auth, other_agent = await _agent()
    _, tele = await _staff("telecaller")
    mine = await _lead(telecaller=tele, agent=agent)
    theirs = await _lead(telecaller=tele, agent=other_agent)
    loan_type, bank = await _catalogue()
    for lead in (mine, theirs):
        application = await _loan(lead, loan_type, bank)
        await _txn(application, "HDFC Bank", "1000.00", date(2026, 1, 1))

    context = {
        "role": "agent",
        "auth_user_uuid": str(agent_auth),
        "agent_profile_uuid": str(agent),
    }
    rows = await _signals_as("lead_list_signals", [mine, theirs], context=context)
    # Someone else's account presenting this Agent profile gets nothing.
    forged = await _signals_as(
        "lead_list_signals", [mine], context={**context, "auth_user_uuid": str(other_auth)}
    )
    other_line = await _signals_as(
        "lead_list_signals", [mine], context={**context, "business_line": "real_estate"}
    )

    assert set(rows) == {mine}
    row = rows[mine]
    assert [item["bank_id"] for item in row["loan_items"]] == [str(bank)]
    assert row["client_referral_code"] is None
    assert row["last_disposition"] is None
    assert row["txn_count"] is None
    assert forged == {}
    assert other_line == {}


@pytest.mark.asyncio
async def test_real_estate_items_include_inactive_property_category_and_subtype(
    client: AsyncClient,
) -> None:
    _, tele = await _staff("telecaller", "real_estate")
    lead = await _lead("real_estate", telecaller=tele)
    await _deal(lead, category="villas", subtype="villa", status="booked", active=False)
    await _deal(lead, category="plots", subtype=None, status="new")

    rows = await _signals_as(
        "lead_list_signals",
        [lead],
        context={
            "role": "telecaller",
            "staff_profile_uuid": str(tele),
            "business_line": "real_estate",
        },
    )

    deals = sorted(rows[lead]["deal_items"], key=lambda item: item["status"])
    assert [(d["status"], d["category"], d["subtype"]) for d in deals] == [
        ("booked", "villas", "villa"),
        ("new", "plots", None),
    ]
    assert rows[lead]["loan_items"] == []


@pytest.mark.asyncio
async def test_team_signals_give_transactions_only_through_the_telecaller(
    client: AsyncClient,
) -> None:
    _, manager_auth, manager, _ = await _sub_admin(client)
    _, tele = await _staff("telecaller")
    _, employee = await _staff("employee")
    _, outsider_tele = await _staff("telecaller")
    await seed_team(manager, [tele])
    _, employee_manager_auth, employee_manager, _ = await _sub_admin(client)
    await seed_team(employee_manager, [employee], member_role="employee")
    lead = await _lead(telecaller=tele)
    task_lead = await _lead(telecaller=outsider_tele)
    loan_type, bank = await _catalogue()
    for target in (lead, task_lead):
        application = await _loan(target, loan_type, bank)
        await _txn(application, "HDFC Bank", "1000.00", date(2026, 1, 1))
    await _task(task_lead, outsider_tele, employee)

    def manager_context(auth: uuid.UUID, profile: uuid.UUID) -> dict[str, str]:
        return {
            "role": "sub_admin",
            "auth_user_uuid": str(auth),
            "staff_profile_uuid": str(profile),
            "business_line": "",
            "platform_scope": "true",
        }

    telecaller_team = await _signals_as(
        "team_lead_signals", [lead, task_lead], context=manager_context(manager_auth, manager)
    )
    employee_team = await _signals_as(
        "team_lead_signals",
        [lead, task_lead],
        context=manager_context(employee_manager_auth, employee_manager),
    )

    assert set(telecaller_team) == {lead}
    assert telecaller_team[lead]["txn_count"] == 1
    assert [i["bank_id"] for i in telecaller_team[lead]["loan_items"]] == [str(bank)]
    # Reached only through an Employee's task: items, but no transactions.
    assert set(employee_team) == {task_lead}
    assert employee_team[task_lead]["txn_count"] is None
    assert len(employee_team[task_lead]["loan_items"]) == 1


# --- List responses ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_telecaller_list_carries_facets_and_rule_filtered_transactions(
    client: AsyncClient,
) -> None:
    auth, tele = await _staff("telecaller")
    lead = await _lead(telecaller=tele)
    estate_auth, estate_tele = await _staff("telecaller", "real_estate")
    estate_lead = await _lead("real_estate", telecaller=estate_tele)
    await _deal(estate_lead, category="villas", subtype="villa", status="booked")
    loan_type, bank = await _catalogue()
    application = await _loan(lead, loan_type, bank, status="sanctioned", amount=123_456)
    await _txn(application, "HDFC Bank", "2500.00", date(2026, 4, 2))
    headers = _token(auth, "telecaller", staff_profile_uuid=tele)

    listed = await client.get("/api/v1/telecaller/leads", headers=headers)
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json() if item["id"] == str(lead))
    [loan_facet] = row["facets"]["loans"]
    assert row["facets"]["deals"] == []
    assert loan_facet["loan_type_id"] == str(loan_type)
    assert loan_facet["loan_type_label"] == "Facet Loan"
    assert loan_facet["bank_id"] == str(bank)
    assert loan_facet["bank_name"].startswith("Facet Bank ")
    assert loan_facet["status"] == "sanctioned"
    assert set(loan_facet) == {
        "loan_type_id",
        "loan_type_label",
        "bank_id",
        "bank_name",
        "status",
    }
    assert row["transactions"] == {
        "count": 1,
        "bank_names": ["HDFC Bank"],
        "amount_min": 2500.0,
        "amount_max": 2500.0,
        "first_date": "2026-04-02",
        "last_date": "2026-04-02",
        "items": [{"txn_date": "2026-04-02", "bank_name": "HDFC Bank", "amount": 2500.0}],
        "hidden_fields": [],
    }
    # Application amounts never travel with the list facets.
    assert "123456" not in listed.text

    async with (
        _Rule("telecaller", "loan_transaction", "amount"),
        _Rule("telecaller", "loan_transaction", "bank_name"),
    ):
        hidden = await client.get("/api/v1/telecaller/leads", headers=headers)
    row = next(item for item in hidden.json() if item["id"] == str(lead))
    assert row["transactions"]["count"] == 1
    assert row["transactions"]["bank_names"] is None
    assert (row["transactions"]["amount_min"], row["transactions"]["amount_max"]) == (None, None)
    assert row["transactions"]["first_date"] == "2026-04-02"
    assert row["transactions"]["items"] == [
        {"txn_date": "2026-04-02", "bank_name": None, "amount": None}
    ]
    assert set(row["transactions"]["hidden_fields"]) == {"bank_names", "amount"}
    assert "2500" not in hidden.text and "HDFC" not in hidden.text

    detail = await client.get(f"/api/v1/telecaller/leads/{lead}", headers=headers)
    assert detail.json()["transactions"]["count"] == 1

    estate = await client.get(
        "/api/v1/telecaller/leads",
        headers=_token(estate_auth, "telecaller", "real_estate", staff_profile_uuid=estate_tele),
    )
    estate_row = next(item for item in estate.json() if item["id"] == str(estate_lead))
    assert estate_row["transactions"] is None
    assert estate_row["facets"]["deals"] == [
        {"status": "booked", "property_category": "villas", "property_subtype": "villa"}
    ]


@pytest.mark.asyncio
async def test_employee_tasks_carry_lead_facets_without_transactions(client: AsyncClient) -> None:
    _, tele = await _staff("telecaller")
    auth, employee = await _staff("employee")
    lead = await _lead(telecaller=tele)
    loan_type, bank = await _catalogue()
    application = await _loan(lead, loan_type, bank)
    await _txn(application, "HDFC Bank", "2500.00", date(2026, 4, 2))
    task = await _task(lead, tele, employee)

    res = await client.get(
        "/api/v1/employee/tasks", headers=_token(auth, "employee", staff_profile_uuid=employee)
    )

    assert res.status_code == 200, res.text
    row = next(item for item in res.json() if item["id"] == str(task))
    [loan_facet] = row["lead_facets"]["loans"]
    assert (loan_facet["loan_type_id"], loan_facet["bank_id"], loan_facet["status"]) == (
        str(loan_type),
        str(bank),
        "new",
    )
    assert "transactions" not in row and "HDFC" not in res.text


@pytest.mark.asyncio
async def test_team_work_rows_follow_the_telecaller_transaction_rules(
    client: AsyncClient,
) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, tele = await _staff("telecaller")
    team_id = await seed_team(manager, [tele])
    lead = await _lead(telecaller=tele)
    loan_type, bank = await _catalogue()
    application = await _loan(lead, loan_type, bank)
    await _txn(application, "HDFC Bank", "2500.00", date(2026, 4, 2))

    work = await client.get(f"/api/v1/manager/teams/{team_id}/work", headers=_headers(token))
    assert work.status_code == 200, work.text
    signals = next(r for r in work.json()["leads"] if r["id"] == str(lead))["signals"]
    assert signals["facets"]["loans"][0]["bank_id"] == str(bank)
    assert signals["transactions"]["bank_names"] == ["HDFC Bank"]

    async with _Rule("telecaller", "loan_transaction", "txn_date"):
        hidden = await client.get(f"/api/v1/manager/teams/{team_id}/work", headers=_headers(token))
    signals = next(r for r in hidden.json()["leads"] if r["id"] == str(lead))["signals"]
    assert signals["transactions"]["first_date"] is None
    assert signals["transactions"]["hidden_fields"] == ["dates"]


# --- Personal analytics ---------------------------------------------------------------


async def _telecaller_world() -> dict[str, Any]:
    """Three loans leads: A (type T at bank B, sanctioned, 9 L), B (type T at
    another bank, new, 2 L) and C (no application)."""
    auth, tele = await _staff("telecaller")
    loan_type, bank = await _catalogue()
    _, other_bank = await _catalogue()
    a = await _lead(telecaller=tele)
    b = await _lead(telecaller=tele)
    await _lead(telecaller=tele)
    await _loan(a, loan_type, bank, status="sanctioned", amount=900_000)
    await _loan(b, loan_type, other_bank, status="new", amount=200_000)
    return {
        "headers": _token(auth, "telecaller", staff_profile_uuid=tele),
        "loan_type": loan_type,
        "bank": bank,
        "other_bank": other_bank,
    }


@pytest.mark.asyncio
async def test_telecaller_product_bank_status_and_amount_filters_narrow_leads(
    client: AsyncClient,
) -> None:
    world = await _telecaller_world()

    async def active(**params: Any) -> float | None:
        res = await client.get("/api/v1/me/analytics", params=params, headers=world["headers"])
        assert res.status_code == 200, res.text
        return _kpis(res.json())["active_leads"]

    assert await active() == 3
    assert await active(loan_type_id=world["loan_type"]) == 2
    assert await active(bank_id=world["bank"]) == 1
    assert await active(loan_type_id=world["loan_type"], loan_status="new") == 1
    assert await active(amount_min=500000) == 1
    assert await active(amount_max=500000) == 1
    assert await active(amount_min=100000, amount_max=1000000) == 2
    # One application must match every loan filter at once.
    assert await active(bank_id=world["bank"], loan_status="new") == 0
    assert await active(bank_id=world["other_bank"], amount_min=500000) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "line", "params"),
    [
        ("telecaller", "loans", {"property_category": "villas"}),
        ("telecaller", "real_estate", {"loan_type_id": str(uuid.uuid4())}),
        ("telecaller", "loans", {"commission_status": "paid"}),
        ("telecaller", "loans", {"amount_min": "10", "amount_max": "5"}),
        ("employee", "loans", {"amount_min": "10"}),
        ("employee", "loans", {"deal_status": "booked"}),
        ("agent", "loans", {"call_status": "busy"}),
        ("agent", "real_estate", {"bank_id": str(uuid.uuid4())}),
        ("sub_admin", "loans", {"loan_type_id": str(uuid.uuid4())}),
        ("telecaller", "loans", {"amount_min": "-1"}),
    ],
)
async def test_invalid_role_line_filter_pairs_are_422(
    client: AsyncClient, role: str, line: str, params: dict[str, str]
) -> None:
    if role == "agent":
        auth, profile = await _agent(line)
        headers = _token(auth, role, line, agent_profile_uuid=profile)
    elif role == "sub_admin":
        auth, _ = await _staff("telecaller")
        headers = _token(auth, role, line)
    else:
        auth, profile = await _staff(role, line)
        headers = _token(auth, role, line, staff_profile_uuid=profile)

    res = await client.get("/api/v1/me/analytics", params=params, headers=headers)

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_telecaller_amount_filter_is_refused_while_the_admin_hides_amounts(
    client: AsyncClient,
) -> None:
    world = await _telecaller_world()

    async with _Rule("telecaller", "loan_application", "amount_requested"):
        hidden = await client.get(
            "/api/v1/me/analytics", params={"amount_min": 1}, headers=world["headers"]
        )
        product_still_works = await client.get(
            "/api/v1/me/analytics",
            params={"loan_type_id": str(world["loan_type"])},
            headers=world["headers"],
        )

    assert hidden.status_code == 422
    assert "hidden by the Admin" in hidden.json()["detail"]
    assert product_still_works.status_code == 200
    # The page learns which filters to leave out.
    assert product_still_works.json()["hidden_filters"] == ["amount_max", "amount_min"]
    shown = await client.get("/api/v1/me/analytics", headers=world["headers"])
    assert shown.json()["hidden_filters"] == []


@pytest.mark.asyncio
async def test_telecaller_property_filters_and_price_narrow_real_estate_leads(
    client: AsyncClient,
) -> None:
    auth, tele = await _staff("telecaller", "real_estate")
    villa = await _lead("real_estate", telecaller=tele)
    flat = await _lead("real_estate", telecaller=tele)
    await _deal(villa, category="villas", subtype="villa", status="booked", price=20_000_000)
    await _deal(flat, category="apartments", subtype="standalone_apartment", price=5_000_000)
    headers = _token(auth, "telecaller", "real_estate", staff_profile_uuid=tele)

    async def active(**params: Any) -> float | None:
        res = await client.get("/api/v1/me/analytics", params=params, headers=headers)
        assert res.status_code == 200, res.text
        return _kpis(res.json())["active_leads"]

    assert await active(property_category="villas") == 1
    assert await active(property_subtype="standalone_apartment") == 1
    assert await active(deal_status="booked") == 1
    assert await active(deal_status="booked", property_category="apartments") == 0
    assert await active(amount_min=10_000_000) == 1


@pytest.mark.asyncio
async def test_employee_product_filters_narrow_tasks(client: AsyncClient) -> None:
    _, tele = await _staff("telecaller")
    auth, employee = await _staff("employee")
    loan_type, bank = await _catalogue()
    with_loan = await _lead(telecaller=tele)
    without = await _lead(telecaller=tele)
    await _loan(with_loan, loan_type, bank, status="docs_collected")
    await _task(with_loan, tele, employee)
    await _task(without, tele, employee)
    headers = _token(auth, "employee", staff_profile_uuid=employee)

    async def open_tasks(**params: Any) -> float | None:
        res = await client.get("/api/v1/me/analytics", params=params, headers=headers)
        assert res.status_code == 200, res.text
        return _kpis(res.json())["open_tasks"]

    assert await open_tasks() == 2
    assert await open_tasks(loan_type_id=loan_type) == 1
    assert await open_tasks(bank_id=bank, loan_status="docs_collected") == 1
    assert await open_tasks(loan_status="sanctioned") == 0


@pytest.mark.asyncio
async def test_agent_finance_filters_narrow_leads_and_commissions_together(
    client: AsyncClient,
) -> None:
    agent_auth, agent = await _agent()
    loan_type, bank = await _catalogue()
    other_type, _ = await _catalogue()
    home = await _lead(agent=agent, status="converted")
    personal = await _lead(agent=agent, status="working")
    await _lead(agent=agent, status="new")
    home_loan = await _loan(home, loan_type, bank, status="disbursed")
    personal_loan = await _loan(personal, other_type, None, status="new")
    await _commission(agent_auth, agent, home, loan=home_loan, paise=500_000, status="paid")
    await _commission(agent_auth, agent, personal, loan=personal_loan, paise=20_000)
    headers = _token(agent_auth, "agent", agent_profile_uuid=agent)

    async def numbers(**params: Any) -> tuple[Any, ...]:
        res = await client.get("/api/v1/me/analytics", params=params, headers=headers)
        assert res.status_code == 200, res.text
        kpis = _kpis(res.json())
        return kpis["introduced"], kpis["paid"], kpis["pending"]

    assert await numbers() == (3, 5000, 200)
    assert await numbers(loan_type_id=loan_type) == (1, 5000, 0)
    assert await numbers(bank_id=bank, loan_status="disbursed") == (1, 5000, 0)
    assert await numbers(commission_status="pending") == (1, 0, 200)
    assert await numbers(amount_min=1000) == (1, 5000, 0)
    assert await numbers(amount_max=1000) == (1, 0, 200)
    # Lead status now narrows the commission numbers as well.
    assert await numbers(lead_status="working") == (1, 0, 200)
    assert await numbers(lead_status="new") == (1, 0, 0)


# --- Team analytics ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_analytics_accept_the_same_filters_and_lead_source_works(
    client: AsyncClient,
) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, tele = await _staff("telecaller")
    team_id = await seed_team(manager, [tele])
    loan_type, bank = await _catalogue()
    with_loan = await _lead(telecaller=tele)
    referred = await _lead(telecaller=tele)
    await _loan(with_loan, loan_type, bank, amount=900_000)
    await _referral_by_account(referred)

    async def active(**params: Any) -> Any:
        res = await client.get(
            f"/api/v1/manager/teams/{team_id}/overview", params=params, headers=_headers(token)
        )
        assert res.status_code == 200, res.text
        return {kpi["key"]: kpi["value"] for kpi in res.json()["totals"]}["active_leads"]

    assert await active() == 2
    assert await active(loan_type_id=loan_type) == 1
    assert await active(bank_id=bank, amount_min=500000) == 1
    # Before CS-023 the manager path read lead_list_signals, which answers
    # nobody but the lead's own staff, so "client" never matched.
    assert await active(lead_source="client") == 1

    for params in ({"property_category": "villas"}, {"task_type": "property_visit"}):
        refused = await client.get(
            f"/api/v1/manager/teams/{team_id}/overview", params=params, headers=_headers(token)
        )
        assert refused.status_code == 422
        assert "Filter not available" in refused.json()["detail"]

    # The manager follows the Telecaller amount rule, like the member does.
    async with _Rule("telecaller", "loan_application", "amount_requested"):
        hidden = await client.get(
            f"/api/v1/manager/teams/{team_id}/overview", headers=_headers(token)
        )
        refused = await client.get(
            f"/api/v1/manager/teams/{team_id}/overview",
            params={"amount_max": 10},
            headers=_headers(token),
        )
    assert hidden.json()["hidden_filters"] == ["amount_max", "amount_min"]
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_employee_team_analytics_filter_tasks_by_product(client: AsyncClient) -> None:
    token, _, manager, _ = await _sub_admin(client)
    _, tele = await _staff("telecaller")
    _, employee = await _staff("employee")
    team_id = await seed_team(manager, [employee], member_role="employee")
    loan_type, bank = await _catalogue()
    with_loan = await _lead(telecaller=tele)
    await _loan(with_loan, loan_type, bank)
    await _task(with_loan, tele, employee)
    await _task(await _lead(telecaller=tele), tele, employee)

    res = await client.get(
        f"/api/v1/manager/teams/{team_id}/members/{employee}/analytics",
        params={"loan_type_id": str(loan_type)},
        headers=_headers(token),
    )
    amount = await client.get(
        f"/api/v1/manager/teams/{team_id}/overview",
        params={"amount_min": 1},
        headers=_headers(token),
    )

    assert res.status_code == 200, res.text
    assert _kpis(res.json())["open_tasks"] == 1
    assert amount.status_code == 422


# --- Admin reports --------------------------------------------------------------------


async def _report_total(kind: str, day: date, line: str, **filters: Any) -> int:
    import app.db.session as session_mod
    from app.services import reporting

    fn = {
        "leads": reporting.get_leads_report,
        "loans": reporting.get_loans_report,
        "deals": reporting.get_deals_report,
    }[kind]
    async with session_mod.AsyncSessionLocal() as db:
        _rows, _total, summary = await fn(
            db,
            date_from=day,
            date_to=day,
            bucket="week",
            business_line=line,
            limit=500,
            report_filters=reporting.ReportFilters(**filters),
        )
    return summary["total_count"]


async def _backdate(day: date, *lead_ids: uuid.UUID) -> None:
    import app.db.session as session_mod

    stamp = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=6)
    async with session_mod.AsyncSessionLocal() as db:
        for lead_id in lead_ids:
            await db.execute(
                text("UPDATE leads SET created_at = :at WHERE id = :id"),
                {"at": stamp, "id": lead_id},
            )
            await db.execute(
                text("UPDATE loan_applications SET opened_at = :at WHERE lead_uuid = :id"),
                {"at": stamp, "id": lead_id},
            )
            await db.execute(
                text("UPDATE property_deals SET opened_at = :at WHERE lead_uuid = :id"),
                {"at": stamp, "id": lead_id},
            )
        await db.commit()


def _unique_future_day() -> date:
    return date(2091, 1, 1) + timedelta(days=secrets.randbelow(3000))


@pytest.mark.asyncio
async def test_admin_reports_filter_by_subtype_amount_and_lead_products(
    client: AsyncClient,
) -> None:
    day = _unique_future_day()
    loan_type, bank = await _catalogue()
    big = await _lead()
    small = await _lead()
    await _loan(big, loan_type, bank, status="sanctioned", amount=900_000)
    await _loan(small, loan_type, None, status="new", amount=100_000)
    villa = await _lead("real_estate")
    flat = await _lead("real_estate")
    await _deal(villa, category="villas", subtype="villa", price=20_000_000)
    await _deal(flat, category="apartments", subtype="standalone_apartment", price=5_000_000)
    await _backdate(day, big, small, villa, flat)

    assert await _report_total("loans", day, "loans") == 2
    assert await _report_total("loans", day, "loans", amount_min=Decimal(500_000)) == 1
    assert await _report_total("loans", day, "loans", amount_max=Decimal(500_000)) == 1
    assert await _report_total("deals", day, "real_estate", property_subtype="villa") == 1
    assert await _report_total("deals", day, "real_estate", amount_min=Decimal(10_000_000)) == 1
    assert await _report_total("leads", day, "loans", loan_type_id=loan_type) == 2
    assert await _report_total("leads", day, "loans", bank_id=bank, loan_status="new") == 0
    assert await _report_total("leads", day, "loans", bank_id=bank, loan_status="sanctioned") == 1
    assert (
        await _report_total("leads", day, "real_estate", property_subtype="standalone_apartment")
        == 1
    )
    assert await _report_total("leads", day, "loans", amount_min=Decimal(500_000)) == 1


@pytest.mark.asyncio
async def test_admin_client_source_matches_referrals_by_the_leads_account(
    client: AsyncClient,
) -> None:
    day = _unique_future_day()
    referred = await _lead()
    direct = await _lead()
    await _referral_by_account(referred)
    await _backdate(day, referred, direct)

    assert await _report_total("leads", day, "loans", lead_source="client") == 1
    assert await _report_total("leads", day, "loans", lead_source="direct") == 1


@pytest.mark.asyncio
async def test_admin_report_routes_accept_new_filters_and_reject_inverted_amounts(
    client: AsyncClient,
) -> None:
    from app.tests.test_reporting_api import _admin_headers

    headers = await _admin_headers(client)
    base = "/api/v1/admin/reports"
    window = "date_from=2091-01-01&date_to=2091-01-31"

    ok = [
        f"{base}/leads?{window}&loan_type_id={uuid.uuid4()}&property_subtype=villa",
        f"{base}/loans?{window}&amount_min=10&amount_max=20",
        f"{base}/deals?{window}&property_subtype=plot&amount_max=5",
    ]
    for url in ok:
        res = await client.get(url, headers=headers)
        assert res.status_code == 200, (url, res.text)
    inverted = await client.get(
        f"{base}/loans?{window}&amount_min=20&amount_max=10", headers=headers
    )
    assert inverted.status_code == 422
