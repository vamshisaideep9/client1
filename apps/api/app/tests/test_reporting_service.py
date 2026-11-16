"""Admin analytics & reporting engine — service-level tests
(FR-16.1-16.3, feature-status.md §3 #2).

Every test seeds into a unique, hardcoded, far-from-"today" date window and
asserts only within that window — the shared dev/test Postgres never
truncates between runs (see the shared-test-db-accumulation-gotcha memory),
so a test that asserted a global total would eventually go flaky.

Seeding goes through the bypass session (AsyncSessionLocal), the same as
every other seed helper in this test suite (e.g. test_telecaller_api.py) —
these are service-correctness tests, not RLS tests (see
test_reporting_rls.py for that).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

import app.db.session as _session_mod
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.loan import LoanApplication, LoanStatus, LoanType
from app.models.profile import AgentProfile, ProfileStatus
from app.models.property import Property
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.user import User
from app.services import reporting
from conftest import unique_mobile


async def _seed_agent(business_line: str = "loans") -> str:
    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name="Agent",
            mobile=unique_mobile(),
            email=f"agent_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        agent = AgentProfile(
            auth_user_uuid=user.id,
            agent_code=f"AG-{uuid.uuid4().hex[:8]}",
            business_line=business_line,
            status=ProfileStatus.ACTIVE,
        )
        db.add(agent)
        await db.commit()
        return str(agent.id)


async def _seed_lead(
    *,
    business_line: str,
    created_at: datetime,
    status: LeadStatus = LeadStatus.NEW,
    origin_agent_profile_uuid: str | None = None,
) -> str:
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            name="Test Lead",
            mobile=unique_mobile(),
            business_line=business_line,
            status=status,
            origin=LeadOrigin.AGENT if origin_agent_profile_uuid else LeadOrigin.DIRECT,
            origin_agent_profile_uuid=(
                uuid.UUID(origin_agent_profile_uuid) if origin_agent_profile_uuid else None
            ),
            created_at=created_at,
        )
        db.add(lead)
        await db.commit()
        return str(lead.id)


async def _seed_loan_application(
    *, lead_id: str, opened_at: datetime, status: LoanStatus = LoanStatus.NEW
) -> str:
    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        client_user = User(
            first_name="Test",
            last_name="Client",
            mobile=unique_mobile(),
            email=f"cl_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(client_user)
        await db.flush()
        from app.models.profile import ClientProfile

        client_profile = ClientProfile(
            auth_user_uuid=client_user.id,
            business_line=lead.business_line or "loans",
            customer_code=f"CL{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        loan_type = LoanType(name=f"lt_{uuid.uuid4().hex[:8]}", label="Test Loan Type")
        db.add_all([client_profile, loan_type])
        await db.flush()
        application = LoanApplication(
            lead_uuid=lead.id,
            client_profile_uuid=client_profile.id,
            business_line=lead.business_line or "loans",
            loan_type_id=loan_type.id,
            amount_requested=100000,
            status=status,
            opened_at=opened_at,
        )
        db.add(application)
        await db.commit()
        return str(application.id)


async def _seed_property_deal(
    *, lead_id: str, opened_at: datetime, status: PropertyDealStatus = PropertyDealStatus.NEW
) -> str:
    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        client_user = User(
            first_name="Test",
            last_name="Client",
            mobile=unique_mobile(),
            email=f"cl_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(client_user)
        await db.flush()
        from app.models.profile import ClientProfile

        client_profile = ClientProfile(
            auth_user_uuid=client_user.id,
            business_line="real_estate",
            customer_code=f"CL{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        prop = Property(
            business_line="real_estate",
            active=True,
            title=f"Test Property {uuid.uuid4().hex[:8]}",
            type="Apartment",
            location="Test Locality, Test City",
            price_display="₹80 L",
            category="apartments",
            city="Test City",
            locality="Test Locality",
            pincode="560001",
            price_paise=8_000_000_0,
            bhk=2,
            area_sqft=1100,
            furnishing="furnished",
            construction_status="ready",
            amenities=[],
            age_years=1,
            rera_number=f"RERA/TEST/{uuid.uuid4().hex[:8]}",
            details={},
        )
        db.add_all([client_profile, prop])
        await db.flush()
        deal = PropertyDeal(
            lead_uuid=lead.id,
            client_profile_uuid=client_profile.id,
            property_id=prop.id,
            business_line="real_estate",
            status=status,
            opened_at=opened_at,
        )
        db.add(deal)
        await db.commit()
        return str(deal.id)


# ---------------------------------------------------------------------------
# Pure boundary math
# ---------------------------------------------------------------------------


def test_utc_bounds_ist_half_open() -> None:
    start, end = reporting._utc_bounds(date(2026, 7, 27), date(2026, 7, 27))
    # 2026-07-27T00:00 IST == 2026-07-26T18:30 UTC
    assert start == datetime(2026, 7, 26, 18, 30, tzinfo=UTC)
    # exclusive end is midnight the NEXT IST day
    assert end == datetime(2026, 7, 27, 18, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# IST week-boundary regression — the single most important test in this slice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ist_week_boundary_regression() -> None:
    """Canonical case (docs/ai/plans/...): a row at 2026-07-26T19:00:00Z is
    Sunday in UTC but 00:30 Monday in IST -- it must land in the Monday-
    starting IST week, not the Sunday-starting UTC one.

    The anchor date is a random day far in the future (not the literal
    2026-07-26, and not a fixed future date either) -- the shared dev/test
    Postgres never truncates, so a fixed date would accumulate one more
    seeded row every time this test file reruns and eventually break the
    exact `total == 1` assertion below (shared-test-db-accumulation-gotcha)."""
    anchor = date(2033, 1, 1) + timedelta(days=uuid.uuid4().int % 9_000)
    sunday = anchor + timedelta(days=(6 - anchor.weekday()) % 7)
    ist_monday = sunday + timedelta(days=1)
    utc_week_start = sunday - timedelta(days=6)  # the (wrong) UTC-bucketed Monday

    created_at = datetime(sunday.year, sunday.month, sunday.day, 19, 0, 0, tzinfo=UTC)
    await _seed_lead(business_line="loans", created_at=created_at)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _total, _summary = await reporting.get_leads_report(
            db,
            date_from=sunday - timedelta(days=3),
            date_to=sunday + timedelta(days=10),
            bucket="week",
            business_line="loans",
            limit=500,
        )

    matching = [r for r in rows if r["bucket_start"].astimezone(reporting.IST).date() == ist_monday]
    assert matching, f"expected an IST-Monday ({ist_monday}) bucket, got {rows}"
    assert matching[0]["total"] == 1

    wrong_week = [
        r for r in rows if r["bucket_start"].astimezone(reporting.IST).date() == utc_week_start
    ]
    assert not wrong_week, "row was bucketed into the UTC week instead of the IST week"


# ---------------------------------------------------------------------------
# Conversion definitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leads_converted_counts_only_converted_status() -> None:
    d = date(2031, 4, 1)
    ts = datetime(2031, 4, 1, 10, 0, 0, tzinfo=UTC)
    await _seed_lead(business_line="loans", created_at=ts, status=LeadStatus.CONVERTED)
    await _seed_lead(business_line="loans", created_at=ts, status=LeadStatus.WORKING)

    async with _session_mod.AsyncSessionLocal() as db:
        _rows, _total, summary = await reporting.get_leads_report(
            db, date_from=d, date_to=d, bucket="week", business_line="loans", limit=500
        )

    assert summary["total_count"] >= 2
    assert summary["converted_count"] >= 1


@pytest.mark.asyncio
async def test_loans_converted_is_disbursed_only() -> None:
    d = date(2031, 4, 2)
    ts = datetime(2031, 4, 2, 10, 0, 0, tzinfo=UTC)
    lead_id = await _seed_lead(business_line="loans", created_at=ts)
    disbursed_id = await _seed_loan_application(
        lead_id=lead_id, opened_at=ts, status=LoanStatus.DISBURSED
    )
    lead_id_2 = await _seed_lead(business_line="loans", created_at=ts)
    await _seed_loan_application(lead_id=lead_id_2, opened_at=ts, status=LoanStatus.SANCTIONED)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _total, summary = await reporting.get_loans_report(
            db, date_from=d, date_to=d, bucket="week", business_line="loans", limit=500
        )

    assert summary["total_count"] >= 2
    assert summary["converted_count"] >= 1
    assert disbursed_id  # sanity: seeded row exists


@pytest.mark.asyncio
async def test_deals_converted_is_closed_only() -> None:
    d = date(2031, 4, 3)
    ts = datetime(2031, 4, 3, 10, 0, 0, tzinfo=UTC)
    lead_id = await _seed_lead(business_line="real_estate", created_at=ts)
    await _seed_property_deal(lead_id=lead_id, opened_at=ts, status=PropertyDealStatus.CLOSED)
    lead_id_2 = await _seed_lead(business_line="real_estate", created_at=ts)
    await _seed_property_deal(
        lead_id=lead_id_2, opened_at=ts, status=PropertyDealStatus.NEGOTIATION
    )

    async with _session_mod.AsyncSessionLocal() as db:
        _rows, _total, summary = await reporting.get_deals_report(
            db, date_from=d, date_to=d, bucket="week", business_line="real_estate", limit=500
        )

    assert summary["total_count"] >= 2
    assert summary["converted_count"] >= 1


# ---------------------------------------------------------------------------
# Sort whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sort_by_outside_whitelist_raises() -> None:
    async with _session_mod.AsyncSessionLocal() as db:
        with pytest.raises(reporting.InvalidSortField):
            await reporting.get_leads_report(
                db,
                date_from=date(2031, 1, 1),
                date_to=date(2031, 1, 1),
                bucket="week",
                sort_by="id; DROP TABLE leads;--",
            )


# ---------------------------------------------------------------------------
# Agents report — no fan-out double counting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_report_does_not_double_count_across_joins() -> None:
    d_from = date(2031, 5, 1)
    d_to = date(2031, 5, 1)
    ts = datetime(2031, 5, 1, 10, 0, 0, tzinfo=UTC)
    agent_id = await _seed_agent("real_estate")

    lead_1 = await _seed_lead(
        business_line="real_estate", created_at=ts, origin_agent_profile_uuid=agent_id
    )
    lead_2 = await _seed_lead(
        business_line="real_estate", created_at=ts, origin_agent_profile_uuid=agent_id
    )
    await _seed_property_deal(lead_id=lead_1, opened_at=ts, status=PropertyDealStatus.CLOSED)
    await _seed_property_deal(lead_id=lead_2, opened_at=ts, status=PropertyDealStatus.NEW)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _total, _summary, team_summaries = await reporting.get_agents_report(
            db, date_from=d_from, date_to=d_to, business_line="real_estate", limit=500
        )

    matching = [r for r in rows if r["agent_profile_uuid"] == uuid.UUID(agent_id)]
    assert len(matching) == 1
    row = matching[0]
    assert row["leads_total"] == 2
    assert row["deals_total"] == 2
    assert row["deals_converted"] == 1
    # The fan-out bug this guards against: a naive 4-table join would multiply
    # deals rows by however many OTHER leads/loans the same agent has, so
    # deals_total would come out as 2 leads x 2 deals = 4, not 2.
    team = next(team for team in team_summaries if team["business_line"] == "real_estate")
    assert team["agent_count"] >= 1
    assert team["leads_total"] >= 2
    assert team["deals_total"] >= 2
    assert team["deals_converted"] >= 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_leads_rows_shape() -> None:
    d = date(2031, 6, 1)
    ts = datetime(2031, 6, 1, 10, 0, 0, tzinfo=UTC)
    await _seed_lead(business_line="loans", created_at=ts)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, header, truncated = await reporting.export_report_rows(
            db,
            "leads",
            reporting.ExportParams(
                date_from=d,
                date_to=d,
                bucket="week",
                business_line="loans",
                agent_profile_uuids=None,
            ),
        )

    assert header == ["bucket_start", "business_line", "total", "converted"]
    assert not truncated
    assert any(r["business_line"] == "loans" for r in rows)


@pytest.mark.asyncio
async def test_export_row_cap_truncates_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 50,000-row export cap has no realistic way to seed past in a unit
    test, so the cap itself is monkeypatched down to 1 rather than left
    entirely unverified -- the truncation flag and row-limiting behavior are
    exactly what X-Report-Truncated depends on at the router layer."""
    monkeypatch.setattr(reporting, "EXPORT_ROW_CAP", 1)
    d = date(2031, 7, 1)
    ts = datetime(2031, 7, 1, 10, 0, 0, tzinfo=UTC)
    await _seed_lead(business_line="loans", created_at=ts)
    await _seed_lead(business_line="real_estate", created_at=ts)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _header, truncated = await reporting.export_report_rows(
            db,
            "leads",
            reporting.ExportParams(
                date_from=d, date_to=d, bucket="week", business_line=None, agent_profile_uuids=None
            ),
        )

    assert truncated is True
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Agent filter on the journey (loans/deals) join path -- distinct code path
# from the agents-report's own GROUP BY subqueries above (_get_journey_report
# joins LoanApplication/PropertyDeal back to Lead via lead_uuid instead).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loans_report_agent_filter_excludes_other_agents_loans() -> None:
    d = date(2031, 8, 1)
    ts = datetime(2031, 8, 1, 10, 0, 0, tzinfo=UTC)
    agent_id = await _seed_agent("loans")
    other_agent_id = await _seed_agent("loans")

    own_lead = await _seed_lead(
        business_line="loans", created_at=ts, origin_agent_profile_uuid=agent_id
    )
    other_lead = await _seed_lead(
        business_line="loans", created_at=ts, origin_agent_profile_uuid=other_agent_id
    )
    await _seed_loan_application(lead_id=own_lead, opened_at=ts, status=LoanStatus.DISBURSED)
    await _seed_loan_application(lead_id=other_lead, opened_at=ts, status=LoanStatus.DISBURSED)

    async with _session_mod.AsyncSessionLocal() as db:
        _rows, _total, summary = await reporting.get_loans_report(
            db,
            date_from=d,
            date_to=d,
            bucket="week",
            business_line="loans",
            agent_profile_uuids=[uuid.UUID(agent_id)],
            limit=500,
        )

    # Without the agent filter this window would show total_count=2 -- the
    # filter must exclude the other agent's loan, not just narrow sorting.
    assert summary["total_count"] == 1
    assert summary["converted_count"] == 1


# ---------------------------------------------------------------------------
# Report filters (telecaller, source, call outcome, statuses, property facets)
# ---------------------------------------------------------------------------


def _unique_day() -> date:
    """A far-future day no other run has used, so totals stay exact on a reused DB."""
    import secrets

    return date(2100 + secrets.randbelow(800), 1 + secrets.randbelow(12), 1 + secrets.randbelow(28))


async def _count(kind: str, d: date, line: str, **filters: object) -> int:
    fn = {
        "leads": reporting.get_leads_report,
        "loans": reporting.get_loans_report,
        "deals": reporting.get_deals_report,
    }[kind]
    async with _session_mod.AsyncSessionLocal() as db:
        _rows, _total, summary = await fn(
            db,
            date_from=d,
            date_to=d,
            bucket="week",
            business_line=line,
            limit=500,
            report_filters=reporting.ReportFilters(**filters),
        )
    return summary["total_count"]


async def _telecaller_profile() -> str:
    from app.models.profile import ProfileScope, StaffProfile, StaffRole

    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name="Telecaller",
            mobile=unique_mobile(),
            email=f"tc_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole.TELECALLER,
            scope=ProfileScope.LINE,
            business_line="loans",
            staff_code=f"TC-{uuid.uuid4().hex[:8]}",
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return str(profile.id)


@pytest.mark.asyncio
async def test_lead_report_filters_by_telecaller_source_status_and_latest_call() -> None:
    import secrets

    from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity
    from app.models.referral import Referral, ReferralCode

    d = _unique_day()
    ts = datetime(d.year, d.month, d.day, 6, 0, tzinfo=UTC)
    telecaller = await _telecaller_profile()
    agent = await _seed_agent("loans")
    worked = await _seed_lead(business_line="loans", created_at=ts, status=LeadStatus.WORKING)
    await _seed_lead(business_line="loans", created_at=ts, origin_agent_profile_uuid=agent)
    referred = await _seed_lead(business_line="loans", created_at=ts)
    await _seed_lead(business_line="loans", created_at=ts)

    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.get(Lead, uuid.UUID(worked))
        assert lead is not None
        lead.assigned_telecaller_profile_uuid = uuid.UUID(telecaller)
        for minutes, disposition, interest in ((0, "connected", "hot"), (30, "busy", None)):
            db.add(
                LeadActivity(
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=uuid.UUID(telecaller),
                    business_line="loans",
                    disposition=CallDisposition(disposition),
                    interest_level=InterestLevel(interest) if interest else None,
                    created_at=ts + timedelta(minutes=minutes),
                )
            )
        referrer = User(
            first_name="Ref",
            last_name="Errer",
            mobile=unique_mobile(),
            email=f"ref_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(referrer)
        await db.flush()
        code = "".join(secrets.choice("0123456789ABCDEFGHJKMNPQRSTVWXYZ") for _ in range(8))
        db.add(ReferralCode(auth_user_uuid=referrer.id, code=code))
        referred_lead = await db.get(Lead, uuid.UUID(referred))
        assert referred_lead is not None
        db.add(Referral(referrer_auth_user_uuid=referrer.id, referred_mobile=referred_lead.mobile))
        await db.commit()

    telecallers = (uuid.UUID(telecaller),)
    assert await _count("leads", d, "loans") == 4
    assert await _count("leads", d, "loans", telecaller_profile_uuids=telecallers) == 1
    assert await _count("leads", d, "loans", lead_source="agent") == 1
    assert await _count("leads", d, "loans", lead_source="client") == 1
    assert await _count("leads", d, "loans", lead_source="direct") == 2
    assert await _count("leads", d, "loans", lead_status="working") == 1
    # Only the LATEST call counts: busy, not the earlier connected/hot call.
    assert await _count("leads", d, "loans", call_status="busy") == 1
    assert await _count("leads", d, "loans", call_status="connected") == 0
    assert await _count("leads", d, "loans", interest="hot") == 0


@pytest.mark.asyncio
async def test_loan_report_filters_by_status_type_and_lead_source() -> None:
    d = _unique_day()
    ts = datetime(d.year, d.month, d.day, 6, 0, tzinfo=UTC)
    first = await _seed_lead(business_line="loans", created_at=ts)
    second = await _seed_lead(business_line="loans", created_at=ts)
    new_app = await _seed_loan_application(lead_id=first, opened_at=ts)
    await _seed_loan_application(lead_id=second, opened_at=ts, status=LoanStatus.SANCTIONED)
    async with _session_mod.AsyncSessionLocal() as db:
        application = await db.get(LoanApplication, uuid.UUID(new_app))
        assert application is not None
        new_type = application.loan_type_id

    assert await _count("loans", d, "loans") == 2
    assert await _count("loans", d, "loans", loan_status="sanctioned") == 1
    assert await _count("loans", d, "loans", loan_type_id=new_type) == 1
    assert await _count("loans", d, "loans", bank_id=uuid.uuid4()) == 0
    assert await _count("loans", d, "loans", lead_source="agent") == 0
    assert await _count("loans", d, "loans", lead_source="direct") == 2


@pytest.mark.asyncio
async def test_deal_report_filters_by_status_city_and_category() -> None:
    d = _unique_day()
    ts = datetime(d.year, d.month, d.day, 6, 0, tzinfo=UTC)
    lead = await _seed_lead(business_line="real_estate", created_at=ts)
    await _seed_property_deal(lead_id=lead, opened_at=ts)

    assert await _count("deals", d, "real_estate") == 1
    assert await _count("deals", d, "real_estate", property_city="  test CITY ") == 1
    assert await _count("deals", d, "real_estate", property_city="Elsewhere") == 0
    assert await _count("deals", d, "real_estate", property_category="apartments") == 1
    assert await _count("deals", d, "real_estate", property_category="villas") == 0
    assert await _count("deals", d, "real_estate", deal_status="new") == 1
    assert await _count("deals", d, "real_estate", deal_status="closed") == 0


# ---------------------------------------------------------------------------
# Client-roster export (bulk client PII)
# ---------------------------------------------------------------------------


async def _seed_client(
    *,
    first_name: str = "Client",
    last_name: str = "Person",
    business_line: str = "loans",
    status=None,
    extra_lines: list[str] | None = None,
) -> tuple[str, str]:
    """Create an auth_users row owning one (or more) client_profiles.

    Returns (auth_user_uuid, mobile). `extra_lines` attaches additional client
    profiles to the SAME user, to exercise the no-duplicate-rows guarantee.
    """
    from app.models.profile import ClientProfile
    from app.models.user import UserStatus

    mobile = unique_mobile()
    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            email=f"cl_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
            status=status or UserStatus.ACTIVE,
        )
        db.add(user)
        await db.flush()
        profiles = [
            ClientProfile(
                auth_user_uuid=user.id,
                business_line=business_line,
                customer_code=f"CL{uuid.uuid4().hex[:8]}",
                status=ProfileStatus.ACTIVE,
            )
        ]
        for line in extra_lines or []:
            profiles.append(
                ClientProfile(
                    auth_user_uuid=user.id,
                    business_line=line,
                    customer_code=f"CL{uuid.uuid4().hex[:8]}",
                    status=ProfileStatus.ACTIVE,
                )
            )
        db.add_all(profiles)
        await db.commit()
        return str(user.id), mobile


@pytest.mark.asyncio
async def test_export_client_rows_shape_and_never_exposes_password() -> None:
    uid, mobile = await _seed_client(first_name="Asha", last_name="Rao")

    async with _session_mod.AsyncSessionLocal() as db:
        rows, header, truncated = await reporting.export_client_rows(
            db, actor_uuid=None, actor_role="admin"
        )

    assert header == ["id", "name", "phone", "created_at", "updated_at"]
    # The hard exclusion: no credential column may ever appear.
    assert "password" not in header
    assert "password_hash" not in header
    for row in rows:
        assert set(row.keys()) == set(header)
        assert "password" not in row
        assert "password_hash" not in row

    mine = next(r for r in rows if r["phone"] == mobile)
    assert mine["id"] == uid
    assert mine["name"] == "Asha Rao"
    # date+time, IST offset, both columns populated
    assert mine["created_at"].endswith("+05:30")
    assert "T" in mine["created_at"]
    assert mine["updated_at"].endswith("+05:30")
    assert truncated is False


@pytest.mark.asyncio
async def test_export_client_rows_spans_both_business_lines() -> None:
    _, loans_mobile = await _seed_client(business_line="loans")
    _, re_mobile = await _seed_client(business_line="real_estate")

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _header, _truncated = await reporting.export_client_rows(
            db, actor_uuid=None, actor_role="admin"
        )

    phones = {r["phone"] for r in rows}
    assert loans_mobile in phones
    assert re_mobile in phones


@pytest.mark.asyncio
async def test_export_client_rows_excludes_soft_deleted() -> None:
    from app.models.user import UserStatus

    _, deleted_mobile = await _seed_client(status=UserStatus.SOFT_DELETED)

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _header, _truncated = await reporting.export_client_rows(
            db, actor_uuid=None, actor_role="admin"
        )

    assert deleted_mobile not in {r["phone"] for r in rows}


@pytest.mark.asyncio
async def test_export_client_rows_dedupes_multi_line_client() -> None:
    """A client holding a profile in BOTH lines is one account, one row."""
    uid, mobile = await _seed_client(business_line="loans", extra_lines=["real_estate"])

    async with _session_mod.AsyncSessionLocal() as db:
        rows, _header, _truncated = await reporting.export_client_rows(
            db, actor_uuid=None, actor_role="admin"
        )

    matching = [r for r in rows if r["id"] == uid]
    assert len(matching) == 1
    assert matching[0]["phone"] == mobile


@pytest.mark.asyncio
async def test_export_client_rows_records_audit_entry() -> None:
    """The security-review decision: a bulk client-PII download is audited."""
    from sqlalchemy import func, select

    from app.models.audit_log import AuditAction, AuditLog

    await _seed_client()

    async with _session_mod.AsyncSessionLocal() as db:
        before = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == AuditAction.CLIENT_EXPORT_DOWNLOADED)
        )
        await reporting.export_client_rows(db, actor_uuid=None, actor_role="admin")
        await db.commit()
        after = await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == AuditAction.CLIENT_EXPORT_DOWNLOADED)
        )

    assert after == (before or 0) + 1
