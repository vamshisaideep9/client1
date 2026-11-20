"""Lead spine — every captured mobile lands here (master_erd.mermaid §LEAD SPINE).

A lead is a sales/follow-up record, NOT an account. It is created only when the
visitor expresses Loans or Real Estate intent. Authentication attempts without
service intent remain auth events and never enter this operational table.
`client_profile_uuid` stays NULL until the lead is claimed/registered. One mobile
may have independent live Loans and Real Estate journeys.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import business_line_enum


class LeadOrigin(enum.StrEnum):
    DIRECT = "direct"
    AGENT = "agent"


class LeadStatus(enum.StrEnum):
    NEW = "new"
    ASSIGNED = "assigned"
    WORKING = "working"
    CONVERTED = "converted"
    CLOSED = "closed"
    RELEASED = "released"


_ev = lambda x: [e.value for e in x]  # noqa: E731
lead_origin_enum = ENUM(LeadOrigin, name="lead_origin", create_type=False, values_callable=_ev)
lead_status_enum = ENUM(LeadStatus, name="lead_status", create_type=False, values_callable=_ev)


class LeadAssignmentCursor(Base):
    """Internal per-line, per-candidate-pool automatic assignment cursor."""

    __tablename__ = "lead_assignment_cursors"
    __table_args__ = (
        CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name="business_line_operational",
        ),
        CheckConstraint(
            "pool = 'all' OR (business_line::text = 'loans' AND "
            "(pool = 'unspecialised' OR pool ~ "
            "'^product:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))",
            name="pool",
        ),
    )

    business_line: Mapped[str] = mapped_column(
        business_line_enum,
        primary_key=True,
    )
    pool: Mapped[str] = mapped_column(
        String(64), primary_key=True, default="all", server_default="all"
    )
    last_telecaller_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name="business_line_operational",
        ),
        Index(
            "uq_leads_mobile_line_live",
            "mobile",
            "business_line",
            unique=True,
            postgresql_where=text("business_line IS NOT NULL AND status <> 'closed'"),
        ),
        Index(
            "uq_leads_mobile_agent_live",
            "mobile",
            unique=True,
            postgresql_where=text(
                "origin_agent_profile_uuid IS NOT NULL "
                "AND agent_expired_at IS NULL AND status <> 'closed'"
            ),
        ),
        Index(
            "ix_leads_assignment_workload",
            "business_line",
            "assigned_telecaller_profile_uuid",
            "status",
            postgresql_where=text("assigned_telecaller_profile_uuid IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Operational rows are classified at creation. ``both`` is an identity claim,
    # never a record value; the database check and additive migration enforce it.
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    origin: Mapped[LeadOrigin] = mapped_column(
        lead_origin_enum, nullable=False, default=LeadOrigin.DIRECT
    )
    origin_agent_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_telecaller_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    mobile: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requirement: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # Internal field-path ownership ledger for FR-2.8. Keys are ``name`` or
    # ``requirement.<top-level-key>``; values contain an owner role and, for
    # authenticated creators, the owning profile/user UUID. The API exposes
    # only safe role labels and computed editable fields, never these UUIDs.
    detail_ownership: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, default=dict
    )
    status: Mapped[LeadStatus] = mapped_column(
        lead_status_enum, nullable=False, default=LeadStatus.NEW
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # Agent attribution has a fixed protection window (FR-4.6). Operational
    # status remains independent so an expired lead can return to the open
    # Telecaller pool and continue through assigned/working/converted later.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Same-Agent resubmissions after expiry (2026-11-14 amendment to FR-4.6).
    resubmit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Set once the 7-day "client hasn't registered" reminder is sent for the
    # current window; cleared when the Agent resubmits.
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # CS-028: the Telecaller whose assignment was most recently cleared
    # (expiry, stale-assignee repair, Admin release). A resubmitted lead goes
    # back to them while they are still eligible. The trigger
    # trg_leads_last_telecaller_guard allows only the assignee being cleared.
    last_telecaller_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # CS-028: when the originating Agent last resubmitted the lead.
    last_resubmitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
