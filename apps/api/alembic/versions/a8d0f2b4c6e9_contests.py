"""Contests, contest results and loan/deal stage markers (CS-027).

Revision ID: a8d0f2b4c6e9
Revises: f6b8d0a2c4e7

2026-11-17 product decision (CS-027, batch G of the stakeholder feedback):
Sub Admins create incentive contests for Agents, Telecallers, Employees or
their managed teams; a platform Admin who is not the maker approves or
rejects; after the end date the Admin confirms winners. Agent prizes are
paid through the existing Payouts maker-checker as ``contest_reward``; staff
prizes are recorded and marked paid by an Admin.

``contests`` (one operational line, immutable):

- audience ``agent`` | ``telecaller`` | ``employee`` | ``team`` (+ the team
  member role), metric, versioned closed ``criteria`` JSON (parsed by
  ``app.schemas.contests``; the database only checks it is a version-1
  object), win mode ``threshold`` | ``top_n`` (+ N), prize per winner or the
  team manager/member prizes and member minimum, optional budget cap,
  inclusive IST start/end dates and status;
- CHECKs: audience/role/prize shapes agree, dates ordered and at most 366
  days, and ``checker_uuid`` is never the maker.

``contest_results`` (end-of-contest snapshot; live standings are never
stored): one row per individual, team, team manager and team member, with
achieved count/amount, metric value, per-target progress (numbers only),
qualified, rank, won, prize, exclusion reason and payment status. Payment
links (``payout_uuid`` unique, ``payout_txn_uuid``) and the staff mark-paid
fields are consistent with ``payment_status`` by CHECK. The payout links are
``ON DELETE SET NULL``: the 7-year retention purge deletes de-linked payouts
and ledger rows, and a contest result (a permanent business record, like a
commission) must never block it; the prize amount stays on the row.

Access (``api_user``; RLS enabled and forced on both):

- ``contests`` SELECT: platform Admin; any Sub Admin (shared authoring
  surface; managers read their team contests); an Agent / Telecaller /
  Employee only for contests at ``approved`` or later on their request line
  whose audience is their role (a team contest when it is for their member
  role). INSERT: a Sub Admin, as maker, as a ``draft`` with no checker.
  UPDATE: the maker Sub Admin while ``draft`` / ``pending_approval`` /
  ``rejected``, only into ``draft`` / ``pending_approval`` / ``cancelled``
  with no checker, so a maker can never approve. DELETE: the maker while
  ``draft``. Approval, rejection, the scheduler moves, finalization and
  Admin cancellation run on the bypass session in ``services/contests.py``.
- ``contest_results`` SELECT only: platform Admin; the participant's own row
  (account plus the request's Agent or staff profile); a Sub Admin for rows
  of the teams they manage. No write grant: rows are written by the
  lifecycle job and Admin commands on the bypass session.

Stage markers for contest scoring (event times, set once by the progress
services; existing rows stay NULL, and no contest can start before its
approval, so no backfill is needed): ``loan_applications.submitted_at`` /
``sanctioned_at`` and ``property_deals.site_visit_done_at`` / ``booked_at`` /
``agreement_signed_at``, each with the column UPDATE grant the existing
progress paths need.

Enum labels: ``payout_type`` and ``transaction_type`` gain
``contest_reward``; ``audit_action`` and ``notification_type`` gain the
contest values. Enum DDL needs a direct connection; restart api and scheduler
after applying (ADR-0004).

Rollback drops both tables, their policies, grants and triggers and the five
stage columns. PostgreSQL cannot drop enum labels, so those stay unused, as in
every additive enum migration here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a8d0f2b4c6e9"
down_revision: str | Sequence[str] | None = "f6b8d0a2c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN = "enforce_business_line_immutable"

_AUDIT_ACTIONS = (
    "contest_created",
    "contest_updated",
    "contest_submitted",
    "contest_deleted",
    "contest_approved",
    "contest_rejected",
    "contest_cancelled",
    "contest_went_live",
    "contest_ended",
    "contest_recalculated",
    "contest_finalized",
    "contest_prize_payout_requested",
    "contest_prize_marked_paid",
)
_NOTIFICATION_TYPES = (
    "contest_submitted",
    "contest_reviewed",
    "contest_live",
    "contest_won",
)

_PLATFORM_ADMIN = (
    "(current_setting('app.platform_scope', true) = 'true' "
    "AND current_setting('app.role', true) = 'admin')"
)
_SUB_ADMIN = "(current_setting('app.role', true) = 'sub_admin')"
_MAKER = (
    "(current_setting('app.role', true) = 'sub_admin' "
    "AND created_by_uuid::text = current_setting('app.auth_user_uuid', true))"
)
_PARTICIPANT_CONTESTS = """
(
    status IN ('approved', 'live', 'ended', 'finalized')
    AND business_line::text = current_setting('app.business_line', true)
    AND (
        (audience = current_setting('app.role', true)
            AND current_setting('app.role', true) IN ('agent', 'telecaller', 'employee'))
        OR (audience = 'team'
            AND team_member_role = current_setting('app.role', true)
            AND current_setting('app.role', true) IN ('telecaller', 'employee'))
    )
)
"""
_OWN_RESULT = """
(
    recipient_user_uuid::text = current_setting('app.auth_user_uuid', true)
    AND (
        (agent_profile_uuid IS NOT NULL
            AND current_setting('app.role', true) = 'agent'
            AND agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true))
        OR (staff_profile_uuid IS NOT NULL
            AND current_setting('app.staff_profile_uuid', true) <> ''
            AND staff_profile_uuid::text = current_setting('app.staff_profile_uuid', true))
    )
)
"""
_MANAGED_TEAM_RESULT = """
(
    current_setting('app.role', true) = 'sub_admin'
    AND team_uuid IS NOT NULL
    AND current_setting('app.staff_profile_uuid', true) <> ''
    AND EXISTS (
        SELECT 1 FROM public.staff_teams AS team
        WHERE team.id = contest_results.team_uuid
          AND team.manager_staff_profile_uuid::text
              = current_setting('app.staff_profile_uuid', true)
    )
)
"""

_LOAN_STAGE_COLUMNS = ("submitted_at", "sanctioned_at")
_DEAL_STAGE_COLUMNS = ("site_visit_done_at", "booked_at", "agreement_signed_at")


def _business_line() -> postgresql.ENUM:
    return postgresql.ENUM(
        "loans", "real_estate", "both", name="business_line_enum", create_type=False
    )


def upgrade() -> None:
    for value in ("contest_reward",):
        op.execute(f"ALTER TYPE payout_type ADD VALUE IF NOT EXISTS '{value}'")
        op.execute(f"ALTER TYPE transaction_type ADD VALUE IF NOT EXISTS '{value}'")
    for value in _AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")
    for value in _NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")

    for column in _LOAN_STAGE_COLUMNS:
        op.add_column(
            "loan_applications", sa.Column(column, sa.DateTime(timezone=True), nullable=True)
        )
    for column in _DEAL_STAGE_COLUMNS:
        op.add_column(
            "property_deals", sa.Column(column, sa.DateTime(timezone=True), nullable=True)
        )
    op.execute(f"GRANT UPDATE ({', '.join(_LOAN_STAGE_COLUMNS)}) ON loan_applications TO api_user")
    op.execute(f"GRANT UPDATE ({', '.join(_DEAL_STAGE_COLUMNS)}) ON property_deals TO api_user")
    # Contest scoring reads stage times by line; partial indexes keep them small.
    op.create_index(
        "ix_loan_applications_sanctioned_at",
        "loan_applications",
        ["sanctioned_at"],
        postgresql_where=sa.text("sanctioned_at IS NOT NULL"),
    )
    op.create_index(
        "ix_loan_applications_submitted_at",
        "loan_applications",
        ["submitted_at"],
        postgresql_where=sa.text("submitted_at IS NOT NULL"),
    )

    op.create_table(
        "contests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("business_line", _business_line(), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("team_member_role", sa.String(length=16), nullable=True),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("criteria_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("win_mode", sa.String(length=16), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=True),
        sa.Column("prize_paise", sa.BigInteger(), nullable=True),
        sa.Column("manager_prize_paise", sa.BigInteger(), nullable=True),
        sa.Column("member_prize_paise", sa.BigInteger(), nullable=True),
        sa.Column("member_min_contribution", sa.BigInteger(), nullable=True),
        sa.Column("budget_cap_paise", sa.BigInteger(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("created_by_uuid", sa.UUID(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checker_uuid", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("live_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_uuid", sa.UUID(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_uuid", sa.UUID(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_contests_business_line_operational"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 3 AND 120", name=op.f("ck_contests_title_present")
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name=op.f("ck_contests_description_length"),
        ),
        sa.CheckConstraint(
            "terms IS NULL OR length(terms) <= 4000", name=op.f("ck_contests_terms_length")
        ),
        sa.CheckConstraint(
            "audience IN ('agent', 'telecaller', 'employee', 'team')",
            name=op.f("ck_contests_audience"),
        ),
        sa.CheckConstraint(
            "(audience = 'team' AND team_member_role IN ('telecaller', 'employee')) "
            "OR (audience <> 'team' AND team_member_role IS NULL)",
            name=op.f("ck_contests_team_member_role"),
        ),
        sa.CheckConstraint(
            "metric IN ('cases', 'amount', 'calls_logged', 'follow_ups_on_time', "
            "'tasks_completed', 'tasks_on_time', 'site_visits_completed')",
            name=op.f("ck_contests_metric"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(criteria) = 'object' AND criteria->>'version' = '1' "
            "AND criteria_version = 1",
            name=op.f("ck_contests_criteria_versioned"),
        ),
        sa.CheckConstraint(
            "(win_mode = 'threshold' AND top_n IS NULL) "
            "OR (win_mode = 'top_n' AND top_n BETWEEN 1 AND 100)",
            name=op.f("ck_contests_win_mode"),
        ),
        sa.CheckConstraint(
            "(audience <> 'team' AND prize_paise BETWEEN 1 AND 1000000000 "
            "AND manager_prize_paise IS NULL AND member_prize_paise IS NULL "
            "AND member_min_contribution IS NULL) "
            "OR (audience = 'team' AND prize_paise IS NULL "
            "AND manager_prize_paise BETWEEN 0 AND 1000000000 "
            "AND member_prize_paise BETWEEN 0 AND 1000000000 "
            "AND manager_prize_paise + member_prize_paise > 0 "
            "AND (member_prize_paise = 0 OR member_min_contribution >= 1))",
            name=op.f("ck_contests_prize_shape"),
        ),
        sa.CheckConstraint(
            "budget_cap_paise IS NULL OR budget_cap_paise BETWEEN 1 AND 100000000000",
            name=op.f("ck_contests_budget_cap"),
        ),
        sa.CheckConstraint(
            "ends_on >= starts_on AND ends_on - starts_on <= 366",
            name=op.f("ck_contests_dates_ordered"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'live', 'ended', "
            "'finalized', 'rejected', 'cancelled')",
            name=op.f("ck_contests_status"),
        ),
        sa.CheckConstraint(
            "checker_uuid IS NULL OR checker_uuid <> created_by_uuid",
            name=op.f("ck_contests_checker_not_maker"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'live', 'ended', 'finalized', 'rejected') "
            "OR (checker_uuid IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_contests_reviewed_has_checker"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_uuid"],
            ["auth_users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_contests_created_by_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["checker_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contests_checker_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contests_finalized_by_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contests_cancelled_by_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contests")),
    )
    op.create_index("ix_contests_status_starts_on", "contests", ["status", "starts_on"])
    op.create_index(
        "ix_contests_line_audience_status", "contests", ["business_line", "audience", "status"]
    )
    op.create_index(op.f("ix_contests_created_by_uuid"), "contests", ["created_by_uuid"])

    op.create_table(
        "contest_results",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("contest_uuid", sa.UUID(), nullable=False),
        sa.Column("business_line", _business_line(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("agent_profile_uuid", sa.UUID(), nullable=True),
        sa.Column("staff_profile_uuid", sa.UUID(), nullable=True),
        sa.Column("team_uuid", sa.UUID(), nullable=True),
        sa.Column("recipient_user_uuid", sa.UUID(), nullable=True),
        sa.Column("achieved_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("achieved_amount_paise", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("metric_value", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("qualified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("won", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("excluded_reason", sa.String(length=32), nullable=True),
        sa.Column("prize_paise", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("payment_status", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("payout_uuid", sa.UUID(), nullable=True),
        sa.Column("payout_txn_uuid", sa.UUID(), nullable=True),
        sa.Column("paid_marked_by_uuid", sa.UUID(), nullable=True),
        sa.Column("paid_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_reference", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_contest_results_business_line_operational"),
        ),
        sa.CheckConstraint(
            "kind IN ('individual', 'team', 'team_manager', 'team_member')",
            name=op.f("ck_contest_results_kind"),
        ),
        # Exactly the participant references each kind needs.
        sa.CheckConstraint(
            "(kind = 'individual' AND team_uuid IS NULL "
            "AND num_nonnulls(agent_profile_uuid, staff_profile_uuid) = 1) "
            "OR (kind = 'team' AND team_uuid IS NOT NULL "
            "AND agent_profile_uuid IS NULL AND staff_profile_uuid IS NULL "
            "AND recipient_user_uuid IS NULL) "
            "OR (kind IN ('team_manager', 'team_member') AND team_uuid IS NOT NULL "
            "AND agent_profile_uuid IS NULL AND staff_profile_uuid IS NOT NULL)",
            name=op.f("ck_contest_results_participant_shape"),
        ),
        sa.CheckConstraint(
            "achieved_count >= 0 AND achieved_amount_paise >= 0 AND metric_value >= 0",
            name=op.f("ck_contest_results_achieved_nonnegative"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(progress) = 'object'", name=op.f("ck_contest_results_progress_object")
        ),
        sa.CheckConstraint("rank IS NULL OR rank >= 1", name=op.f("ck_contest_results_rank")),
        sa.CheckConstraint(
            "excluded_reason IS NULL OR excluded_reason IN ('budget_cap', 'below_member_minimum')",
            name=op.f("ck_contest_results_excluded_reason"),
        ),
        sa.CheckConstraint(
            "prize_paise BETWEEN 0 AND 1000000000 AND (won OR prize_paise = 0)",
            name=op.f("ck_contest_results_prize"),
        ),
        sa.CheckConstraint(
            "payment_status IN ('none', 'unpaid', 'payout_pending', 'paid')",
            name=op.f("ck_contest_results_payment_status"),
        ),
        # A prize is owed exactly when one was won; the payout link exists only
        # for an Agent prize in flight or paid by payout; a staff prize marked
        # paid carries who marked it and when.
        sa.CheckConstraint(
            "(payment_status = 'none') = (prize_paise = 0)",
            name=op.f("ck_contest_results_payment_matches_prize"),
        ),
        # A paid Agent prize may lose its payout / ledger links when the 7-year
        # retention purge deletes a de-linked payout (ON DELETE SET NULL), so
        # "paid" does not require the links to stay.
        sa.CheckConstraint(
            "(payout_uuid IS NULL OR (agent_profile_uuid IS NOT NULL "
            "AND payment_status IN ('payout_pending', 'paid'))) "
            "AND (payment_status <> 'payout_pending' OR payout_uuid IS NOT NULL) "
            "AND (payout_txn_uuid IS NULL OR (agent_profile_uuid IS NOT NULL "
            "AND payment_status = 'paid'))",
            name=op.f("ck_contest_results_payout_link"),
        ),
        sa.CheckConstraint(
            "(paid_marked_by_uuid IS NULL AND paid_marked_at IS NULL AND paid_reference IS NULL) "
            "OR (agent_profile_uuid IS NULL AND payment_status = 'paid' "
            "AND paid_marked_at IS NOT NULL)",
            name=op.f("ck_contest_results_mark_paid_staff_only"),
        ),
        sa.ForeignKeyConstraint(
            ["contest_uuid"],
            ["contests.id"],
            ondelete="RESTRICT",
            name=op.f("fk_contest_results_contest_uuid_contests"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_profile_uuid"],
            ["agent_profiles.id"],
            ondelete="RESTRICT",
            name=op.f("fk_contest_results_agent_profile_uuid_agent_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_profile_uuid"],
            ["staff_profiles.id"],
            ondelete="RESTRICT",
            name=op.f("fk_contest_results_staff_profile_uuid_staff_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["team_uuid"],
            ["staff_teams.id"],
            ondelete="RESTRICT",
            name=op.f("fk_contest_results_team_uuid_staff_teams"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contest_results_recipient_user_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["payout_uuid"],
            ["payouts.id"],
            ondelete="SET NULL",
            name=op.f("fk_contest_results_payout_uuid_payouts"),
        ),
        sa.ForeignKeyConstraint(
            ["payout_txn_uuid"],
            ["transactions.id"],
            ondelete="SET NULL",
            name=op.f("fk_contest_results_payout_txn_uuid_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["paid_marked_by_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contest_results_paid_marked_by_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contest_results")),
    )
    # One row per participant per contest.
    op.execute(
        "CREATE UNIQUE INDEX uq_contest_results_participant ON contest_results ("
        "contest_uuid, kind, "
        "COALESCE(team_uuid, '00000000-0000-0000-0000-000000000000'::uuid), "
        "COALESCE(agent_profile_uuid, '00000000-0000-0000-0000-000000000000'::uuid), "
        "COALESCE(staff_profile_uuid, '00000000-0000-0000-0000-000000000000'::uuid))"
    )
    # One payout per result, and a payout pays at most one result.
    op.create_index(
        "uq_contest_results_payout_uuid",
        "contest_results",
        ["payout_uuid"],
        unique=True,
        postgresql_where=sa.text("payout_uuid IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_contest_results_recipient_user_uuid"), "contest_results", ["recipient_user_uuid"]
    )
    op.create_index(op.f("ix_contest_results_team_uuid"), "contest_results", ["team_uuid"])

    for table in ("contests", "contest_results"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_business_line_immutable "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_FN}()"
        )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON contests TO api_user")
    op.execute("ALTER TABLE contests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE contests FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY contests_select ON contests
        FOR SELECT
        USING ({_PLATFORM_ADMIN} OR {_SUB_ADMIN} OR {_PARTICIPANT_CONTESTS})
        """
    )
    op.execute(
        f"""
        CREATE POLICY contests_insert ON contests
        FOR INSERT
        WITH CHECK ({_MAKER} AND status = 'draft' AND checker_uuid IS NULL)
        """
    )
    op.execute(
        f"""
        CREATE POLICY contests_update ON contests
        FOR UPDATE
        USING ({_MAKER} AND status IN ('draft', 'pending_approval', 'rejected'))
        WITH CHECK (
            {_MAKER}
            AND status IN ('draft', 'pending_approval', 'cancelled')
            AND checker_uuid IS NULL
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY contests_delete ON contests
        FOR DELETE
        USING ({_MAKER} AND status = 'draft')
        """
    )

    op.execute("GRANT SELECT ON contest_results TO api_user")
    op.execute("ALTER TABLE contest_results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE contest_results FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY contest_results_select ON contest_results
        FOR SELECT
        USING ({_PLATFORM_ADMIN} OR {_OWN_RESULT} OR {_MANAGED_TEAM_RESULT})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS contest_results_select ON contest_results")
    op.execute("REVOKE ALL PRIVILEGES ON contest_results FROM api_user")
    for policy in ("contests_delete", "contests_update", "contests_insert", "contests_select"):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON contests")
    op.execute("REVOKE ALL PRIVILEGES ON contests FROM api_user")
    for table in ("contest_results", "contests"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_business_line_immutable ON {table}")
    op.drop_table("contest_results")
    op.drop_table("contests")

    op.drop_index("ix_loan_applications_submitted_at", table_name="loan_applications")
    op.drop_index("ix_loan_applications_sanctioned_at", table_name="loan_applications")
    op.execute(f"REVOKE UPDATE ({', '.join(_DEAL_STAGE_COLUMNS)}) ON property_deals FROM api_user")
    op.execute(
        f"REVOKE UPDATE ({', '.join(_LOAN_STAGE_COLUMNS)}) ON loan_applications FROM api_user"
    )
    for column in reversed(_DEAL_STAGE_COLUMNS):
        op.drop_column("property_deals", column)
    for column in reversed(_LOAN_STAGE_COLUMNS):
        op.drop_column("loan_applications", column)
    # Enum labels stay: PostgreSQL has no DROP VALUE (see module docstring).
