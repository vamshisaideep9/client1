"""Agent-saved payout destination (bank account and/or UPI ID), encrypted at rest.

One row per Agent profile. Raw values are stored only as AES-GCM blobs
(core/field_crypto.py); the masked ``*_hint`` columns are what the Agent's own
screens show. Payout makers read the decrypted values only through an
audited service call (services/agent_payout_details.py). An optional cancelled
cheque is stored as a private object (services/agent_payout_cheque.py).
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
        CheckConstraint(
            "(cheque_object_key IS NULL) = (cheque_content_type IS NULL) "
            "AND (cheque_object_key IS NULL) = (cheque_uploaded_at IS NULL)",
            name="cheque_fields_pair",
        ),
        CheckConstraint(
            "cheque_content_type IS NULL "
            "OR cheque_content_type IN ('image/jpeg', 'image/png', 'application/pdf')",
            name="cheque_content_type_allowed",
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
    # Optional cancelled cheque (CS-022): a private, sanitized canonical object
    # that only payout makers can open (audited). Set or cleared together.
    cheque_object_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cheque_content_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cheque_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
