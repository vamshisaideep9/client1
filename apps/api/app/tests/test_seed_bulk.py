"""Bulk development dataset (app.scripts.bulk_catalog / app.scripts.seed_bulk)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models.lead import Lead, LeadStatus
from app.models.loan import LoanApplication, LoanStatus
from app.models.payout import Payout, PayoutStatus
from app.models.profile import ProfileStatus, StaffProfile
from app.models.property import Property, PropertySubtype, ReraApplicability
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.property_submission import PropertySubmission, SubmissionStatus
from app.models.referral import Referral, ReferralStatus
from app.models.task import Task, TaskStatus
from app.models.user import User, UserStatus
from app.schemas.property_submissions import SubmissionFacts
from app.scripts import bulk_catalog as catalog
from app.scripts import demo_catalog, seed_dev_roster
from app.scripts.demo_media import document_pdf
from app.services.storage import sniff_content_type
from conftest import unique_email


def test_roster_has_the_requested_shape_and_unique_identities() -> None:
    staff = Counter((a.role, a.business_line) for a in catalog.staff_accounts())
    assert staff == {
        ("admin", None): 2,
        ("sub_admin", None): 9,
        ("telecaller", "loans"): 8,
        ("telecaller", "real_estate"): 7,
        ("employee", "loans"): 8,
        ("employee", "real_estate"): 7,
        ("agent", "loans"): 8,
        ("agent", "real_estate"): 7,
    }
    clients = catalog.client_accounts()
    lines = Counter(line for client in clients for line in client.client_lines)
    assert len(clients) == 195
    assert lines["loans"] >= 100 and lines["real_estate"] >= 100
    assert sum(len(c.client_lines) == 2 for c in clients) == 25

    accounts = catalog.all_accounts()
    for attribute in ("key", "mobile", "email", "code"):
        values = [getattr(a, attribute) for a in accounts]
        assert len(set(values)) == len(values), attribute
    assert all(a.mobile.startswith(catalog.MOBILE_PREFIX) and len(a.mobile) == 13 for a in accounts)
    assert all(a.email.endswith("@example.com") for a in accounts)
    assert all(a.rera_code for a in catalog.accounts_by_role("agent", "real_estate"))


def test_bulk_identities_never_overlap_other_seeders() -> None:
    bulk = {a.mobile for a in catalog.all_accounts()}
    bulk |= {p.mobile for p in catalog.prospects()}
    bulk |= {p.mobile for p in catalog.agent_application_plans()}
    others = {a.mobile for a in demo_catalog.DEMO_ACCOUNTS} | {
        a.mobile for a in seed_dev_roster.ROSTER
    }
    assert not bulk & others
    assert catalog.bulk_uuid("user:admin-01") != demo_catalog.demo_uuid("user:admin")


def test_teams_have_sub_admin_managers_and_line_role_members() -> None:
    by_key = {a.key: a for a in catalog.staff_accounts()}
    managers = [team.manager_key for team in catalog.TEAMS]
    assert len(catalog.TEAMS) == 5 and len(set(managers)) == 5
    assert all(by_key[key].role == "sub_admin" for key in managers)
    seen: set[tuple[str, str]] = set()
    for team in catalog.TEAMS:
        for member in team.member_keys:
            account = by_key[member]
            assert account.role == team.member_role
            assert account.business_line == team.business_line
            assert (member, team.business_line) not in seen  # one team per line
            seen.add((member, team.business_line))
    unassigned = [
        a.key
        for a in catalog.staff_accounts()
        if a.role in {"telecaller", "employee"}
        and all(a.key not in t.member_keys for t in catalog.TEAMS)
    ]
    assert unassigned  # the "not in any team" state stays testable
    assert sum(a.payout_grant for a in catalog.staff_accounts()) == 2


def test_every_listing_passes_real_submission_validation_and_covers_the_catalogue() -> None:
    facts = [
        SubmissionFacts.model_validate(catalog.listing_facts(index))
        for index in range(catalog.LISTING_COUNT + catalog.SUBMISSION_COUNT)
    ]
    catalogue = facts[: catalog.LISTING_COUNT]
    assert len(catalogue) > 100
    assert {f.property_subtype for f in catalogue} == set(PropertySubtype)
    assert {f.listing_intent.value for f in catalogue} == {"sale", "rent"}
    rentals = {f.property_subtype for f in catalogue if f.listing_intent.value == "rent"}
    assert rentals == catalog.RENTABLE
    assert {f.rera_applicability for f in catalogue} == set(ReraApplicability)
    assert {f.construction_status for f in catalogue} >= {"ready", "under_construction"}


def test_approved_submissions_mirror_a_rera_cleared_listing() -> None:
    plans = catalog.submission_plans()
    assert {p.status for p in plans} == {"pending", "approved", "rejected"}
    for plan in plans:
        if plan.status == "approved":
            assert plan.approved_listing == plan.index
            facts = catalog.listing_facts(plan.index)
            assert facts["rera_applicability"] == ReraApplicability.APPLICABLE
        else:
            assert plan.approved_listing is None and plan.index >= catalog.LISTING_COUNT


def test_every_catalogue_listing_has_exactly_one_approved_origin() -> None:
    planned = [
        p.approved_listing for p in catalog.submission_plans() if p.approved_listing is not None
    ]
    origins = list(catalog.listing_origin_indices())
    assert sorted(planned + origins) == list(range(catalog.LISTING_COUNT))
    by_key = {a.key: a for a in catalog.staff_accounts()}
    for index in origins:
        author = by_key[catalog.listing_origin_author(index)]
        assert author.role in {"admin", "sub_admin"} or (
            author.role == "agent"
            and author.business_line == "real_estate"
            and author.profile_status == ProfileStatus.ACTIVE
        )


def test_client_journeys_cover_every_pipeline_and_account_state() -> None:
    journeys = catalog.client_journeys()
    loans = [j for j in journeys if j.line == "loans"]
    estate = [j for j in journeys if j.line == "real_estate"]
    assert len(loans) == len(estate) == 110

    active_loans = {j.current_loan_status for j in loans if j.current_loan_status}
    assert active_loans == set(LoanStatus) - {LoanStatus.CLOSED, LoanStatus.REJECTED}
    assert any(j.closed_loan for j in loans) and any(j.rejected_loan for j in loans)
    assert {j.deal_status for j in estate if j.deal_status} == set(PropertyDealStatus)

    lead_states = {j.lead_status for j in journeys} | {p.status for p in catalog.prospects()}
    assert lead_states >= set(LeadStatus)
    assert sum(j.lead_status is None for j in journeys) == 2 * catalog.EMPTY_PROFILES_PER_LINE
    assert {j.profile_status for j in journeys} == set(ProfileStatus)
    assert {c.user_status for c in catalog.client_accounts()} >= {
        UserStatus.ACTIVE,
        UserStatus.SUSPENDED,
        UserStatus.PENDING_PASSWORD_RESET,
    }
    assert any(p.agent_expired for p in catalog.prospects())

    # A mobile may hold only one live Agent-protected lead across both lines.
    protected = Counter(
        catalog.account(j.account_key).mobile
        for j in journeys
        if j.agent_key and j.lead_status not in {None, LeadStatus.CLOSED}
    )
    assert max(protected.values()) == 1
    # Leads only route to active staff of the same line.
    by_key = {a.key: a for a in catalog.staff_accounts()}
    for journey in journeys:
        for key in (journey.agent_key, journey.telecaller_key):
            if key:
                assert by_key[key].business_line == journey.line
                assert by_key[key].profile_status == ProfileStatus.ACTIVE


def test_document_pdf_is_a_real_pdf() -> None:
    content = document_pdf(title="Salary Slip", lines=("Synthetic",))
    assert sniff_content_type(content[:32]) == "application/pdf"
    assert b"/Type /Page" in content or b"/Type/Page" in content


def test_writer_refuses_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.scripts.seed_helpers import require_development

    monkeypatch.setattr(settings, "ENV", "staging")
    with pytest.raises(SystemExit, match="development-only"):
        require_development("seed_bulk")


@pytest.mark.asyncio
async def test_every_phase_writes_valid_rows_in_one_transaction() -> None:
    """Run all row phases against the real schema, constraints and triggers.

    seed_bulk() commits per phase; this drives the same phase functions in
    one session and rolls everything back so the shared test database is
    left untouched.
    """
    from app.db.session import AsyncSessionLocal
    from app.scripts import seed_bulk as seeder

    ctx = seeder.Ctx(now=datetime.now(UTC))
    async with AsyncSessionLocal() as db:
        try:
            await seeder._seed_users(db, ctx)
            await seeder._seed_profiles(db, ctx)
            await seeder._seed_teams(db, ctx)
            await seeder._seed_referral_codes(db, ctx)
            await seeder._seed_properties(db, ctx)
            await seeder._seed_leads(db, ctx)
            await seeder._seed_loans(db, ctx)
            await seeder._seed_real_estate(db, ctx)
            await seeder._seed_tasks(db, ctx)
            await seeder._seed_money(db, ctx)
            await seeder._seed_support_and_notifications(db, ctx)
            await seeder._seed_coverage(db, ctx)
            await db.flush()

            bulk_users = [user.id for user in ctx.users.values()]
            assert len(bulk_users) == len(catalog.all_accounts())
            admins = await db.scalars(
                select(StaffProfile).where(StaffProfile.id.in_([p.id for p in ctx.staff.values()]))
            )
            assert not any(profile.is_primary_admin for profile in admins)

            properties = [p.id for p in ctx.properties]
            assert (
                await db.scalar(
                    select(func.count()).select_from(Property).where(Property.id.in_(properties))
                )
                == 110
            )
            # The Admin "Published" view joins approved submissions to listings.
            assert (
                await db.scalar(
                    select(
                        func.count(func.distinct(PropertySubmission.approved_property_id))
                    ).where(
                        PropertySubmission.status == SubmissionStatus.APPROVED,
                        PropertySubmission.approved_property_id.in_(properties),
                    )
                )
                == 110
            )

            leads = [lead.id for lead in ctx.leads.values()]
            lead_states = set(
                (await db.scalars(select(Lead.status).where(Lead.id.in_(leads)))).all()
            )
            assert lead_states == set(LeadStatus)

            profiles = [p.id for p in ctx.clients.values()]
            loan_states = set(
                (
                    await db.scalars(
                        select(LoanApplication.status).where(
                            LoanApplication.client_profile_uuid.in_(profiles)
                        )
                    )
                ).all()
            )
            assert loan_states == set(LoanStatus)
            deal_states = set(
                (
                    await db.scalars(
                        select(PropertyDeal.status).where(
                            PropertyDeal.client_profile_uuid.in_(profiles)
                        )
                    )
                ).all()
            )
            assert deal_states == set(PropertyDealStatus)

            task_states = set(
                (
                    await db.scalars(
                        select(Task.status).where(Task.id.in_([t.id for t in ctx.tasks]))
                    )
                ).all()
            )
            assert task_states == set(TaskStatus)

            payout_states = set(
                (
                    await db.scalars(
                        select(Payout.status).where(Payout.recipient_user_uuid.in_(bulk_users))
                    )
                ).all()
            )
            assert payout_states == set(PayoutStatus)
            referral_states = set(
                (
                    await db.scalars(
                        select(Referral.conversion_status).where(
                            Referral.referrer_auth_user_uuid.in_(bulk_users)
                        )
                    )
                ).all()
            )
            assert referral_states == set(ReferralStatus)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_seed_refuses_a_foreign_account_on_a_bulk_mobile() -> None:
    from app.db.session import AsyncSessionLocal
    from app.scripts import seed_bulk as seeder

    first = catalog.all_accounts()[0]
    async with AsyncSessionLocal() as db:
        try:
            existing = await db.scalar(select(User).where(User.mobile == first.mobile))
            if existing is not None:
                pytest.skip("This database already holds the bulk dataset.")
            db.add(
                User(
                    first_name="Someone",
                    last_name="Else",
                    mobile=first.mobile,
                    email=unique_email(),
                    password_hash="unused",
                    status=UserStatus.ACTIVE,
                )
            )
            await db.flush()
            with pytest.raises(seeder.BulkSeedConflict, match="belongs to another account"):
                await seeder._seed_users(db, seeder.Ctx(now=datetime.now(UTC)))
        finally:
            await db.rollback()


def _staff_keys(role: str, line: str | None = None) -> list[str]:
    return [
        a.key
        for a in catalog.accounts_by_role(role, line)
        if a.profile_status == ProfileStatus.ACTIVE
    ]


def _lead_signal_values(lead: catalog.CoverageLead) -> dict[str, set[str]]:
    loan_statuses: set[str] = set()
    if lead.current_loan_status is not None:
        loan_statuses.add(lead.current_loan_status.value)
    if lead.closed_loan:
        loan_statuses.add("closed")
    if lead.rejected_loan:
        loan_statuses.add("rejected")
    return {
        "lead_status": {lead.lead_status.value},
        "call": {lead.disposition or "not_called"},
        "interest": {lead.interest} if lead.interest else set(),
        "source": {"agent" if lead.agent_key else "client" if lead.client_referral else "direct"},
        "loan_status": loan_statuses,
    }


def _assert_min(counts: Counter, values, who: str, dimension: str) -> None:
    for value in values:
        assert counts[value] >= catalog.COVERAGE_MIN, (who, dimension, value, counts[value])


def test_every_telecaller_sees_five_of_every_filter_value() -> None:
    for line in ("loans", "real_estate"):
        for telecaller in _staff_keys("telecaller", line):
            mine = [lead for lead in catalog.coverage_leads() if lead.telecaller_key == telecaller]
            dims: dict[str, Counter] = {}
            for lead in mine:
                for dimension, values in _lead_signal_values(lead).items():
                    dims.setdefault(dimension, Counter()).update(values)
            _assert_min(dims["lead_status"], catalog.TELECALLER_STATUSES, telecaller, "status")
            _assert_min(dims["call"], ("not_called", *catalog.DISPOSITIONS), telecaller, "call")
            _assert_min(dims["interest"], catalog.INTERESTS, telecaller, "interest")
            _assert_min(dims["source"], ("direct", "agent", "client"), telecaller, "source")
            if line == "loans":
                _assert_min(dims["loan_status"], [s.value for s in LoanStatus], telecaller, "loan")


def test_every_employee_sees_five_of_every_filter_value() -> None:
    for line in ("loans", "real_estate"):
        for employee in _staff_keys("employee", line):
            mine = [
                lead
                for lead in catalog.coverage_leads()
                if lead.task is not None and lead.task.employee_key == employee
            ]
            statuses = Counter(lead.task.status for lead in mine)
            types = Counter(lead.task.task_type for lead in mine)
            _assert_min(statuses, catalog.EMPLOYEE_TASK_STATUSES, employee, "task status")
            _assert_min(types, catalog.TASK_TYPES_BY_LINE[line], employee, "task type")
            dims: dict[str, Counter] = {}
            for lead in mine:
                for dimension, values in _lead_signal_values(lead).items():
                    dims.setdefault(dimension, Counter()).update(values)
            _assert_min(dims["call"], ("not_called", *catalog.DISPOSITIONS), employee, "call")
            _assert_min(dims["interest"], catalog.INTERESTS, employee, "interest")
            _assert_min(dims["source"], ("direct", "agent", "client"), employee, "source")
            if line == "loans":
                _assert_min(dims["loan_status"], [s.value for s in LoanStatus], employee, "loan")
            else:
                pickups = Counter(
                    lead.arrangement.status
                    for lead in catalog.coverage_leads()
                    if lead.arrangement is not None and lead.arrangement.employee_key == employee
                )
                _assert_min(pickups, ("assigned", "completed", "cancelled"), employee, "pickup")


def test_every_agent_sees_five_of_every_status() -> None:
    for line in ("loans", "real_estate"):
        for agent in _staff_keys("agent", line):
            mine = [lead for lead in catalog.coverage_leads() if lead.agent_key == agent]
            statuses = Counter(
                "expired" if lead.agent_expired else lead.lead_status.value for lead in mine
            )
            _assert_min(statuses, (*catalog.TELECALLER_STATUSES, "expired"), agent, "lead")
            commissions = Counter(lead.commission_status for lead in mine if lead.commission_status)
            _assert_min(commissions, catalog.COMMISSION_CYCLE, agent, "commission")
            if line == "real_estate":
                listings = Counter(
                    p.status for p in catalog.agent_listing_plans() if p.submitter_key == agent
                )
                listings["approved"] += sum(
                    1
                    for index in catalog.listing_origin_indices()
                    if catalog.listing_origin_author(index) == agent
                )
                _assert_min(listings, ("pending", "approved", "rejected"), agent, "listing")


def test_coverage_identities_are_unique_and_valid() -> None:
    accounts = catalog.all_accounts()
    for attribute in ("key", "mobile", "email", "code"):
        values = [getattr(a, attribute) for a in accounts]
        assert len(set(values)) == len(values), attribute
    leads = catalog.coverage_leads()
    assert len({lead.key for lead in leads}) == len(leads)
    for lead in leads:
        if lead.telecaller_key:
            assert catalog.account(lead.telecaller_key).business_line == lead.line
        if lead.task and lead.task.employee_key:
            assert catalog.account(lead.task.employee_key).business_line == lead.line
        if lead.commission_status:
            assert lead.current_loan_status == LoanStatus.DISBURSED or lead.deal_status in {
                PropertyDealStatus.BOOKED,
                PropertyDealStatus.AGREEMENT_SIGNED,
                PropertyDealStatus.CLOSED,
            }
    for plan in catalog.agent_listing_plans():
        SubmissionFacts.model_validate(catalog.listing_facts(plan.index))
