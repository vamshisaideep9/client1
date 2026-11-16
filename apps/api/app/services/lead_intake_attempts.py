"""Record and read rejected lead introductions and referral sign-ups (CS-024).

Writes run on their own bypass session (``app`` superuser), never on the
caller's transaction: the Agent capture transaction that rejects a number is
rolled back, and a referral attribution is best-effort, so the attempt must be
committed independently or it would vanish with the rejection. Recording is
itself best-effort: any failure is logged (masked) and swallowed so it can
never change the response the caller already gets.

The number is kept only as its last four digits plus a keyed fingerprint.
The fingerprint is an HMAC-SHA256 under ``SECRET_KEY`` with a purpose prefix
(the same construction as the cheque-reference fingerprint in
``services/payments.py``), so it links repeat attempts on one number without
being reversible by hashing every possible mobile.

An identical attempt (same owner, number and reason) within 24 hours is not
stored again, so a double submit or a retry does not inflate the counts.

Reads run on the caller's request session; ``lead_intake_attempts`` RLS
returns only the caller's own rows, and every query also names the actor.

``import app.db.session as db_session`` is resolved at call time so the test
suite's NullPool rebind applies (same convention as ``services/referrals.py``).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.core.config import settings
from app.core.masking import mask_mobile
from app.models.lead_intake_attempt import IntakeActorType, IntakeOutcome, LeadIntakeAttempt
from app.models.profile import AgentProfile
from app.schemas.eligibility import EligibilitySummary, IntakeAttemptRead
from app.services.eligibility import (
    ATTEMPT_OUTCOME,
    EligibilityReason,
    RowEligibility,
    reason_label,
)

logger = logging.getLogger(__name__)

_REPEAT_WINDOW = timedelta(hours=24)
_NON_DIGITS = re.compile(r"\D")


def mobile_fingerprint(mobile: str) -> str:
    """Keyed, purpose-bound fingerprint of an E.164 mobile number."""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"lead-intake-mobile:{mobile.strip()}".encode(),
        hashlib.sha256,
    ).hexdigest()


def mobile_last4(mobile: str) -> str | None:
    digits = _NON_DIGITS.sub("", mobile)
    return digits[-4:] if len(digits) >= 4 else None


def masked(last4: str) -> str:
    return f"***{last4}"


async def record_attempt(
    *,
    actor_type: IntakeActorType,
    actor_uuid: UUID,
    mobile: str,
    reason: EligibilityReason,
    business_line: str | None = None,
    auth_user_uuid: UUID | None = None,
) -> None:
    """Store one rejected attempt. Never raises.

    ``auth_user_uuid`` is the owning account: required for a referrer (it is
    their ``actor_uuid``), looked up from the Agent profile otherwise.
    """
    try:
        outcome = ATTEMPT_OUTCOME[reason]
        last4 = mobile_last4(mobile)
        if last4 is None:
            return
        fingerprint = mobile_fingerprint(mobile)
        line = business_line if business_line in ("loans", "real_estate") else None
        async with db_session.AsyncSessionLocal() as session:
            owner = auth_user_uuid
            if actor_type == IntakeActorType.AGENT:
                owner = await session.scalar(
                    select(AgentProfile.auth_user_uuid).where(AgentProfile.id == actor_uuid)
                )
            if owner is None:
                return
            repeated = await session.scalar(
                select(LeadIntakeAttempt.id)
                .where(
                    LeadIntakeAttempt.actor_type == actor_type.value,
                    LeadIntakeAttempt.actor_uuid == actor_uuid,
                    LeadIntakeAttempt.mobile_fingerprint == fingerprint,
                    LeadIntakeAttempt.reason_code == reason.value,
                    LeadIntakeAttempt.created_at > datetime.now(UTC) - _REPEAT_WINDOW,
                )
                .limit(1)
            )
            if repeated is not None:
                return
            session.add(
                LeadIntakeAttempt(
                    actor_type=actor_type.value,
                    actor_uuid=actor_uuid,
                    auth_user_uuid=owner,
                    mobile_last4=last4,
                    mobile_fingerprint=fingerprint,
                    business_line=line,
                    outcome=outcome.value,
                    reason_code=reason.value,
                )
            )
            await session.commit()
    except Exception:
        logger.warning(
            "lead_intake_attempts.record_failed actor_type=%s reason=%s mobile=%s",
            actor_type,
            reason,
            mask_mobile(mobile),
            exc_info=True,
        )


def _actor(actor_type: IntakeActorType, actor_uuid: UUID):  # noqa: ANN202
    return (
        LeadIntakeAttempt.actor_type == actor_type.value,
        LeadIntakeAttempt.actor_uuid == actor_uuid,
    )


async def outcome_counts(
    db: AsyncSession, actor_type: IntakeActorType, actor_uuid: UUID
) -> dict[IntakeOutcome, int]:
    rows = await db.execute(
        select(LeadIntakeAttempt.outcome, func.count())
        .where(*_actor(actor_type, actor_uuid))
        .group_by(LeadIntakeAttempt.outcome)
    )
    counts = dict.fromkeys(IntakeOutcome, 0)
    for outcome, count in rows.all():
        counts[IntakeOutcome(outcome)] = int(count)
    return counts


async def eligibility_summary(
    db: AsyncSession,
    actor_type: IntakeActorType,
    actor_uuid: UUID,
    row_outcomes: Iterable[RowEligibility],
) -> EligibilitySummary:
    """Combine the accepted rows' derived outcomes with the recorded attempts."""
    eligible = not_eligible = 0
    for outcome in row_outcomes:
        if outcome == "eligible":
            eligible += 1
        else:
            not_eligible += 1
    attempts = await outcome_counts(db, actor_type, actor_uuid)
    return EligibilitySummary(
        eligible=eligible,
        not_eligible=not_eligible + attempts[IntakeOutcome.NOT_ELIGIBLE],
        duplicate=attempts[IntakeOutcome.DUPLICATE],
        not_accepted=sum(attempts.values()),
    )


async def list_attempts(
    db: AsyncSession,
    actor_type: IntakeActorType,
    actor_uuid: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[IntakeAttemptRead], int]:
    total = (
        await db.scalar(
            select(func.count())
            .select_from(LeadIntakeAttempt)
            .where(*_actor(actor_type, actor_uuid))
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(LeadIntakeAttempt)
            .where(*_actor(actor_type, actor_uuid))
            .order_by(LeadIntakeAttempt.created_at.desc(), LeadIntakeAttempt.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        IntakeAttemptRead(
            id=row.id,
            outcome=row.outcome,  # type: ignore[arg-type]
            reason=row.reason_code,  # type: ignore[arg-type]
            reason_label=reason_label(row.reason_code) or "Not accepted",
            mobile_masked=masked(row.mobile_last4),
            business_line=row.business_line,  # type: ignore[arg-type]
            created_at=row.created_at,
        )
        for row in rows
    ]
    return items, int(total)
