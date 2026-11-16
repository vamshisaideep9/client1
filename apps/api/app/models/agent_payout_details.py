"""Agent-saved payout destination (bank account and/or UPI ID), encrypted at rest.

One row per Agent profile. Raw values are stored only as AES-GCM blobs
(core/field_crypto.py); the masked ``*_hint`` columns are what the Agent's own
screens show. Payout makers read the decrypted values only through an
audited service call (services/agent_payout_details.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AgentPayoutDetails(Base):
    __tablename__ = "agent_payout_details"
    __table_args__ = (
        CheckConstraint(
            "upi_ciphertext IS NOT NULL OR bank_ciphertext IS NOT NULL",
            name="has_destination",
        ),
        CheckConstraint(
            "(upi_ciphertext IS NULL) = (upi_hint IS NULL)",
            name="upi_hint_pairs",
        ),
        CheckConstraint(
            "(bank_ciphertext IS NULL) = (bank_hint IS NULL)",
            name="bank_hint_pairs",
        ),
    )

    agent_profile_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Denormalized owner so RLS and account deletion key on the identity.
    auth_user_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upi_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    upi_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bank_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    bank_hint: Mapped[str | None] = mapped_column(String(60), nullable=True)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
