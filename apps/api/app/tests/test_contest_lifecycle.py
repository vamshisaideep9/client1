"""CS-027 lifecycle: IST boundaries, idempotent go-live and end snapshot."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.db.session as db_session
from app.models.audit_log import AuditAction, AuditLog
from app.models.contest import Contest, ContestResult
from app.models.loan import LoanStatus
from app.models.notification import Notification, NotificationType
from app.scheduler.main import build_scheduler
from app.services.contest_lifecycle import activate_if_due, end_if_due, run_contest_lifecycle
from app.services.contests import today_ist
from app.tests.contest_support import (
    admin_token,
    definition,
    headers,
    seed_agent,
    seed_contest,
    seed_lead,
    seed_loan,
    seed_loan_type,
    seed_user,
    sub_admin_token,
)

pytestmark = pytest.mark.asyncio

IST = ZoneInfo("Asia/Kolkata")


def _ist_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST).astimezone(UTC)


async def _step(contest_id, now: datetime) -> tuple[bool, bool]:
    async with db_session.AsyncSessionLocal() as session:
        contest = await session.scalar(
            select(Contest).where(Contest.id == contest_id).with_for_update()
        )
        went_live = await activate_if_due(session, contest, now)
        ended = await end_if_due(session, contest, now)
        await session.commit()
    return went_live, ended


async def _count(model, *where) -> int:
    async with db_session.AsyncSessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0


async def test_ist_boundaries_and_idempotent_steps(client) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Lifecycle loan")
    agent_user, agent = await seed_agent("loans")
    start_day = today_ist() + timedelta(days=3)
    contest = await seed_contest(
        created_by=maker,
        status="approved",
        starts_on=start_day,
        ends_on=start_day + timedelta(days=1),
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "disbursed",
                "count_at_least": 1,
            },
        },
    )
    start = _ist_midnight(start_day)
    # 18:29:59 UTC the evening before is still the previous IST day.
    assert await _step(contest.id, start - timedelta(seconds=1)) == (False, False)
    assert await _step(contest.id, start) == (True, False)
    assert await _step(contest.id, start + timedelta(minutes=5)) == (False, False)

    notified = await _count(
        Notification,
        Notification.user_uuid == agent_user.id,
        Notification.type == NotificationType.CONTEST_LIVE,
    )
    assert notified == 1

    # A case disbursed inside the window counts in the end snapshot.
    await seed_loan(
        await seed_lead("loans", agent=agent),
        loan_type=loan_type,
        status=LoanStatus.DISBURSED,
        at=start + timedelta(hours=10),
    )
    end = _ist_midnight(start_day + timedelta(days=2))
    assert await _step(contest.id, end - timedelta(seconds=1)) == (False, False)
    assert await _step(contest.id, end) == (False, True)
    assert await _step(contest.id, end + timedelta(minutes=5)) == (False, False)

    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(Contest, contest.id)
        assert stored.status == "ended" and stored.ended_at is not None
        rows = list(
            await db.scalars(select(ContestResult).where(ContestResult.contest_uuid == contest.id))
        )
        actions = list(
            await db.scalars(select(AuditLog.action).where(AuditLog.entity_uuid == contest.id))
        )
    mine = [row for row in rows if row.agent_profile_uuid == agent.id]
    assert len(mine) == 1
    assert (mine[0].achieved_count, mine[0].qualified, mine[0].won) == (1, True, False)
    assert mine[0].payment_status == "none" and mine[0].rank == 1
    assert len({row.agent_profile_uuid for row in rows}) == len(rows)
    assert actions.count(AuditAction.CONTEST_WENT_LIVE) == 1
    assert actions.count(AuditAction.CONTEST_ENDED) == 1


async def test_overdue_contest_goes_live_and_ends_in_one_tick(client) -> None:
    maker = await seed_user("Maker", "Sub")
    contest = await seed_contest(
        created_by=maker,
        status="approved",
        starts_on=today_ist() - timedelta(days=5),
        ends_on=today_ist() - timedelta(days=2),
    )
    summary = await run_contest_lifecycle()
    assert summary["failed"] == 0
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.get(Contest, contest.id)).status == "ended"
    before = await _count(ContestResult, ContestResult.contest_uuid == contest.id)
    await run_contest_lifecycle()
    assert await _count(ContestResult, ContestResult.contest_uuid == contest.id) == before


async def test_approval_on_the_start_day_goes_live_at_once(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    admin, _ = await admin_token()
    today = today_ist()
    response = await client.post(
        "/api/v1/contests",
        json=definition(
            starts_on=today.isoformat(), ends_on=(today + timedelta(days=7)).isoformat()
        ),
        headers=headers(maker),
    )
    contest_id = response.json()["id"]
    assert (
        await client.post(f"/api/v1/contests/{contest_id}/submit", headers=headers(maker))
    ).status_code == 200
    response = await client.post(f"/api/v1/contests/{contest_id}/approve", headers=headers(admin))
    assert response.status_code == 200
    assert response.json()["status"] == "live"
    assert response.json()["live_at"] is not None


def test_job_is_registered_every_five_minutes() -> None:
    job = build_scheduler().get_job("contest_lifecycle")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 5 * 60
    assert job.max_instances == 1 and job.coalesce is True
