"""Contact changes, mandatory email and permanent contact history (CS-025).

Revision ID: d4f6a8c0e2b4
Revises: c7e9a1b3d5f8

2026-11-17 product decision (CS-025, batch E of the stakeholder feedback;
amends CS-005 and the support-only mobile change):

- every account needs an OTP-verified email (enforcement is switched on per
  environment with ``EMAIL_REQUIRED_ENFORCED`` once email delivery is proven);
- Clients, Agents and Admins change their own phone or email: password, a code
  to the current value, the new value, a code to the new value, then one
  atomic update. Phone and email are never changed in the same request;
- Telecallers, Employees and Sub Admins request a change (the new value is
  OTP-verified) and one platform Admin approves or rejects it;
- the old value is kept permanently in an Admin-only history and erased only
  with the account.

``contact_change_requests`` is the one state machine for all three journeys
(``kind`` = ``self_service`` / ``email_add`` / ``staff_request``). The raw new
value lives only while the row is active; a CHECK forbids it on every terminal
status, so a completed, rejected, cancelled or expired row can never keep it
(the same rule ``mobile_change_requests`` follows). The current value is never
copied: only its keyed fingerprint, to prove it did not change mid-flow. One
active row per account (partial unique index), so phone and email can never be
in flight together.

``contact_change_history`` is the permanent copy: field, old value, new value,
method, proof category and PII-free reference, approver and time. It is the
only place an old number or address survives a completed change.

Access (``api_user``, RLS enabled and forced on both tables):

- ``contact_change_requests``: SELECT for the owner or a platform Admin; no
  write grant. The contact-change service writes on the bypass session after
  its own actor checks, as ``services/mobile_change.py`` does;
- ``contact_change_history``: SELECT for a platform Admin only (the account
  holder cannot read their own history); no write grant;
- account erasure calls the confined SECURITY DEFINER
  ``erase_contact_change_data(uuid)``. It accepts the owner or a platform Admin
  and only for an account already marked ``soft_deleted`` in the same
  transaction, so the permanent history cannot be erased any other way.

Audit and notification enum labels are additive and stay after downgrade,
matching the repository's PostgreSQL enum policy. Rollback drops both tables
and the function; any recorded history is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f6a8c0e2b4"
down_revision: str | Sequence[str] | None = "c7e9a1b3d5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUESTS = "contact_change_requests"
_HISTORY = "contact_change_history"

_ADMIN = """
    current_setting('app.platform_scope', true) = 'true'
    AND current_setting('app.role', true) = 'admin'
"""
_OWNER = "auth_user_uuid::text = current_setting('app.auth_user_uuid', true)"

_ACTIVE = "('awaiting_current_otp', 'awaiting_new_value', 'awaiting_new_otp', 'pending_approval')"


def upgrade() -> None:
    for value in ("contact_changed", "contact_change_requested", "contact_change_rejected"):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")
    # Every Admin read of someone's permanent contact history is audited.
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'contact_history_viewed'")

    op.create_table(
        _REQUESTS,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("auth_user_uuid", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("field", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("new_value", sa.String(length=320), nullable=True),
        sa.Column("current_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_uuid", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "kind IN ('self_service', 'email_add', 'staff_request')",
            name=op.f("ck_contact_change_requests_kind"),
        ),
        sa.CheckConstraint(
            "field IN ('mobile', 'email')",
            name=op.f("ck_contact_change_requests_field"),
        ),
        sa.CheckConstraint(
            "kind <> 'email_add' OR field = 'email'",
            name=op.f("ck_contact_change_requests_email_add_is_email"),
        ),
        # Each journey has its own closed set of steps; a status from another
        # journey can never be written (no step skipping through the table).
        sa.CheckConstraint(
            "(kind = 'self_service' AND status IN ('awaiting_current_otp', "
            "'awaiting_new_value', 'awaiting_new_otp', 'completed', 'cancelled', 'expired')) "
            "OR (kind = 'email_add' AND status IN ('awaiting_new_otp', 'completed', "
            "'cancelled', 'expired')) "
            "OR (kind = 'staff_request' AND status IN ('awaiting_new_otp', "
            "'pending_approval', 'completed', 'rejected', 'cancelled', 'expired'))",
            name=op.f("ck_contact_change_requests_status_for_kind"),
        ),
        sa.CheckConstraint(
            f"status IN {_ACTIVE} OR new_value IS NULL",
            name=op.f("ck_contact_change_requests_terminal_has_no_value"),
        ),
        sa.CheckConstraint(
            "new_value IS NULL "
            "OR (field = 'mobile' AND new_value ~ '^\\+[1-9][0-9]{6,14}$') "
            "OR (field = 'email' AND new_value ~ '^[^@[:space:]]+@[^@[:space:]]+$' "
            "AND new_value = lower(new_value))",
            name=op.f("ck_contact_change_requests_new_value_format"),
        ),
        sa.CheckConstraint(
            "current_fingerprint IS NULL OR current_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_contact_change_requests_current_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "rejection_reason IS NULL OR status = 'rejected'",
            name=op.f("ck_contact_change_requests_reason_only_when_rejected"),
        ),
        sa.ForeignKeyConstraint(
            ["auth_user_uuid"],
            ["auth_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_contact_change_requests_auth_user_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contact_change_requests_decided_by_user_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_change_requests")),
    )
    op.create_index(
        op.f("ix_contact_change_requests_auth_user_uuid"), _REQUESTS, ["auth_user_uuid"]
    )
    op.create_index(
        "ix_contact_change_requests_status_created", _REQUESTS, ["status", "created_at"]
    )
    # One change in flight per account, of any kind and either field.
    op.create_index(
        "uq_contact_change_requests_active_account",
        _REQUESTS,
        ["auth_user_uuid"],
        unique=True,
        postgresql_where=sa.text(f"status IN {_ACTIVE}"),
    )

    op.create_table(
        _HISTORY,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("auth_user_uuid", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=8), nullable=False),
        sa.Column("old_value", sa.String(length=320), nullable=True),
        sa.Column("new_value", sa.String(length=320), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("proof_category", sa.String(length=32), nullable=True),
        sa.Column("proof_reference", sa.String(length=300), nullable=True),
        sa.Column("approved_by_user_uuid", sa.UUID(), nullable=True),
        sa.Column("request_uuid", sa.UUID(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field IN ('mobile', 'email')",
            name=op.f("ck_contact_change_history_field"),
        ),
        sa.CheckConstraint(
            "method IN ('self_service', 'email_added', 'admin_approved', 'lost_number_recovery')",
            name=op.f("ck_contact_change_history_method"),
        ),
        sa.CheckConstraint(
            "proof_category IS NULL OR proof_category ~ '^[a-z][a-z_]{0,31}$'",
            name=op.f("ck_contact_change_history_proof_category_format"),
        ),
        sa.ForeignKeyConstraint(
            ["auth_user_uuid"],
            ["auth_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_contact_change_history_auth_user_uuid_auth_users"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_uuid"],
            ["auth_users.id"],
            ondelete="SET NULL",
            name=op.f("fk_contact_change_history_approved_by_user_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_change_history")),
    )
    op.create_index(
        "ix_contact_change_history_account_changed",
        _HISTORY,
        ["auth_user_uuid", sa.text("changed_at DESC")],
    )

    op.execute(f"GRANT SELECT ON {_REQUESTS} TO api_user")
    op.execute(f"ALTER TABLE {_REQUESTS} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_REQUESTS} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_REQUESTS}_select ON {_REQUESTS} "
        f"FOR SELECT USING (({_ADMIN}) OR ({_OWNER}))"
    )

    op.execute(f"GRANT SELECT ON {_HISTORY} TO api_user")
    op.execute(f"ALTER TABLE {_HISTORY} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_HISTORY} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {_HISTORY}_select ON {_HISTORY} FOR SELECT USING ({_ADMIN})")

    # Account erasure only. api_user has no DELETE grant on either table; this
    # definer accepts the owner (self-deletion) or a platform Admin (account
    # removal), and only once the account row is already soft-deleted in the
    # calling transaction, so the permanent history has no other erase path.
    op.execute(
        """
        CREATE FUNCTION erase_contact_change_data(target_auth_user_uuid uuid)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            removed_requests integer;
            removed_history integer;
        BEGIN
            IF NOT (
                target_auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                OR (
                    current_setting('app.role', true) = 'admin'
                    AND current_setting('app.platform_scope', true) = 'true'
                )
            ) THEN
                RAISE EXCEPTION 'contact change erasure is not authorized'
                    USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.auth_users
                WHERE id = target_auth_user_uuid AND status = 'soft_deleted'
            ) THEN
                RAISE EXCEPTION 'contact change data is erased only with the account'
                    USING ERRCODE = '42501';
            END IF;

            DELETE FROM public.contact_change_requests
            WHERE auth_user_uuid = target_auth_user_uuid;
            GET DIAGNOSTICS removed_requests = ROW_COUNT;
            DELETE FROM public.contact_change_history
            WHERE auth_user_uuid = target_auth_user_uuid;
            GET DIAGNOSTICS removed_history = ROW_COUNT;
            RETURN removed_requests + removed_history;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION erase_contact_change_data(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION erase_contact_change_data(uuid) TO api_user")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION erase_contact_change_data(uuid) FROM api_user")
    op.execute("DROP FUNCTION IF EXISTS erase_contact_change_data(uuid)")
    op.execute(f"DROP POLICY IF EXISTS {_HISTORY}_select ON {_HISTORY}")
    op.execute(f"REVOKE ALL PRIVILEGES ON {_HISTORY} FROM api_user")
    op.drop_index("ix_contact_change_history_account_changed", table_name=_HISTORY)
    op.drop_table(_HISTORY)
    op.execute(f"DROP POLICY IF EXISTS {_REQUESTS}_select ON {_REQUESTS}")
    op.execute(f"REVOKE ALL PRIVILEGES ON {_REQUESTS} FROM api_user")
    op.drop_index("uq_contact_change_requests_active_account", table_name=_REQUESTS)
    op.drop_index("ix_contact_change_requests_status_created", table_name=_REQUESTS)
    op.drop_index(op.f("ix_contact_change_requests_auth_user_uuid"), table_name=_REQUESTS)
    op.drop_table(_REQUESTS)
