"""Sub Admin managers over single-role Telecaller / Employee teams (CS-019).

A team is one operational line plus one member role. Its manager is an active
platform Sub Admin; reach over the members' work is granted by the
``team_manager_reaches`` RLS predicate (migration e4f6a8c0b2d5), which reads
these rows live. Teams never change how leads or tasks are routed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import business_line_enum


class TeamMemberRole(enum.StrEnum):
    TELECALLER = "telecaller"
    EMPLOYEE = "employee"


class StaffTeam(Base):
    __tablename__ = "staff_teams"
    __table_args__ = (
        CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')", name="business_line_operational"
        ),
        CheckConstraint("member_role IN ('telecaller', 'employee')", name="member_role_supported"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 80", name="name_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    member_role: Mapped[str] = mapped_column(String(16), nullable=False)
    manager_staff_profile_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_auth_user_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class StaffTeamMember(Base):
    __tablename__ = "staff_team_members"
    __table_args__ = (
        CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')", name="business_line_operational"
        ),
        UniqueConstraint("staff_profile_uuid", "business_line"),
    )

    team_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_teams.id", ondelete="CASCADE"), primary_key=True
    )
    staff_profile_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    # Denormalized team line so "one team per line per member" is a plain
    # unique constraint; the insert policy pins it to the team's line.
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    added_by_auth_user_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
