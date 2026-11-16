"""Remind an Agent seven days before their lead's window ends (FR-4.6 amendment).

2026-11-14 product decision: if the client has not registered when an Agent's
30-day window has seven days left, the Agent is notified so they can follow up
before the lead returns to the open pool.

Each bounded batch is claimed by a ``FOR UPDATE SKIP LOCKED`` CTE and stamped
with ``expiry_reminder_sent_at`` in the same ``UPDATE``, so retries and multiple
scheduler replicas send at most one reminder per window. A resubmission clears
the stamp, giving the new window its own reminder. Notifications are
best-effort and sent only after the stamp commits.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.models.lead import Lead, LeadStatus
from app.models.notification import NotificationType
from app.models.profile import AgentProfile
from app.services.notifications import emit_notification

logger = logging.getLogger("scheduler")

_BATCH_SIZE = 500
REMINDER_LEAD_TIME = timedelta(days=7)


@dataclass(frozen=True)
class _Reminder:
    lead_id: UUID
    agent_user_uuid: UUID


async def _remind_batch(session: AsyncSession) -> tuple[int, list[_Reminder]]:
    """Stamp one batch and return (claimed row count, reminders to send)."""
    due = (
        select(Lead.id.label("lead_id"))
        .where(
            Lead.origin_agent_profile_uuid.is_not(None),
            Lead.expires_at.is_not(None),
            Lead.expires_at > func.now(),
            Lead.expires_at <= func.now() + REMINDER_LEAD_TIME,
            Lead.agent_expired_at.is_(None),
            Lead.client_profile_uuid.is_(None),
            Lead.expiry_reminder_sent_at.is_(None),
            Lead.status.not_in((LeadStatus.CONVERTED, LeadStatus.CLOSED)),
        )
        .order_by(Lead.expires_at, Lead.id)
        .limit(_BATCH_SIZE)
        .with_for_update(skip_locked=True)
        .cte("due_agent_lead_reminders")
    )
    rows = (
        await session.execute(
            update(Lead)
            .where(Lead.id == due.c.lead_id)
            .values(expiry_reminder_sent_at=func.now())
            .returning(Lead.id, Lead.origin_agent_profile_uuid)
            .execution_options(synchronize_session=False)
        )
    ).all()
    if not rows:
        await session.rollback()
        return 0, []

    agent_users = dict(
        (
            await session.execute(
                select(AgentProfile.id, AgentProfile.auth_user_uuid).where(
                    AgentProfile.id.in_({row.origin_agent_profile_uuid for row in rows})
                )
            )
        ).all()
    )
    await session.commit()
    return len(rows), [
        _Reminder(lead_id=row.id, agent_user_uuid=agent_users[row.origin_agent_profile_uuid])
        for row in rows
        if agent_users.get(row.origin_agent_profile_uuid) is not None
    ]


async def _notify(reminder: _Reminder) -> None:
    await emit_notification(
        user_uuid=reminder.agent_user_uuid,
        notification_type=NotificationType.AGENT_LEAD_EXPIRY_REMINDER,
        title="Lead expires in 7 days",
        body=(
            "Your client hasn't registered yet. Follow up now; if the lead expires "
            "you can resubmit it."
        ),
        href=f"/dashboard/leads/{reminder.lead_id}",
    )


async def remind_agent_lead_expiry() -> dict[str, int]:
    started = time.monotonic()
    logger.info("job.remind_agent_lead_expiry.start")
    reminded = 0
    try:
        while True:
            async with db_session.AsyncSessionLocal() as session:
                claimed, batch = await _remind_batch(session)
            for reminder in batch:
                await _notify(reminder)
            reminded += len(batch)
            if claimed < _BATCH_SIZE:
                break
    except Exception:
        logger.exception("job.remind_agent_lead_expiry.failed")
        raise
    else:
        logger.info(
            "job.remind_agent_lead_expiry.success reminded=%d duration_ms=%d",
            reminded,
            (time.monotonic() - started) * 1000,
        )
        return {"reminded": reminded}
