"""Contest lifecycle (CS-027): approved -> live -> ended, with the end snapshot.

Runs on the bypass session (``import app.db.session as db_session``, resolved
at call time so tests get the NullPool engine), like ``jobs/cms_activation``.
Each contest moves in its own transaction under a row lock, and each step
re-checks the status it overwrites, so the job is idempotent and safe to
rerun or to overlap with an approval: a second run finds nothing to do.

- ``activate_if_due``: an approved contest whose IST start has arrived goes
  live; every participant gets a "contest is live" notification in the same
  transaction (all or nothing with the status change).
- ``end_if_due``: a live contest whose IST end has passed is scored one last
  time and its standings are written to ``contest_results``; it becomes
  ``ended`` and waits for the Admin to confirm winners.
- ``snapshot`` is shared with the Admin's recalculation of an ended contest.

An approved contest whose dates have both passed (the scheduler was down)
goes live and ends in the same tick.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.models.audit_log import AuditAction
from app.models.contest import (
    Contest,
    ContestPaymentStatus,
    ContestResult,
    ContestStatus,
)
from app.models.notification import Notification, NotificationType
from app.services.audit_log import record as record_audit
from app.services.contest_scoring import (
    ContestWindow,
    Participant,
    Standings,
    compute_standings,
)
from app.services.contests import parse_criteria, today_ist

logger = logging.getLogger("scheduler")


def _contest_href(contest: Contest) -> str:
    return f"/dashboard/contests?contest={contest.id}"


def _recipients(standings: Standings) -> set[uuid.UUID]:
    people = [*standings.ranked, *standings.team_people]
    return {person.user_uuid for person in people if person.user_uuid is not None}


async def activate_if_due(session: AsyncSession, contest: Contest, now: datetime) -> bool:
    """approved -> live once the IST start has arrived. Caller holds the row
    lock and commits."""
    if contest.status != ContestStatus.APPROVED.value or now < ContestWindow.of(contest).start:
        return False
    contest.status = ContestStatus.LIVE.value
    contest.live_at = now
    contest.version += 1
    await session.flush()
    standings = await compute_standings(session, contest, parse_criteria(contest), now)
    recipients = _recipients(standings)
    session.add_all(
        Notification(
            user_uuid=user_uuid,
            type=NotificationType.CONTEST_LIVE,
            title="A new contest is live",
            body=(
                f"“{contest.title}” runs until "
                f"{contest.ends_on.strftime('%d %b %Y')}. See the rules and your progress."
            ),
            href=_contest_href(contest),
        )
        for user_uuid in recipients
    )
    await record_audit(
        session,
        action=AuditAction.CONTEST_WENT_LIVE,
        entity_type="contest",
        entity_uuid=contest.id,
        actor_uuid=None,
        actor_role=None,
        business_line=contest.business_line,
        detail={"status": contest.status, "notified": len(recipients)},
    )
    return True


def _result_row(contest: Contest, person: Participant) -> ContestResult:
    return ContestResult(
        contest_uuid=contest.id,
        business_line=contest.business_line,
        kind=person.kind,
        agent_profile_uuid=person.agent_profile_uuid,
        staff_profile_uuid=person.staff_profile_uuid,
        team_uuid=person.team_uuid,
        recipient_user_uuid=person.user_uuid,
        achieved_count=person.tally.count,
        achieved_amount_paise=person.tally.amount_paise,
        metric_value=person.metric_value,
        progress=person.progress,
        qualified=person.qualified,
        rank=person.rank,
        won=False,
        prize_paise=0,
        payment_status=ContestPaymentStatus.NONE.value,
    )


async def snapshot(session: AsyncSession, contest: Contest, now: datetime) -> Standings:
    """Replace the contest's result rows with freshly computed standings.

    Only for a contest that has ended and is not finalized: no row can carry
    a prize or payment yet, so replacing them loses nothing.
    """
    standings = await compute_standings(session, contest, parse_criteria(contest), now)
    await session.execute(delete(ContestResult).where(ContestResult.contest_uuid == contest.id))
    session.add_all(_result_row(contest, person) for person in standings.ranked)
    session.add_all(_result_row(contest, person) for person in standings.team_people)
    await session.flush()
    return standings


async def end_if_due(session: AsyncSession, contest: Contest, now: datetime) -> bool:
    """live -> ended after the IST end, writing the end snapshot."""
    if contest.status != ContestStatus.LIVE.value or now < ContestWindow.of(contest).end:
        return False
    standings = await snapshot(session, contest, now)
    contest.status = ContestStatus.ENDED.value
    contest.ended_at = now
    contest.version += 1
    qualified = sum(1 for person in standings.ranked if person.qualified)
    await record_audit(
        session,
        action=AuditAction.CONTEST_ENDED,
        entity_type="contest",
        entity_uuid=contest.id,
        actor_uuid=None,
        actor_role=None,
        business_line=contest.business_line,
        detail={
            "status": contest.status,
            "participants": len(standings.ranked),
            "qualified": qualified,
        },
    )
    return True


async def run_contest_lifecycle(now: datetime | None = None) -> dict[str, int]:
    """One scheduler tick. Returns counts for the job log."""
    now = now or datetime.now(UTC)
    async with db_session.AsyncSessionLocal() as session:
        due = list(
            await session.scalars(
                select(Contest.id).where(
                    Contest.status.in_((ContestStatus.APPROVED.value, ContestStatus.LIVE.value)),
                    Contest.starts_on <= today_ist(now),
                )
            )
        )
    activated = ended = failed = 0
    for contest_id in due:
        try:
            async with db_session.AsyncSessionLocal() as session:
                contest = await session.scalar(
                    select(Contest)
                    .where(Contest.id == contest_id)
                    .with_for_update(skip_locked=True)
                )
                if contest is None:
                    continue
                went_live = await activate_if_due(session, contest, now)
                did_end = await end_if_due(session, contest, now)
                await session.commit()
            activated += int(went_live)
            ended += int(did_end)
        except Exception:
            failed += 1
            logger.exception("job.contest_lifecycle.contest_failed contest_id=%s", contest_id)
    return {"scanned": len(due), "activated": activated, "ended": ended, "failed": failed}
