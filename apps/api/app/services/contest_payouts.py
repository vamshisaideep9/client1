"""Contest prize payment links (CS-027): one ``contest_reward`` payout per
Agent result, mirroring ``services/commissions.py``'s payout functions.

``attach_payout`` claims an unpaid Agent prize for a freshly created payout
with a compare-and-swap (``payment_status = 'unpaid' AND payout_uuid IS
NULL``), so two concurrent "Pay prize" commands can only ever have one
winner; the deterministic idempotency key ``ctr-<result id>`` makes
``payments.create_payout``'s dedupe guard and partial-unique index reject
the second payout before it exists. ``mark_paid_from_payout`` and
``release_payout_link`` are the paid / terminal-dead hooks dispatched by
``services/payout_links.py`` and re-driven by its reconciliation sweep.

All three run on the bypass session (module-qualified ``db_session``) because
the payment settle paths that call the hooks have no request identity, and
api_user has no write grant on ``contest_results``. The hooks are
best-effort and never raise into a settlement.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, update

import app.db.session as db_session
from app.models.contest import ContestPaymentStatus, ContestResult

logger = logging.getLogger(__name__)


async def attach_payout(*, result_id: uuid.UUID, payout_id: uuid.UUID) -> bool:
    async with db_session.AsyncSessionLocal() as session:
        claimed = await session.scalar(
            update(ContestResult)
            .where(
                ContestResult.id == result_id,
                ContestResult.agent_profile_uuid.is_not(None),
                ContestResult.won.is_(True),
                ContestResult.payment_status == ContestPaymentStatus.UNPAID.value,
                ContestResult.payout_uuid.is_(None),
            )
            .values(
                payout_uuid=payout_id,
                payment_status=ContestPaymentStatus.PAYOUT_PENDING.value,
                updated_at=func.now(),
            )
            .returning(ContestResult.id)
        )
        await session.commit()
        return claimed is not None


async def mark_paid_from_payout(*, payout_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
    """A CONTEST_REWARD payout settled: its result becomes paid. The status
    predicate makes a redelivered settle a no-op."""
    try:
        async with db_session.AsyncSessionLocal() as session:
            await session.execute(
                update(ContestResult)
                .where(
                    ContestResult.payout_uuid == payout_id,
                    ContestResult.payment_status == ContestPaymentStatus.PAYOUT_PENDING.value,
                )
                .values(
                    payment_status=ContestPaymentStatus.PAID.value,
                    payout_txn_uuid=transaction_id,
                    updated_at=func.now(),
                )
            )
            await session.commit()
    except Exception:
        logger.warning("contest_payouts.mark_paid_failed payout_id=%s", payout_id, exc_info=True)


async def release_payout_link(*, payout_id: uuid.UUID) -> None:
    """A CONTEST_REWARD payout was rejected, failed or reversed: the prize is
    owed again (unpaid, links cleared) so the Admin can pay it once more."""
    try:
        async with db_session.AsyncSessionLocal() as session:
            await session.execute(
                update(ContestResult)
                .where(ContestResult.payout_uuid == payout_id)
                .values(
                    payment_status=ContestPaymentStatus.UNPAID.value,
                    payout_uuid=None,
                    payout_txn_uuid=None,
                    updated_at=func.now(),
                )
            )
            await session.commit()
    except Exception:
        logger.warning(
            "contest_payouts.release_payout_link_failed payout_id=%s", payout_id, exc_info=True
        )
