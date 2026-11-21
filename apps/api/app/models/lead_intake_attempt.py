"""Rejected lead introductions and referral sign-ups (CS-024).

One row per attempt the platform turned away: an Agent introducing a number
that is already linked elsewhere, or a referral code used by someone who was
already referred. Accepted leads and referrals derive their eligibility from
their own rows; this table only exists so the owner can see what was *not*
accepted ("Not accepted" on the Agent Leads and Client Referrals pages).

The number is stored only as its last four digits plus a keyed fingerprint
(``services/lead_intake_attempts.py::mobile_fingerprint``); the raw mobile is
never written. Rows are written on the bypass session and read by the owner
through RLS (migration ``c7e9a1b3d5f8``); they are erased with the owner's
account.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import business_line_enum


class IntakeActorType(enum.StrEnum):
    AGENT = "agent"
    REFERRER = "referrer"


class IntakeOutcome(enum.StrEnum):
    DUPLICATE = "duplicate"
    NOT_ELIGIBLE = "not_eligible"


class LeadIntakeAttempt(Base):
    __tablename__ = "lead_intake_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # agent -> agent_profiles.id; referrer -> auth_users.id (= auth_user_uuid).
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    auth_user_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False
    )
    mobile_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    mobile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    business_line: Mapped[str | None] = mapped_column(business_line_enum, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
