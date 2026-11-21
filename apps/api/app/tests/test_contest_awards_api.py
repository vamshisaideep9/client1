"""CS-027 finalization and prizes: winners, Agent payouts, staff mark-paid.

Runs in mock payment mode (no RAZORPAY_* credentials): approving a payout
settles it locally and emits the Agent's ledger row, which drives the
contest result to paid through the payout hooks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

import app.db.session as db_session
from app.models.audit_log import AuditAction, AuditLog
from app.models.contest import Contest, ContestResult
from app.models.loan import LoanStatus
from app.models.notification import Notification, NotificationType
from app.models.payout import Payout, PayoutStatus, PayoutType
from app.models.profile import StaffRole
from app.models.transaction import Transaction, TransactionType
from app.services import payout_links
from app.services.contest_lifecycle import end_if_due
from app.services.contests import today_ist
from app.services.retention_purge import purge_delinked_financial_records
from app.tests.contest_support import (
    admin_token,
    headers,
    seed_agent,
    seed_call,
    seed_contest,
    seed_lead,
    seed_loan,
    seed_loan_type,
    seed_staff,
    seed_team,
    sub_admin_token,
    token_for,
)

pytestmark = pytest.mark.asyncio

_VPA = {"destination_type": "vpa", "destination": {"vpa": "winner@okhdfc"}}


async def _ended_contest(maker_user, loan_type, **fields) -> Contest:
    """A contest over the last ten IST days that has just been ended."""
    contest = await seed_contest(
        created_by=maker_user,
        status="live",
        starts_on=today_ist() - timedelta(days=10),
        ends_on=today_ist() - timedelta(days=1),
        **fields,
    )
    async with db_session.AsyncSessionLocal() as session:
        locked = await session.get(Contest, contest.id, with_for_update=True)
        assert await end_if_due(session, locked, datetime.now(UTC))
        await session.commit()
    return contest


def _loan_criteria(loan_type, **extra) -> dict:
    return {
        "version": 1,
        "loans": {
            "loan_type_ids": [str(loan_type.id)],
            "counted_stage": "disbursed",
            **extra,
        },
    }


async def _results(contest_id) -> list[ContestResult]:
    async with db_session.AsyncSessionLocal() as db:
        return list(
            await db.scalars(select(ContestResult).where(ContestResult.contest_uuid == contest_id))
        )


def _inside_window() -> datetime:
    """Noon IST two days ago: inside every ended test contest's window."""
    day = today_ist() - timedelta(days=2)
    return datetime.combine(day, time(12), tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC)


async def _seed_cases(agent, loan_type, count: int) -> None:
    for _ in range(count):
        await seed_loan(
            await seed_lead("loans", agent=agent), loan_type=loan_type, at=_inside_window()
        )


async def test_agent_item_prize_is_snapshotted_and_awarded_without_payout(client) -> None:
    _, maker, _ = await sub_admin_token()
    admin, _ = await admin_token()
    _, agent = await seed_agent()
    loan_type = await seed_loan_type("Item award loan")
    await _seed_cases(agent, loan_type, 1)
    item = {
        "label": "Headphones",
        "details": "Collect from the office",
        "estimated_value_paise": 400000,
    }
    contest = await _ended_contest(
        maker,
        loan_type,
        criteria=_loan_criteria(loan_type, count_at_least=1),
        prize_kind="item",
        prize_paise=None,
        item_prize=item,
    )
    snapshot = next(r for r in await _results(contest.id) if r.agent_profile_uuid == agent.id)
    assert snapshot.item_prize == item and snapshot.payment_status == "none"
    url = f"/api/v1/contests/{contest.id}"
    response = await client.post(f"{url}/finalize", headers=headers(admin))
    assert response.status_code == 200, response.text
    row = next(r for r in await _results(contest.id) if r.id == snapshot.id)
    assert row.won and row.prize_paise == 0 and row.payment_status == "unpaid"
    response = await client.get(f"{url}/standings", headers=headers(admin))
    assert response.json()["winners"] == 1
    assert response.json()["prize_total_paise"] == 0
    assert (
        await client.post(f"{url}/results/{row.id}/payout", json=_VPA, headers=headers(admin))
    ).status_code == 409
    for expected in (200, 409):
        response = await client.post(
            f"{url}/results/{row.id}/mark-paid",
            json={"reference": "Office collection"},
            headers=headers(admin),
        )
        assert response.status_code == expected, response.text
    awarded = next(r for r in await _results(contest.id) if r.id == row.id)
    assert awarded.payment_status == "paid" and awarded.paid_reference == "Office collection"
    assert awarded.payout_uuid is None and awarded.payout_txn_uuid is None


async def test_finalize_top_n_with_tie_and_maker_checker(client: AsyncClient) -> None:
    maker_token, maker_user, maker_profile = await sub_admin_token()
    admin, _ = await admin_token()
    loan_type = await seed_loan_type("Award loan")
    agents = [await seed_agent("loans", first_name=name) for name in ("Ana", "Ben", "Cy", "Dev")]
    for (_, agent), cases in zip(agents, (4, 3, 3, 1), strict=True):
        await _seed_cases(agent, loan_type, cases)
    contest = await _ended_contest(
        maker_user,
        loan_type,
        criteria=_loan_criteria(loan_type, count_at_least=1),
        win_mode="top_n",
        top_n=2,
        prize_paise=1_000_00,
    )

    # The maker, even with an Admin session, cannot finalize; a Sub Admin neither.
    maker_as_admin = token_for(
        maker_user, "admin", platform_scope="true", staff_profile=maker_profile
    )
    for token, code in ((maker_as_admin, 403), (maker_token, 403)):
        response = await client.post(
            f"/api/v1/contests/{contest.id}/finalize", headers=headers(token)
        )
        assert response.status_code == code

    response = await client.post(
        f"/api/v1/contests/{contest.id}/recalculate", headers=headers(admin)
    )
    assert response.status_code == 200
    response = await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "finalized"

    rows = {row.agent_profile_uuid: row for row in await _results(contest.id)}
    winners = {agent.id for _, agent in agents if rows[agent.id].won}
    assert winners == {agents[0][1].id, agents[1][1].id, agents[2][1].id}  # tie at 2nd kept
    assert all(
        rows[a].prize_paise == 1_000_00 and rows[a].payment_status == "unpaid" for a in winners
    )
    assert rows[agents[3][1].id].payment_status == "none"

    async with db_session.AsyncSessionLocal() as db:
        won_notes = await db.scalars(
            select(Notification.user_uuid).where(
                Notification.type == NotificationType.CONTEST_WON,
                Notification.href == f"/dashboard/contests?contest={contest.id}",
            )
        )
        assert set(won_notes) == {agents[i][0].id for i in range(3)}

    # Finalized is terminal for these commands.
    for path in ("finalize", "recalculate"):
        response = await client.post(
            f"/api/v1/contests/{contest.id}/{path}", headers=headers(admin)
        )
        assert response.status_code == 409
    response = await client.post(
        f"/api/v1/contests/{contest.id}/cancel", json={"reason": "Too late"}, headers=headers(admin)
    )
    assert response.status_code == 409


async def test_agent_prize_payout_is_idempotent_and_needs_a_second_admin(
    client: AsyncClient,
) -> None:
    _, maker_user, _ = await sub_admin_token()
    admin, admin_user = await admin_token()
    checker, _ = await admin_token()
    loan_type = await seed_loan_type("Payout loan")
    agent_user, agent = await seed_agent("loans", first_name="Gita")
    await _seed_cases(agent, loan_type, 2)
    contest = await _ended_contest(
        maker_user,
        loan_type,
        criteria=_loan_criteria(loan_type, count_at_least=2),
        prize_paise=2_500_00,
    )
    assert (
        await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    ).status_code == 200
    row = next(r for r in await _results(contest.id) if r.agent_profile_uuid == agent.id)

    # Staff-only command refused for an Agent prize.
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{row.id}/mark-paid",
        json={"reference": "Payroll"},
        headers=headers(admin),
    )
    assert response.status_code == 409

    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{row.id}/payout", json=_VPA, headers=headers(admin)
    )
    assert response.status_code == 201, response.text
    payout_id = uuid.UUID(response.json()["payout_id"])
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{row.id}/payout", json=_VPA, headers=headers(admin)
    )
    assert response.status_code == 409

    async with db_session.AsyncSessionLocal() as db:
        payout = await db.get(Payout, payout_id)
        assert payout.type == PayoutType.CONTEST_REWARD
        assert payout.status == PayoutStatus.PENDING_APPROVAL
        assert payout.amount_paise == 2_500_00
        assert payout.recipient_user_uuid == agent_user.id
        assert payout.idempotency_key == f"ctr-{row.id.hex}"
        assert payout.maker_user_uuid == admin_user.id
        stored = await db.get(ContestResult, row.id)
        assert (stored.payment_status, stored.payout_uuid) == ("payout_pending", payout_id)

    # The maker cannot approve; a second Admin approves and the mock settles.
    response = await client.post(f"/api/v1/payouts/{payout_id}/approve", headers=headers(admin))
    assert response.status_code == 403
    response = await client.post(f"/api/v1/payouts/{payout_id}/approve", headers=headers(checker))
    assert response.status_code == 200, response.text
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(ContestResult, row.id)
        assert stored.payment_status == "paid" and stored.payout_txn_uuid is not None
        txn = await db.get(Transaction, stored.payout_txn_uuid)
        assert txn.type == TransactionType.CONTEST_REWARD and txn.user_uuid == agent_user.id
        actions = set(
            await db.scalars(select(AuditLog.action).where(AuditLog.entity_uuid == row.id))
        )
        assert AuditAction.CONTEST_PRIZE_PAYOUT_REQUESTED in actions


async def test_retention_purge_is_not_blocked_by_a_paid_contest_prize(
    client: AsyncClient,
) -> None:
    """Security review: the 7-year purge of a de-linked contest_reward payout
    and its ledger row must succeed; the result keeps its paid prize."""
    _, maker_user, _ = await sub_admin_token()
    admin, _ = await admin_token()
    checker, _ = await admin_token()
    loan_type = await seed_loan_type("Purge loan")
    _, agent = await seed_agent("loans")
    await _seed_cases(agent, loan_type, 1)
    contest = await _ended_contest(
        maker_user, loan_type, criteria=_loan_criteria(loan_type, count_at_least=1)
    )
    assert (
        await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    ).status_code == 200
    row = next(r for r in await _results(contest.id) if r.agent_profile_uuid == agent.id)
    payout_id = (
        await client.post(
            f"/api/v1/contests/{contest.id}/results/{row.id}/payout",
            json=_VPA,
            headers=headers(admin),
        )
    ).json()["payout_id"]
    assert (
        await client.post(f"/api/v1/payouts/{payout_id}/approve", headers=headers(checker))
    ).status_code == 200
    async with db_session.AsyncSessionLocal() as db:
        paid = await db.get(ContestResult, row.id)
        assert paid.payment_status == "paid" and paid.payout_txn_uuid is not None
        long_ago = datetime.now(UTC) - timedelta(days=365 * 8)
        await db.execute(
            update(Payout).where(Payout.id == uuid.UUID(payout_id)).values(delinked_at=long_ago)
        )
        await db.execute(
            update(Transaction)
            .where(Transaction.id == paid.payout_txn_uuid)
            .values(delinked_at=long_ago)
        )
        await db.commit()

    summary = await purge_delinked_financial_records()
    assert summary["payouts_purged"] >= 1 and summary["transactions_purged"] >= 1

    async with db_session.AsyncSessionLocal() as db:
        kept = await db.get(ContestResult, row.id)
        assert (kept.payout_uuid, kept.payout_txn_uuid) == (None, None)
        assert (kept.payment_status, kept.prize_paise) == ("paid", 1_000_00)


async def test_rejected_payout_frees_the_prize_and_generic_create_is_refused(
    client: AsyncClient,
) -> None:
    _, maker_user, _ = await sub_admin_token()
    admin, _ = await admin_token()
    loan_type = await seed_loan_type("Reject loan")
    agent_user, agent = await seed_agent("loans")
    await _seed_cases(agent, loan_type, 1)
    contest = await _ended_contest(
        maker_user, loan_type, criteria=_loan_criteria(loan_type, count_at_least=1)
    )
    await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    row = next(r for r in await _results(contest.id) if r.agent_profile_uuid == agent.id)
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{row.id}/payout", json=_VPA, headers=headers(admin)
    )
    payout_id = response.json()["payout_id"]
    response = await client.post(
        f"/api/v1/payouts/{payout_id}/reject", json={"reason": "Wrong VPA"}, headers=headers(admin)
    )
    assert response.status_code == 200
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(ContestResult, row.id)
        assert (stored.payment_status, stored.payout_uuid) == ("unpaid", None)
    # Idempotent repair sweep finds nothing left to do.
    await payout_links.reconcile_payout_links()

    response = await client.post(
        "/api/v1/payouts",
        json={
            "recipient_user_uuid": str(agent_user.id),
            "type": "contest_reward",
            "business_line": "loans",
            "amount_paise": 1_000_00,
            "idempotency_key": uuid.uuid4().hex,
            **_VPA,
        },
        headers=headers(admin),
    )
    assert response.status_code == 422


async def test_budget_cap_and_staff_mark_paid_with_audit(client: AsyncClient) -> None:
    _, maker_user, _ = await sub_admin_token()
    admin, admin_user = await admin_token()
    manager_user, manager = await seed_staff(StaffRole.SUB_ADMIN, first_name="Mira")
    _, ravi = await seed_staff(StaffRole.TELECALLER, business_line="loans", first_name="Ravi")
    _, sam = await seed_staff(StaffRole.TELECALLER, business_line="loans", first_name="Sam")
    team = await seed_team(manager, "loans", "telecaller", [ravi, sam])
    loan_type = await seed_loan_type("Team award loan")
    for person in (ravi, ravi, sam):
        lead = await seed_lead("loans", telecaller=person)
        # Telecaller credit needs a call before the counted stage.
        await seed_call(person, lead, at=_inside_window() - timedelta(hours=1))
        await seed_loan(
            lead,
            loan_type=loan_type,
            status=LoanStatus.SANCTIONED,
            at=_inside_window(),
        )
    contest = await _ended_contest(
        maker_user,
        loan_type,
        audience="team",
        team_member_role="telecaller",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "count_at_least": 3,
            },
        },
        prize_paise=None,
        manager_prize_paise=3_000_00,
        member_prize_paise=1_000_00,
        member_min_contribution=2,
        budget_cap_paise=4_000_00,
    )
    response = await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    assert response.status_code == 200, response.text
    rows = {
        (r.kind, r.staff_profile_uuid): r
        for r in await _results(contest.id)
        if r.team_uuid == team.id
    }
    manager_row = rows[("team_manager", manager.id)]
    ravi_row, sam_row = rows[("team_member", ravi.id)], rows[("team_member", sam.id)]
    assert (manager_row.prize_paise, ravi_row.prize_paise, sam_row.prize_paise) == (
        3_000_00,
        1_000_00,
        0,
    )
    assert sam_row.excluded_reason == "below_member_minimum"

    # Staff prizes are marked paid (never through Payouts), by someone else.
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{ravi_row.id}/payout",
        json=_VPA,
        headers=headers(admin),
    )
    assert response.status_code == 409
    manager_as_admin = token_for(
        manager_user, "admin", platform_scope="true", staff_profile=manager
    )
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{manager_row.id}/mark-paid",
        json={"reference": "Payroll November"},
        headers=headers(manager_as_admin),
    )
    assert response.status_code == 403
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{manager_row.id}/mark-paid",
        json={"reference": "NEFT to account 123456789012"},
        headers=headers(admin),
    )
    assert response.status_code == 422  # no account / phone numbers in the record
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{manager_row.id}/mark-paid",
        json={"reference": "Payroll November"},
        headers=headers(admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["payment_status"] == "paid"
    response = await client.post(
        f"/api/v1/contests/{contest.id}/results/{manager_row.id}/mark-paid",
        json={"reference": "Again"},
        headers=headers(admin),
    )
    assert response.status_code == 409
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(ContestResult, manager_row.id)
        assert stored.paid_marked_by_uuid == admin_user.id and stored.paid_reference
        audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.entity_uuid == manager_row.id,
                AuditLog.action == AuditAction.CONTEST_PRIZE_MARKED_PAID,
            )
        )
        assert audit is not None and audit.actor_uuid == admin_user.id


async def test_budget_cap_leaves_out_a_crossing_group(client: AsyncClient) -> None:
    _, maker_user, _ = await sub_admin_token()
    admin, _ = await admin_token()
    loan_type = await seed_loan_type("Capped loan")
    agents = [await seed_agent("loans") for _ in range(3)]
    for (_, agent), cases in zip(agents, (3, 2, 2), strict=True):
        await _seed_cases(agent, loan_type, cases)
    contest = await _ended_contest(
        maker_user,
        loan_type,
        criteria=_loan_criteria(loan_type, count_at_least=1),
        prize_paise=1_000_00,
        budget_cap_paise=2_000_00,
    )
    assert (
        await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    ).status_code == 200
    rows = {r.agent_profile_uuid: r for r in await _results(contest.id)}
    assert rows[agents[0][1].id].won is True
    for _, agent in agents[1:]:
        assert (rows[agent.id].won, rows[agent.id].excluded_reason) == (False, "budget_cap")


async def test_admin_cancel_of_a_live_contest(client: AsyncClient) -> None:
    maker_token, maker_user, _ = await sub_admin_token()
    admin, _ = await admin_token()
    contest = await seed_contest(created_by=maker_user, status="live")
    response = await client.post(
        f"/api/v1/contests/{contest.id}/cancel",
        json={"reason": "Rules were wrong"},
        headers=headers(maker_token),
    )
    assert response.status_code == 409  # the maker cannot cancel after approval
    response = await client.post(
        f"/api/v1/contests/{contest.id}/cancel",
        json={"reason": "Rules were wrong"},
        headers=headers(admin),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    response = await client.post(f"/api/v1/contests/{contest.id}/finalize", headers=headers(admin))
    assert response.status_code == 409
