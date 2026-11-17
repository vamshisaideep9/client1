"""Contest finalization and prizes (CS-027): Admin-only commands after review.

All commands run on the bypass session under a row lock on the contest, with
the platform-Admin check done by the router and the maker-checker rule here:
the Sub Admin who made a contest can never cancel-after-approval, recalculate,
finalize or pay it, even holding an Admin session.

- ``admin_cancel``: an approved, live or ended (not finalized) contest is
  cancelled with a reason; nothing is paid.
- ``recalculate``: re-snapshot an ended contest from live data (late
  corrections, a case rejected after the end date).
- ``finalize``: ended -> finalized. Winners and prizes are decided from the
  snapshot (``contest_scoring.decide_winners``, budget cap included); every
  prize row becomes ``unpaid`` and winners are notified in the same
  transaction.
- ``request_agent_prize_payout``: one ``contest_reward`` payout per Agent
  prize through the existing Payouts maker-checker (``payments.create_payout``
  with ``allow_standalone=False``, so even the Main Admin needs a second
  Admin's approval), within the budget cap; the payout hooks mark it paid.
- ``mark_staff_prize_paid``: a staff prize (Telecaller, Employee, team member
  or managing Sub Admin) is recorded as paid outside Payouts, with a
  PII-free reference and an audit entry. Tax treatment of prizes is pending
  the accountant's confirmation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.models.audit_log import AuditAction
from app.models.contest import (
    Contest,
    ContestPaymentStatus,
    ContestResult,
    ContestResultKind,
    ContestStatus,
)
from app.models.notification import Notification, NotificationType
from app.models.payout import PayoutDestination, PayoutType
from app.services import contest_payouts
from app.services import payments as payments_service
from app.services.audit_log import record as record_audit
from app.services.contest_lifecycle import snapshot
from app.services.contest_scoring import Participant, Standings, decide_winners
from app.services.contests import (
    ContestMakerChecker,
    ContestNotFound,
    ContestStateError,
)

logger = logging.getLogger(__name__)

_ADMIN_CANCELLABLE = (
    ContestStatus.APPROVED.value,
    ContestStatus.LIVE.value,
    ContestStatus.ENDED.value,
)


class ContestPrizeError(ContestStateError):
    """The prize cannot be paid this way or in its current state."""


class ContestBudgetExceeded(ContestStateError):
    """Paying this prize would cross the contest's budget cap."""


async def _locked(session: AsyncSession, contest_id: uuid.UUID, actor_uuid: uuid.UUID) -> Contest:
    contest = await session.scalar(
        select(Contest).where(Contest.id == contest_id).with_for_update()
    )
    if contest is None:
        raise ContestNotFound("Contest not found.")
    if contest.created_by_uuid == actor_uuid:
        raise ContestMakerChecker("You cannot act on a contest you created.")
    return contest


async def _audit(
    session: AsyncSession,
    contest: Contest,
    action: AuditAction,
    actor_uuid: uuid.UUID,
    actor_role: str | None,
    detail: dict,
    entity_uuid: uuid.UUID | None = None,
    entity_type: str = "contest",
) -> None:
    await record_audit(
        session,
        action=action,
        entity_type=entity_type,
        entity_uuid=entity_uuid or contest.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line=contest.business_line,
        detail={"contest_uuid": str(contest.id), **detail},
    )


async def admin_cancel(
    contest_id: uuid.UUID, *, reason: str, actor_uuid: uuid.UUID, actor_role: str | None
) -> Contest:
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id, actor_uuid)
        if contest.status not in _ADMIN_CANCELLABLE:
            raise ContestStateError("Only an approved, live or ended contest can be cancelled.")
        previous = contest.status
        contest.status = ContestStatus.CANCELLED.value
        contest.cancelled_by_uuid = actor_uuid
        contest.cancelled_at = datetime.now(UTC)
        contest.cancel_reason = reason
        contest.version += 1
        await session.flush()
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_CANCELLED,
            actor_uuid,
            actor_role,
            {"status": contest.status, "previous_status": previous},
        )
        await session.commit()
        await session.refresh(contest)
        return contest


async def recalculate(
    contest_id: uuid.UUID, *, actor_uuid: uuid.UUID, actor_role: str | None
) -> Contest:
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id, actor_uuid)
        if contest.status != ContestStatus.ENDED.value:
            raise ContestStateError("Only an ended contest that is not final can be recalculated.")
        standings = await snapshot(session, contest, datetime.now(UTC))
        contest.version += 1
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_RECALCULATED,
            actor_uuid,
            actor_role,
            {
                "status": contest.status,
                "participants": len(standings.ranked),
                "qualified": sum(1 for p in standings.ranked if p.qualified),
            },
        )
        await session.commit()
        await session.refresh(contest)
        return contest


def _participant(row: ContestResult) -> Participant:
    return Participant(
        kind=row.kind,
        user_uuid=row.recipient_user_uuid,
        first_name="",
        last_name="",
        agent_profile_uuid=row.agent_profile_uuid,
        staff_profile_uuid=row.staff_profile_uuid,
        team_uuid=row.team_uuid,
        metric_value=row.metric_value,
        qualified=row.qualified,
        rank=row.rank,
    )


async def finalize(
    contest_id: uuid.UUID, *, actor_uuid: uuid.UUID, actor_role: str | None
) -> Contest:
    """ended -> finalized: decide winners from the snapshot and owe prizes."""
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id, actor_uuid)
        if contest.status != ContestStatus.ENDED.value:
            raise ContestStateError("Only an ended contest can be finalized.")
        rows = list(
            await session.scalars(
                select(ContestResult)
                .where(ContestResult.contest_uuid == contest.id)
                .with_for_update()
            )
        )
        if any(row.won or row.payment_status != ContestPaymentStatus.NONE.value for row in rows):
            raise ContestStateError("This contest already has winners recorded.")
        people = {row.id: _participant(row) for row in rows}
        ranked_kinds = (ContestResultKind.INDIVIDUAL, ContestResultKind.TEAM)
        standings = Standings(
            contest.id,
            datetime.now(UTC),
            [people[row.id] for row in rows if row.kind in ranked_kinds],
            [people[row.id] for row in rows if row.kind not in ranked_kinds],
        )
        decide_winners(contest, standings)

        now = datetime.now(UTC)
        winners: list[ContestResult] = []
        prize_total = 0
        for row in rows:
            person = people[row.id]
            row.won = person.won
            row.prize_paise = person.prize_paise
            row.excluded_reason = person.excluded_reason
            row.payment_status = (
                ContestPaymentStatus.UNPAID.value
                if person.prize_paise > 0
                else ContestPaymentStatus.NONE.value
            )
            if person.prize_paise > 0:
                prize_total += person.prize_paise
            if person.won and row.recipient_user_uuid is not None:
                winners.append(row)
        if contest.budget_cap_paise is not None and prize_total > contest.budget_cap_paise:
            # decide_winners never exceeds the cap; refuse rather than owe more.
            raise ContestBudgetExceeded("The prizes would exceed the budget cap.")

        contest.status = ContestStatus.FINALIZED.value
        contest.finalized_by_uuid = actor_uuid
        contest.finalized_at = now
        contest.version += 1
        await session.flush()
        session.add_all(
            Notification(
                user_uuid=row.recipient_user_uuid,
                type=NotificationType.CONTEST_WON,
                title="You won a contest",
                body=(
                    f"You are a winner of “{contest.title}”."
                    + (f" Prize: ₹{row.prize_paise / 100:,.2f}." if row.prize_paise > 0 else "")
                ),
                href=f"/dashboard/contests?contest={contest.id}",
            )
            for row in winners
        )
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_FINALIZED,
            actor_uuid,
            actor_role,
            {
                "status": contest.status,
                "winners": len(winners),
                "prize_total_paise": prize_total,
                "budget_capped": sum(1 for row in rows if row.excluded_reason == "budget_cap"),
            },
        )
        await session.commit()
        await session.refresh(contest)
        return contest


async def _prize_row(
    session: AsyncSession, contest: Contest, result_id: uuid.UUID
) -> ContestResult:
    row = await session.scalar(
        select(ContestResult)
        .where(ContestResult.id == result_id, ContestResult.contest_uuid == contest.id)
        .with_for_update()
    )
    if row is None:
        raise ContestNotFound("Result not found.")
    if contest.status != ContestStatus.FINALIZED.value:
        raise ContestPrizeError("Prizes are paid only after the winners are confirmed.")
    if not row.won or row.prize_paise <= 0:
        raise ContestPrizeError("This result has no prize.")
    if row.payment_status != ContestPaymentStatus.UNPAID.value or row.payout_uuid is not None:
        raise ContestPrizeError("This prize is already being paid or has been paid.")
    return row


async def request_agent_prize_payout(
    contest_id: uuid.UUID,
    result_id: uuid.UUID,
    *,
    destination_type: PayoutDestination,
    destination: dict,
    actor_uuid: uuid.UUID,
    actor_role: str | None,
) -> uuid.UUID:
    """Create the one contest_reward payout for an Agent prize (maker step).

    Amount, recipient and line come from the result and contest, never the
    request; only the destination is caller-supplied. The payout always
    starts pending approval by a different Admin.
    """
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id, actor_uuid)
        row = await _prize_row(session, contest, result_id)
        if row.agent_profile_uuid is None:
            raise ContestPrizeError("Staff prizes are marked paid, not sent through Payouts.")
        if row.recipient_user_uuid is None:
            raise ContestPrizeError("The winner's account no longer exists.")
        if contest.budget_cap_paise is not None:
            committed = await session.scalar(
                select(func.coalesce(func.sum(ContestResult.prize_paise), 0)).where(
                    ContestResult.contest_uuid == contest.id,
                    ContestResult.payment_status.in_(
                        (
                            ContestPaymentStatus.PAYOUT_PENDING.value,
                            ContestPaymentStatus.PAID.value,
                        )
                    ),
                )
            )
            if (committed or 0) + row.prize_paise > contest.budget_cap_paise:
                raise ContestBudgetExceeded("Paying this prize would exceed the budget cap.")
        recipient, amount, line = row.recipient_user_uuid, row.prize_paise, contest.business_line
        # Release the locks before the payment service opens its own session.
        await session.rollback()

    payout_id = await payments_service.create_payout(
        recipient_user_uuid=recipient,
        payout_type=PayoutType.CONTEST_REWARD,
        business_line=line,
        amount_paise=amount,
        destination_type=destination_type,
        destination=destination,
        idempotency_key=f"ctr-{result_id.hex}",
        maker_user_uuid=actor_uuid,
        actor_role=actor_role,
        allow_standalone=False,
    )
    if not await contest_payouts.attach_payout(result_id=result_id, payout_id=payout_id):
        # The prize was claimed or changed between the check and the claim:
        # reject the orphan payout (not value-moving) instead of leaving it.
        try:
            await payments_service.reject_payout(
                payout_id=payout_id,
                rejector_user_uuid=actor_uuid,
                reason="Contest prize was claimed by another payout concurrently.",
                rejector_role=actor_role,
            )
        except payments_service.PayoutError:
            logger.warning(
                "contest_awards.orphan_payout_reject_failed payout_id=%s result_id=%s",
                payout_id,
                result_id,
            )
        raise ContestPrizeError("This prize is already being paid.")

    async with db_session.AsyncSessionLocal() as session:
        contest = await session.get(Contest, contest_id)
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_PRIZE_PAYOUT_REQUESTED,
            actor_uuid,
            actor_role,
            {"payout_uuid": str(payout_id), "amount_paise": amount},
            entity_uuid=result_id,
            entity_type="contest_result",
        )
        await session.commit()
    return payout_id


async def mark_staff_prize_paid(
    contest_id: uuid.UUID,
    result_id: uuid.UUID,
    *,
    reference: str,
    actor_uuid: uuid.UUID,
    actor_role: str | None,
) -> ContestResult:
    async with db_session.AsyncSessionLocal() as session:
        contest = await _locked(session, contest_id, actor_uuid)
        row = await _prize_row(session, contest, result_id)
        if row.agent_profile_uuid is not None:
            raise ContestPrizeError("Agent prizes are paid through Payouts.")
        if row.recipient_user_uuid == actor_uuid:
            raise ContestMakerChecker("You cannot mark your own prize as paid.")
        now = datetime.now(UTC)
        await session.execute(
            update(ContestResult)
            .where(ContestResult.id == row.id)
            .values(
                payment_status=ContestPaymentStatus.PAID.value,
                paid_marked_by_uuid=actor_uuid,
                paid_marked_at=now,
                paid_reference=reference,
                updated_at=now,
            )
        )
        await _audit(
            session,
            contest,
            AuditAction.CONTEST_PRIZE_MARKED_PAID,
            actor_uuid,
            actor_role,
            {"amount_paise": row.prize_paise, "result_kind": row.kind},
            entity_uuid=row.id,
            entity_type="contest_result",
        )
        await session.commit()
        await session.refresh(row)
        return row
