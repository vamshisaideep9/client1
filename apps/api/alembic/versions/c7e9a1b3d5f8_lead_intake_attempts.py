"""Record rejected lead introductions and referral sign-ups (CS-024).

Revision ID: c7e9a1b3d5f8
Revises: f1b3d5a7c9e2

2026-11-17 product decision (CS-024, batch D of the stakeholder feedback):
the Agent panel shows lead eligibility and the Client panel shows referral
eligibility as Duplicate / Not eligible / Eligible. Accepted rows derive their
eligibility from existing columns; rejected attempts were never stored, so
this table records them from release onward.

``lead_intake_attempts`` holds one row per rejected attempt:

- ``actor_type`` ``agent`` (an Agent introducing a lead; ``actor_uuid`` is the
  Agent profile) or ``referrer`` (the Client whose referral code was used;
  ``actor_uuid`` is their account). ``auth_user_uuid`` is always the owning
  account, so RLS and account erasure key on the identity;
- the number only as its last four digits and a keyed HMAC-SHA256
  fingerprint (``SECRET_KEY``, domain-separated). The raw number is never
  stored; without the key the fingerprint cannot be reversed by trying every
  mobile number;
- ``outcome`` ``duplicate`` or ``not_eligible`` and a short ``reason_code``
  (lower-case identifier only, never free text). Codes and their labels are
  defined once in ``app/services/eligibility.py``.

Access (``api_user``, RLS enabled and forced):

- SELECT for the owner only: a referrer row by its account; an Agent row by
  its account *and* the request's Agent profile. No staff role, Admin
  included, has a read policy: there is no Admin surface for these rows, so
  none is granted (least privilege; a later oversight view adds its own
  policy);
- no INSERT/UPDATE/DELETE grant. Rows are written by the lead-capture and
  referral services on the bypass session, outside the rejected transaction;
- account erasure (owner from any role, or a platform Admin) calls the
  confined SECURITY DEFINER ``erase_lead_intake_attempts(uuid)``, the same
  shape as ``erase_agent_payout_details``.

Rollback drops the function, policies, grants and table; recorded attempts
are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7e9a1b3d5f8"
down_revision: str | Sequence[str] | None = "f1b3d5a7c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "lead_intake_attempts"

_OWNER = """
    auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
    AND (
        actor_type = 'referrer'
        OR (
            actor_type = 'agent'
            AND current_setting('app.role', true) = 'agent'
            AND actor_uuid::text = current_setting('app.agent_profile_uuid', true)
        )
    )
"""


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_uuid", sa.UUID(), nullable=False),
        sa.Column("auth_user_uuid", sa.UUID(), nullable=False),
        sa.Column("mobile_last4", sa.String(length=4), nullable=False),
        sa.Column("mobile_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "business_line",
            postgresql.ENUM(
                "loans", "real_estate", "both", name="business_line_enum", create_type=False
            ),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('agent', 'referrer')",
            name=op.f("ck_lead_intake_attempts_actor_type"),
        ),
        # A referrer is identified by their account; only Agents carry a
        # separate profile id.
        sa.CheckConstraint(
            "actor_type = 'agent' OR actor_uuid = auth_user_uuid",
            name=op.f("ck_lead_intake_attempts_referrer_is_account"),
        ),
        sa.CheckConstraint(
            "outcome IN ('duplicate', 'not_eligible')",
            name=op.f("ck_lead_intake_attempts_outcome"),
        ),
        sa.CheckConstraint(
            "reason_code ~ '^[a-z][a-z_]{0,47}$'",
            name=op.f("ck_lead_intake_attempts_reason_code_format"),
        ),
        sa.CheckConstraint(
            "mobile_last4 ~ '^[0-9]{4}$'",
            name=op.f("ck_lead_intake_attempts_mobile_last4_format"),
        ),
        sa.CheckConstraint(
            "mobile_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_lead_intake_attempts_mobile_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "business_line IS NULL OR business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_lead_intake_attempts_business_line_operational"),
        ),
        sa.ForeignKeyConstraint(
            ["auth_user_uuid"],
            ["auth_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_lead_intake_attempts_auth_user_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_intake_attempts")),
    )
    op.create_index(
        "ix_lead_intake_attempts_actor_created",
        _TABLE,
        ["actor_type", "actor_uuid", sa.text("created_at DESC")],
    )
    op.create_index(op.f("ix_lead_intake_attempts_auth_user_uuid"), _TABLE, ["auth_user_uuid"])

    op.execute(f"GRANT SELECT ON {_TABLE} TO api_user")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {_TABLE}_select ON {_TABLE} FOR SELECT USING ({_OWNER})")
    # Account erasure runs as the owner from any role or as a platform Admin;
    # api_user has no DELETE grant, so it goes through this confined definer.
    op.execute(
        """
        CREATE FUNCTION erase_lead_intake_attempts(target_auth_user_uuid uuid)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            removed_count integer;
        BEGIN
            IF NOT (
                target_auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                OR (
                    current_setting('app.role', true) = 'admin'
                    AND current_setting('app.platform_scope', true) = 'true'
                )
            ) THEN
                RAISE EXCEPTION 'lead intake attempt erasure is not authorized'
                    USING ERRCODE = '42501';
            END IF;

            DELETE FROM public.lead_intake_attempts
            WHERE auth_user_uuid = target_auth_user_uuid;
            GET DIAGNOSTICS removed_count = ROW_COUNT;
            RETURN removed_count;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION erase_lead_intake_attempts(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION erase_lead_intake_attempts(uuid) TO api_user")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION erase_lead_intake_attempts(uuid) FROM api_user")
    op.execute("DROP FUNCTION IF EXISTS erase_lead_intake_attempts(uuid)")
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_select ON {_TABLE}")
    op.execute(f"REVOKE ALL PRIVILEGES ON {_TABLE} FROM api_user")
    op.drop_index(op.f("ix_lead_intake_attempts_auth_user_uuid"), table_name=_TABLE)
    op.drop_index("ix_lead_intake_attempts_actor_created", table_name=_TABLE)
    op.drop_table(_TABLE)
