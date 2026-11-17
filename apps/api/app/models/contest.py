"""Contests (CS-027): Sub Admin-authored, Admin-approved incentive contests.

A contest targets one operational line and one audience: Agents, Telecallers,
Employees, or Sub Admin-managed teams of Telecallers or Employees. Its
``criteria`` is a versioned, closed grammar parsed by
``app.schemas.contests.ContestCriteria`` on every authoring and scoring path;
it is never interpreted as arbitrary JSON.

Lifecycle: ``draft -> pending_approval -> approved -> live -> ended ->
finalized`` with ``rejected`` (edit and resubmit) and ``cancelled`` side
branches. The Sub Admin maker writes drafts under RLS; approval, rejection,
the scheduler-owned ``approved -> live -> ended`` moves and finalization run
in ``services/contests.py`` on the bypass session, with the maker never
allowed to act as checker (also a CHECK constraint).

``contest_results`` is the end-of-contest snapshot written by the lifecycle
job (and Admin recalculation while ``ended``). Live standings are computed on
read and never stored. One row per individual participant, per team, and per
person who can receive a team prize (the manager and each member), so every
prize is exactly one row: Agent prizes link to one ``contest_reward`` payout,
staff prizes are recorded and marked paid by a platform Admin.

Money is integer paise.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import business_line_enum


class ContestAudience(enum.StrEnum):
    AGENT = "agent"
    TELECALLER = "telecaller"
    EMPLOYEE = "employee"
    TEAM = "team"


class ContestTeamMemberRole(enum.StrEnum):
    TELECALLER = "telecaller"
    EMPLOYEE = "employee"


class ContestMetric(enum.StrEnum):
    """What a contest ranks and reports as "achieved"."""

    CASES = "cases"  # qualifying loan cases or property deals
    AMOUNT = "amount"  # their true amount (sanctioned / requested / deal value)
    CALLS_LOGGED = "calls_logged"
    FOLLOW_UPS_ON_TIME = "follow_ups_on_time"
    TASKS_COMPLETED = "tasks_completed"
    TASKS_ON_TIME = "tasks_on_time"
    SITE_VISITS_COMPLETED = "site_visits_completed"


class ContestWinMode(enum.StrEnum):
    THRESHOLD = "threshold"  # everyone who meets every target wins
    TOP_N = "top_n"  # the N best qualifying participants win


class ContestStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    LIVE = "live"
    ENDED = "ended"
    FINALIZED = "finalized"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ContestResultKind(enum.StrEnum):
    INDIVIDUAL = "individual"  # one Agent, Telecaller or Employee
    TEAM = "team"  # a team's combined standing (no prize of its own)
    TEAM_MANAGER = "team_manager"  # the managing Sub Admin's prize row
    TEAM_MEMBER = "team_member"  # one member's contribution and prize row


class ContestPaymentStatus(enum.StrEnum):
    NONE = "none"  # no prize
    UNPAID = "unpaid"  # prize owed, nothing requested yet
    PAYOUT_PENDING = "payout_pending"  # Agent prize: a contest_reward payout is in flight
    PAID = "paid"  # Agent payout settled, or staff prize marked paid


class ContestExclusion(enum.StrEnum):
    """Why a participant who met the targets is not a winner."""

    BUDGET_CAP = "budget_cap"
    BELOW_MEMBER_MINIMUM = "below_member_minimum"


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    team_member_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    criteria_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    win_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    top_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prize_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    manager_prize_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    member_prize_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # In the contest metric's unit (count, or paise for the amount metric).
    member_min_contribution: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    budget_cap_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Inclusive India Standard Time calendar dates.
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContestStatus.DRAFT.value
    )
    # Maker (RLS owner axis for draft edits) and checker. The checker can
    # never be the maker (ck_contests_checker_not_maker).
    created_by_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checker_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_by_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ContestResult(Base):
    __tablename__ = "contest_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contest_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contests.id", ondelete="RESTRICT"), nullable=False
    )
    business_line: Mapped[str] = mapped_column(business_line_enum, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    staff_profile_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    team_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_teams.id", ondelete="RESTRICT"), nullable=True
    )
    # The account a prize is owed to (NULL on a team row). SET NULL on
    # account de-link, like payouts and transactions.
    recipient_user_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    achieved_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    achieved_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    metric_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Closed per-target progress snapshot (numbers only, keyed by target).
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    qualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prize_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContestPaymentStatus.NONE.value
    )
    payout_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payouts.id", ondelete="SET NULL"), nullable=True
    )
    payout_txn_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    paid_marked_by_uuid: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    paid_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
