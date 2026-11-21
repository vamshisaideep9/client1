"""Per-staff IST attendance, effective-dated policy, and reviewed requests."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AttendancePolicy(Base):
    __tablename__ = "attendance_policies"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date)
    shift_start_minute: Mapped[int] = mapped_column(Integer)
    shift_minutes: Mapped[int] = mapped_column(Integer)
    grace_minutes: Mapped[int] = mapped_column(Integer)
    half_day_minutes: Mapped[int] = mapped_column(Integer)
    full_day_minutes: Mapped[int] = mapped_column(Integer)
    weekly_off: Mapped[list[int]] = mapped_column(JSONB)
    leave_quotas: Mapped[dict[str, int]] = mapped_column(JSONB)
    session_clock: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_users.id", ondelete="SET NULL")
    )


class AttendanceHoliday(Base):
    __tablename__ = "attendance_holidays"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class AttendanceRequest(Base):
    __tablename__ = "attendance_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="CASCADE")
    )
    requester_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    leave_type: Mapped[str | None] = mapped_column(String(32))
    half_day: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_units: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    correction_before: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    decisions: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business_line: Mapped[str | None] = mapped_column(String(12))
    two_stage: Mapped[bool] = mapped_column(Boolean, default=False)
    adjustment_type: Mapped[str | None] = mapped_column(String(16))
    leave_session: Mapped[str | None] = mapped_column(String(9))


class AttendanceDay(Base):
    __tablename__ = "attendance_days"

    staff_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    policy_version: Mapped[int] = mapped_column(ForeignKey("attendance_policies.version"))
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(12))
    original_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    leave_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attendance_requests.id", ondelete="SET NULL")
    )
    leave_units: Mapped[int] = mapped_column(Integer, default=0)
    correction_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attendance_requests.id", ondelete="SET NULL")
    )
    system_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_status: Mapped[str | None] = mapped_column(String(12))
    morning_covered: Mapped[bool | None] = mapped_column(Boolean)
    afternoon_covered: Mapped[bool | None] = mapped_column(Boolean)
    early_exit: Mapped[bool] = mapped_column(Boolean, default=False)
    uncovered_units: Mapped[int | None] = mapped_column(SmallInteger)
    lop_units: Mapped[int | None] = mapped_column(SmallInteger)
    adjustments: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    leave_sessions: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    business_line: Mapped[str | None] = mapped_column(String(12))


class AttendanceRolloverState(Base):
    __tablename__ = "attendance_rollover_state"

    staff_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    through_day: Mapped[date] = mapped_column(Date)


ATTENDANCE_ROLLOVER_LOCK = 1_885_206_137
ATTENDANCE_POLICY_LOCK = 1_885_206_138
