"""Manual call-activity log — the telecaller's per-attempt record on a lead.

Replaces the cloud-telephony webhook call log that's out of the current web-only
scope (docs/architecture/Telecaller_Dashboard_System_Design.md §1.1): a telecaller
dials the lead directly on their own device, then logs the outcome here. Each row
is an immutable attempt record (no UPDATE/DELETE grant — see the migration);
corrections happen by logging a new attempt, not editing history.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import business_line_enum


class CallDisposition(enum.StrEnum):
    CONNECTED = "connected"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    SWITCHED_OFF = "switched_off"
    WRONG_NUMBER = "wrong_number"
    CALLBACK_REQUESTED = "callback_requested"
    NOT_INTERESTED = "not_interested"


class InterestLevel(enum.StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


_ev = lambda x: [e.value for e in x]  # noqa: E731
call_disposition_enum = ENUM(
    CallDisposition, name="call_disposition", create_type=False, values_callable=_ev
)
interest_level_enum = ENUM(
    InterestLevel, name="interest_level", create_type=False, values_callable=_ev
)


class LeadActivity(Base):
    __tablename__ = "lead_activities"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(loan_application_uuid, financial_service_enquiry_uuid, "
            "enquiry_uuid, site_visit_uuid, property_deal_uuid) <= 1",
            name="single_request_link",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    telecaller_staff_profile_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_profiles.id"), nullable=False
    )
    # Stamped from the lead at insert; immutable (enforce_business_line_immutable
    # trigger), same discriminator every business-scoped table carries.
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    disposition: Mapped[CallDisposition] = mapped_column(call_disposition_enum, nullable=False)
    interest_level: Mapped[InterestLevel | None] = mapped_column(interest_level_enum, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # At most one request this call was about (ck_lead_activities_single_request_link,
    # migration e7a9c1b3d5f8). All NULL means a general call on the lead.
    loan_application_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    financial_service_enquiry_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_service_enquiries.id", ondelete="SET NULL"),
        nullable=True,
    )
    enquiry_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enquiries.id", ondelete="SET NULL"), nullable=True
    )
    site_visit_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("site_visits.id", ondelete="SET NULL"), nullable=True
    )
    property_deal_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("property_deals.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
