"""CS-027 contest scoring fixtures per audience and line (live standings).

Each test filters its contest to a loan product or city of its own so cases
other tests seed on the same day never reach its standings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import update

import app.db.session as db_session
from app.models.lead import Lead
from app.models.lead_activity import CallDisposition, LeadActivity
from app.models.loan import LoanApplication, LoanStatus
from app.models.profile import AgentProfile, ProfileStatus, StaffRole
from app.models.property import PropertyCategory, PropertySubtype
from app.models.property_deal import PropertyDealStatus
from app.models.task import Task, TaskStatus, TaskType
from app.services.contest_scoring import Participant, compute_standings
from app.services.contests import parse_criteria, today_ist
from app.tests.contest_support import (
    seed_agent,
    seed_contest,
    seed_deal,
    seed_lead,
    seed_loan,
    seed_loan_type,
    seed_property,
    seed_staff,
    seed_team,
    seed_user,
)

pytestmark = pytest.mark.asyncio

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime.now(UTC)
BEFORE = NOW - timedelta(days=40)


async def _standings(contest):
    async with db_session.AsyncSessionLocal() as session:
        return await compute_standings(session, contest, parse_criteria(contest))


def _by(standings, key) -> Participant:
    for person in [*standings.ranked, *standings.team_people]:
        if key in (person.agent_profile_uuid, person.staff_profile_uuid, person.team_uuid):
            return person
    raise AssertionError(f"{key} is not a participant")


async def test_agent_loans_true_amount_filters_and_targets(client) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Personal loan")
    other_type = await seed_loan_type("Gold loan")
    agent_user, agent = await seed_agent("loans", first_name="Asha")
    _, rival = await seed_agent("loans", first_name="Bala")

    for sanctioned in (30_00_000, 25_00_000):
        await seed_loan(
            await seed_lead("loans", agent=agent), loan_type=loan_type, sanctioned=sanctioned
        )
    # Outside the window, another product, and another Agent's lead.
    await seed_loan(await seed_lead("loans", agent=agent), loan_type=loan_type, at=BEFORE)
    await seed_loan(await seed_lead("loans", agent=agent), loan_type=other_type)
    await seed_loan(
        await seed_lead("loans", agent=rival), loan_type=loan_type, sanctioned=10_00_000
    )
    # Sanctioned but not disbursed does not reach the disbursed stage.
    await seed_loan(
        await seed_lead("loans", agent=agent), loan_type=loan_type, status=LoanStatus.SANCTIONED
    )

    contest = await seed_contest(
        created_by=maker,
        metric="amount",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "disbursed",
                "count_at_least": 1,
                "count_at_most": 5,
                "amount_at_least_paise": 50_00_000_00,
            },
        },
    )
    standings = await _standings(contest)
    mine = _by(standings, agent.id)
    assert (mine.tally.count, mine.tally.amount_paise) == (2, 55_00_000_00)
    assert mine.qualified and mine.metric_value == 55_00_000_00
    assert mine.progress == {"count": 2, "amount_paise": 55_00_000_00}
    assert mine.rank == 1
    assert _by(standings, rival.id).tally.count == 1
    assert not _by(standings, rival.id).qualified

    # True amount is read live: a lowered sanction drops the total below target.
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(LoanApplication)
            .where(
                LoanApplication.amount_sanctioned == Decimal(30_00_000),
                LoanApplication.loan_type_id == loan_type.id,
            )
            .values(amount_sanctioned=Decimal(20_00_000))
        )
        await db.commit()
    mine = _by(await _standings(contest), agent.id)
    assert mine.tally.amount_paise == 45_00_000_00
    assert not mine.qualified


async def test_sanctioned_stage_excludes_rejected_and_bounds_per_case(client) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Home loan")
    _, agent = await seed_agent("loans")
    await seed_loan(
        await seed_lead("loans", agent=agent),
        loan_type=loan_type,
        status=LoanStatus.SANCTIONED,
        sanctioned=40_00_000,
    )
    await seed_loan(
        await seed_lead("loans", agent=agent),
        loan_type=loan_type,
        status=LoanStatus.SANCTIONED,
        sanctioned=2_00_000,
    )
    rejected = await seed_loan(
        await seed_lead("loans", agent=agent),
        loan_type=loan_type,
        status=LoanStatus.SANCTIONED,
        sanctioned=50_00_000,
    )
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(LoanApplication)
            .where(LoanApplication.id == rejected.id)
            .values(status=LoanStatus.REJECTED)
        )
        await db.commit()
    contest = await seed_contest(
        created_by=maker,
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "case_amount_min_paise": 5_00_000_00,
                "count_at_least": 1,
            },
        },
    )
    mine = _by(await _standings(contest), agent.id)
    assert (mine.tally.count, mine.tally.amount_paise) == (1, 40_00_000_00)


async def test_agent_real_estate_deals_by_category_city_and_stage(client) -> None:
    maker = await seed_user("Maker", "Sub")
    city = f"Contest City {uuid.uuid4().hex[:6]}"
    _, agent = await seed_agent("real_estate")
    apartment = await seed_property(city=city)
    villa = await seed_property(
        city=city, category=PropertyCategory.VILLAS, subtype=PropertySubtype.VILLA
    )
    elsewhere = await seed_property(city="Elsewhere")
    await seed_deal(await seed_lead("real_estate", agent=agent), apartment, price_quoted=80_00_000)
    await seed_deal(await seed_lead("real_estate", agent=agent), villa, price_quoted=2_00_00_000)
    await seed_deal(await seed_lead("real_estate", agent=agent), elsewhere)
    # Booked without a quote counts at the listing price for the booked stage.
    await seed_deal(
        await seed_lead("real_estate", agent=agent),
        apartment,
        status=PropertyDealStatus.BOOKED,
        price_quoted=None,
    )

    closed = await seed_contest(
        created_by=maker,
        business_line="real_estate",
        metric="amount",
        criteria={
            "version": 1,
            "real_estate": {
                "counted_stage": "closed",
                "property_categories": ["apartments"],
                "cities": [city.upper()],
                "count_at_least": 1,
            },
        },
    )
    mine = _by(await _standings(closed), agent.id)
    assert (mine.tally.count, mine.tally.amount_paise) == (1, 80_00_000_00)

    booked = await seed_contest(
        created_by=maker,
        business_line="real_estate",
        metric="amount",
        criteria={
            "version": 1,
            "real_estate": {"counted_stage": "booked", "cities": [city], "count_at_least": 1},
        },
    )
    mine = _by(await _standings(booked), agent.id)
    # Two closed deals passed booking too, plus the unquoted booking.
    assert mine.tally.count == 3
    assert mine.tally.amount_paise == 80_00_000_00 + 2_00_00_000_00 + 75_00_000_00


async def test_eligibility_tenure_kyc_and_line(client) -> None:
    maker = await seed_user("Maker", "Sub")
    _, veteran = await seed_agent("loans", created_at=NOW - timedelta(days=200))
    _, newcomer = await seed_agent("loans", created_at=NOW - timedelta(days=5))
    _, unverified = await seed_agent("loans", kyc_status=None, created_at=NOW - timedelta(days=200))
    _, other_line = await seed_agent("real_estate", created_at=NOW - timedelta(days=200))
    _, inactive = await seed_agent("loans", created_at=NOW - timedelta(days=200))
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(AgentProfile)
            .where(AgentProfile.id == inactive.id)
            .values(status=ProfileStatus.SUSPENDED)
        )
        await db.commit()
    contest = await seed_contest(
        created_by=maker,
        criteria={
            "version": 1,
            "loans": {"counted_stage": "disbursed", "count_at_least": 1},
            "eligibility": {"min_tenure_days": 90, "kyc_verified": True},
        },
    )
    keys = {p.agent_profile_uuid for p in (await _standings(contest)).ranked}
    assert veteran.id in keys
    assert not keys & {newcomer.id, unverified.id, other_line.id, inactive.id}


async def _call(
    telecaller, lead: Lead, *, at: datetime, connected: bool = True, follow_up_at=None
) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(
            LeadActivity(
                lead_uuid=lead.id,
                telecaller_staff_profile_uuid=telecaller.id,
                business_line=lead.business_line,
                disposition=CallDisposition.CONNECTED if connected else CallDisposition.NO_ANSWER,
                follow_up_at=follow_up_at,
                created_at=at,
            )
        )
        await db.commit()


async def test_telecaller_business_follows_current_assignee_and_activity(client) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Business loan")
    _, first = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    _, second = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    held = await seed_lead("loans", telecaller=first)
    moved = await seed_lead("loans", telecaller=first)
    for lead in (held, moved):
        await seed_loan(lead, loan_type=loan_type, status=LoanStatus.SANCTIONED)
    # Reassigned: only the current holder gets credit.
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(Lead)
            .where(Lead.id == moved.id)
            .values(assigned_telecaller_profile_uuid=second.id)
        )
        await db.commit()

    # Anchored on yesterday's IST noon so no call straddles an IST midnight.
    noon = datetime.combine(today_ist() - timedelta(days=1), time(12), tzinfo=IST)
    await _call(first, held, at=noon, follow_up_at=noon + timedelta(hours=2))
    await _call(first, held, at=noon + timedelta(hours=3), connected=False)  # kept
    await _call(first, held, at=noon + timedelta(hours=4))
    await _call(first, moved, at=noon, connected=False, follow_up_at=noon + timedelta(hours=1))

    contest = await seed_contest(
        created_by=maker,
        audience="telecaller",
        metric="calls_logged",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "count_at_least": 1,
            },
            "activity": {
                "calls_logged_at_least": 4,
                "connect_rate_at_least_percent": 50,
                "connect_rate_min_calls": 4,
                "follow_ups_on_time_at_least": 1,
            },
        },
    )
    standings = await _standings(contest)
    one, two = _by(standings, first.id), _by(standings, second.id)
    assert one.tally.count == 1 and two.tally.count == 1
    assert (one.tally.calls, one.tally.connected) == (4, 2)
    assert one.tally.follow_ups_on_time == 1
    assert one.progress["connect_rate_percent"] == 50
    assert one.qualified and one.metric_value == 4
    assert not two.qualified


async def test_employee_tasks_and_site_visits(client) -> None:
    maker = await seed_user("Maker", "Sub")
    _, employee = await seed_staff(StaffRole.EMPLOYEE, business_line="real_estate")
    raiser_user, raiser = await seed_staff(StaffRole.TELECALLER, business_line="real_estate")
    lead = await seed_lead("real_estate", telecaller=raiser)
    async with db_session.AsyncSessionLocal() as db:
        for task_type, due in (
            (TaskType.PROPERTY_VISIT, NOW + timedelta(hours=5)),
            (TaskType.DOCUMENT_COLLECTION, NOW - timedelta(hours=5)),
            (TaskType.BACKGROUND_CHECK, None),
        ):
            db.add(
                Task(
                    assigned_employee_profile_uuid=employee.id,
                    raised_by_staff_profile_uuid=raiser.id,
                    business_line="real_estate",
                    task_type=task_type,
                    lead_uuid=lead.id,
                    status=TaskStatus.COMPLETED,
                    due_at=due,
                    updated_at=NOW - timedelta(hours=1),
                )
            )
        db.add(
            Task(
                assigned_employee_profile_uuid=employee.id,
                raised_by_staff_profile_uuid=raiser.id,
                business_line="real_estate",
                task_type=TaskType.PROPERTY_VISIT,
                lead_uuid=lead.id,
                status=TaskStatus.IN_PROGRESS,
            )
        )
        await db.commit()
    prop = await seed_property(city=f"Task City {uuid.uuid4().hex[:6]}")
    await seed_deal(lead, prop, status=PropertyDealStatus.BOOKED, price_quoted=60_00_000)

    contest = await seed_contest(
        created_by=maker,
        business_line="real_estate",
        audience="employee",
        metric="tasks_completed",
        criteria={
            "version": 1,
            "real_estate": {"counted_stage": "booked", "cities": [prop.city]},
            "activity": {
                "tasks_completed_at_least": 3,
                "tasks_on_time_at_least": 1,
                "site_visits_completed_at_least": 1,
            },
        },
    )
    mine = _by(await _standings(contest), employee.id)
    assert (mine.tally.tasks_completed, mine.tally.tasks_on_time) == (3, 1)
    assert mine.tally.site_visits_completed == 1
    assert mine.tally.count == 1  # the booked deal on a lead they hold a task for
    assert mine.qualified and mine.metric_value == 3


async def test_team_sums_current_members_and_counts_shared_cases_once(client) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Team loan")
    _, manager = await seed_staff(StaffRole.SUB_ADMIN)
    _, ravi = await seed_staff(StaffRole.TELECALLER, business_line="loans", first_name="Ravi")
    _, sam = await seed_staff(StaffRole.TELECALLER, business_line="loans", first_name="Sam")
    _, outsider = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    team = await seed_team(manager, "loans", "telecaller", [ravi, sam])
    for person in (ravi, ravi, sam, outsider):
        lead = await seed_lead("loans", telecaller=person)
        await seed_loan(lead, loan_type=loan_type, status=LoanStatus.SANCTIONED)
        await _call(person, lead, at=NOW - timedelta(hours=2))

    contest = await seed_contest(
        created_by=maker,
        audience="team",
        team_member_role="telecaller",
        metric="cases",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "count_at_least": 3,
            },
        },
        prize_paise=None,
        manager_prize_paise=5_000_00,
        member_prize_paise=1_000_00,
        member_min_contribution=2,
    )
    standings = await _standings(contest)
    team_row = _by(standings, team.id)
    assert team_row.kind == "team" and team_row.tally.count == 3 and team_row.qualified
    members = {p.staff_profile_uuid: p for p in standings.team_people if p.team_uuid == team.id}
    assert members[ravi.id].metric_value == 2 and members[sam.id].metric_value == 1
    assert members[manager.id].kind == "team_manager"
    assert outsider.id not in members
