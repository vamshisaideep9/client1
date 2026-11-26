"""Phone and email changes and the permanent contact history (CS-025).

``ContactChangeRequest`` is one state machine for three journeys:

- ``self_service`` (Client, Agent, Admin): password, a code to the current
  value, the new value, a code to the new value, then an atomic update;
- ``email_add`` (an account without a verified email): the new address and a
  code to it;
- ``staff_request`` (Telecaller, Employee, Sub Admin): the new value and a code
  to it, then one platform Admin approves or rejects.

The raw new value is kept only while the row is active (a database CHECK
forbids it on every terminal status); the current value is represented only by
a keyed fingerprint. ``ContactChangeHistory`` is the permanent, platform-Admin-
only record of every completed change, erased only with the account (migration
``d4f6a8c0e2b4``).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContactField(enum.StrEnum):
    MOBILE = "mobile"
    EMAIL = "email"


class ContactChangeKind(enum.StrEnum):
    SELF_SERVICE = "self_service"
    EMAIL_ADD = "email_add"
    STAFF_REQUEST = "staff_request"


class ContactChangeStatus(enum.StrEnum):
    AWAITING_CURRENT_OTP = "awaiting_current_otp"
    AWAITING_NEW_VALUE = "awaiting_new_value"
    AWAITING_NEW_OTP = "awaiting_new_otp"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


ACTIVE_CONTACT_CHANGE_STATUSES = frozenset(
    {
        ContactChangeStatus.AWAITING_CURRENT_OTP,
        ContactChangeStatus.AWAITING_NEW_VALUE,
        ContactChangeStatus.AWAITING_NEW_OTP,
        ContactChangeStatus.PENDING_APPROVAL,
    }
)


class ContactChangeMethod(enum.StrEnum):
    SELF_SERVICE = "self_service"
    EMAIL_ADDED = "email_added"
    ADMIN_APPROVED = "admin_approved"
    LOST_NUMBER_RECOVERY = "lost_number_recovery"


class ContactChangeRequest(Base):
    __tablename__ = "contact_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    auth_user_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    field: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    # Keyed fingerprint of the value being replaced, captured at start; never
    # the value itself. Completion refuses when the live value no longer
    # matches (another change landed in between).
    current_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Raw only while active; cleared on every terminal status (DB CHECK).
    new_value: Mapped[str | None] = mapped_column(String(320), nullable=True)
    current_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    new_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class ContactChangeHistory(Base):
    __tablename__ = "contact_change_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    auth_user_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(8), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(320), nullable=True)
    new_value: Mapped[str] = mapped_column(String(320), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    proof_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # PII-free operational reference only (lost-number proof attestation).
    proof_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    approved_by_user_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    # The contact_change_requests or mobile_change_requests row it came from.
    request_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
