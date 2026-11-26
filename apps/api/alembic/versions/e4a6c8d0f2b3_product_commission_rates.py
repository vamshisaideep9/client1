"""Per-loan-product commission rates with maker-checker (CS-028).

Revision ID: e4a6c8d0f2b3
Revises: d3f5b7c9e1a2

2026-11-19 product decision (CS-028, batch 2 "Agent leads"): when a loans
Agent picks a loan product on the lead form they see the commission for it.
A Sub Admin or a platform Admin enters the rate; a Sub Admin's entry needs a
platform Admin's approval. The rate is a percent of the loan amount or a
fixed rupee amount plus an optional short note. It is indicative: the
per-deal commission is still entered by the Admin (``commissions``), now
pre-filled from it.

``product_commission_rates`` (loan-category products only, checked by the
service; rows cascade with an unused product the Admin deletes):

- ``kind`` ``percent`` (``percent_bps`` 1..10000, i.e. 0.01 %..100 %) XOR
  ``fixed`` (``amount_paise`` 1..10^10, the per-commission cap), ``note``
  (<= 280), ``status`` ``pending_approval | approved | rejected | superseded |
  withdrawn``, the maker (``created_by_uuid``, ``created_by_role``
  ``admin | sub_admin``), the checker (``checker_uuid``, ``reviewed_at``,
  ``review_note`` <= 500, required on a rejection) and ``version``;
- at most one ``approved`` and at most one ``pending_approval`` row per
  product (partial unique indexes);
- a Sub Admin's row is never checked by its maker
  (``ck_product_commission_rates_checker_not_maker``, mirroring
  ``ck_contests_checker_not_maker``); a platform Admin's own entry is
  approved at once with themselves recorded as checker; unreviewed rows carry
  no checker; reviewed rows always do.
- trigger ``trg_product_commission_rates_transition``: the terms, product and
  maker never change after insert, and the status only moves
  ``pending_approval -> approved | rejected | withdrawn`` or
  ``approved -> superseded`` (every other status is final).

Access (``api_user``; RLS enabled and forced):

- SELECT: platform Admin; any Sub Admin; a loans-line Agent only for
  ``approved`` rows. Nobody else (Clients, real-estate Agents, Telecallers,
  Employees, line-scoped Admins, anonymous) reads any row.
- INSERT: a Sub Admin, as maker, only a ``pending_approval`` row with no
  checker or review fields.
- UPDATE (column grant: ``status``, ``version``, ``updated_at`` only): the
  maker Sub Admin on their own ``pending_approval`` row, only into
  ``pending_approval`` / ``withdrawn``, never with a checker.
- No DELETE grant. Platform Admin entries, approvals, rejections and
  supersession run in ``services/commission_rates.py`` on the bypass session
  after its own checks, like the contest checker moves.

Enum labels (``audit_action``: ``commission_rate_proposed``,
``commission_rate_set``, ``commission_rate_approved``,
``commission_rate_rejected``, ``commission_rate_withdrawn``;
``notification_type``: ``commission_rate_submitted``,
``commission_rate_reviewed``) need a direct connection; restart api and
scheduler after applying (ADR-0004). They stay after a downgrade.

Rollback drops the table with its policies, grants, trigger and function.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4a6c8d0f2b3"
down_revision: str | Sequence[str] | None = "d3f5b7c9e1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "product_commission_rates"
_FN = "enforce_product_commission_rate_transition"

_AUDIT_ACTIONS = (
    "commission_rate_proposed",
    "commission_rate_set",
    "commission_rate_approved",
    "commission_rate_rejected",
    "commission_rate_withdrawn",
)
_NOTIFICATION_TYPES = ("commission_rate_submitted", "commission_rate_reviewed")

_PLATFORM_ADMIN = (
    "(current_setting('app.platform_scope', true) = 'true' "
    "AND current_setting('app.role', true) = 'admin')"
)
_SUB_ADMIN = "(current_setting('app.role', true) = 'sub_admin')"
_LOANS_AGENT_APPROVED = (
    "(status = 'approved' "
    "AND current_setting('app.role', true) = 'agent' "
    "AND current_setting('app.business_line', true) = 'loans' "
    "AND coalesce(current_setting('app.agent_profile_uuid', true), '') <> '')"
)
_MAKER = (
    "(current_setting('app.role', true) = 'sub_admin' "
    "AND created_by_role = 'sub_admin' "
    "AND created_by_uuid::text = current_setting('app.auth_user_uuid', true))"
)

_MAX_FIXED_PAISE = 10_000_000_000


def upgrade() -> None:
    for value in _AUDIT_ACTIONS:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")
    for value in _NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("loan_type_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("percent_bps", sa.Integer(), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending_approval", nullable=False
        ),
        sa.Column("created_by_uuid", sa.UUID(), nullable=False),
        sa.Column("created_by_role", sa.String(length=16), nullable=False),
        sa.Column("checker_uuid", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
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
            "kind IN ('percent', 'fixed')", name=op.f("ck_product_commission_rates_kind")
        ),
        sa.CheckConstraint(
            "(kind = 'percent' AND percent_bps BETWEEN 1 AND 10000 AND amount_paise IS NULL) "
            f"OR (kind = 'fixed' AND amount_paise BETWEEN 1 AND {_MAX_FIXED_PAISE} "
            "AND percent_bps IS NULL)",
            name=op.f("ck_product_commission_rates_amount_shape"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(btrim(note)) BETWEEN 1 AND 280",
            name=op.f("ck_product_commission_rates_note_length"),
        ),
        sa.CheckConstraint(
            "review_note IS NULL OR char_length(btrim(review_note)) BETWEEN 1 AND 500",
            name=op.f("ck_product_commission_rates_review_note_length"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'approved', 'rejected', 'superseded', 'withdrawn')",
            name=op.f("ck_product_commission_rates_status"),
        ),
        sa.CheckConstraint(
            "created_by_role IN ('admin', 'sub_admin')",
            name=op.f("ck_product_commission_rates_created_by_role"),
        ),
        sa.CheckConstraint(
            "created_by_role <> 'sub_admin' OR checker_uuid IS NULL "
            "OR checker_uuid <> created_by_uuid",
            name=op.f("ck_product_commission_rates_checker_not_maker"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'rejected', 'superseded') "
            "OR (checker_uuid IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_product_commission_rates_reviewed_has_checker"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('pending_approval', 'withdrawn') "
            "OR (checker_uuid IS NULL AND reviewed_at IS NULL AND review_note IS NULL)",
            name=op.f("ck_product_commission_rates_unreviewed_has_no_checker"),
        ),
        sa.CheckConstraint(
            "created_by_role <> 'admin' OR status IN ('approved', 'superseded')",
            name=op.f("ck_product_commission_rates_admin_entry_approved"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR review_note IS NOT NULL",
            name=op.f("ck_product_commission_rates_rejection_has_note"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_product_commission_rates_version")),
        sa.ForeignKeyConstraint(
            ["loan_type_id"],
            ["loan_types.id"],
            ondelete="CASCADE",
            name=op.f("fk_product_commission_rates_loan_type_id_loan_types"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_uuid"],
            ["auth_users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_product_commission_rates_created_by_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["checker_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_product_commission_rates_checker_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_commission_rates")),
    )
    op.create_index(
        "uq_product_commission_rates_one_approved",
        _TABLE,
        ["loan_type_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_index(
        "uq_product_commission_rates_one_pending",
        _TABLE,
        ["loan_type_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending_approval'"),
    )
    op.create_index(
        "ix_product_commission_rates_loan_type_created",
        _TABLE,
        ["loan_type_id", "created_at"],
    )

    op.execute(
        f"""
        CREATE FUNCTION {_FN}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        BEGIN
            IF NEW.loan_type_id IS DISTINCT FROM OLD.loan_type_id
               OR NEW.kind IS DISTINCT FROM OLD.kind
               OR NEW.percent_bps IS DISTINCT FROM OLD.percent_bps
               OR NEW.amount_paise IS DISTINCT FROM OLD.amount_paise
               OR NEW.note IS DISTINCT FROM OLD.note
               OR NEW.created_by_uuid IS DISTINCT FROM OLD.created_by_uuid
               OR NEW.created_by_role IS DISTINCT FROM OLD.created_by_role
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'a commission rate''s terms and maker never change'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'pending_approval'
                    AND NEW.status IN ('approved', 'rejected', 'withdrawn'))
                OR (OLD.status = 'approved' AND NEW.status = 'superseded')
            ) THEN
                RAISE EXCEPTION 'commission rate status cannot move from % to %',
                    OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FN}() FROM PUBLIC")
    op.execute(
        f"""
        CREATE TRIGGER trg_product_commission_rates_transition
        BEFORE UPDATE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FN}()
        """
    )

    op.execute(f"GRANT SELECT, INSERT ON {_TABLE} TO api_user")
    op.execute(f"GRANT UPDATE (status, version, updated_at) ON {_TABLE} TO api_user")
    op.execute("ALTER TABLE product_commission_rates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_commission_rates FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY product_commission_rates_select ON {_TABLE}
        FOR SELECT
        USING ({_PLATFORM_ADMIN} OR {_SUB_ADMIN} OR {_LOANS_AGENT_APPROVED})
        """
    )
    op.execute(
        f"""
        CREATE POLICY product_commission_rates_insert ON {_TABLE}
        FOR INSERT
        WITH CHECK (
            {_MAKER}
            AND status = 'pending_approval'
            AND checker_uuid IS NULL
            AND reviewed_at IS NULL
            AND review_note IS NULL
            AND version = 1
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY product_commission_rates_update ON {_TABLE}
        FOR UPDATE
        USING ({_MAKER} AND status = 'pending_approval')
        WITH CHECK (
            {_MAKER}
            AND status IN ('pending_approval', 'withdrawn')
            AND checker_uuid IS NULL
        )
        """
    )


def downgrade() -> None:
    for policy in (
        "product_commission_rates_update",
        "product_commission_rates_insert",
        "product_commission_rates_select",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {_TABLE}")
    op.execute(f"REVOKE ALL PRIVILEGES ON {_TABLE} FROM api_user")
    op.execute(f"DROP TRIGGER IF EXISTS trg_product_commission_rates_transition ON {_TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {_FN}()")
    op.drop_index("ix_product_commission_rates_loan_type_created", table_name=_TABLE)
    op.drop_index("uq_product_commission_rates_one_pending", table_name=_TABLE)
    op.drop_index("uq_product_commission_rates_one_approved", table_name=_TABLE)
    op.drop_table(_TABLE)
    # Enum labels stay: PostgreSQL has no DROP VALUE (see module docstring).
