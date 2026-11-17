"""Add Agent-saved payout details (bank account / UPI ID), encrypted at rest.

Revision ID: a1b3d5f7c9e2
Revises: f8a0c2e4b6d1

2026-11-14 product decision: an Agent can save the bank account and/or UPI ID
their commission should be paid to. Until now the platform never stored raw
destinations (payouts keep only a masked hint), so this table is a new store of
financial PII and is deliberately narrow:

- Raw values exist only as AES-256-GCM blobs (``core/field_crypto.py``) bound
  to the row's Agent profile; the key lives in the runtime environment, never in
  the database. ``*_hint`` columns hold the masked display form.
- One row per Agent profile; at least one destination is required.
- ``auth_user_uuid`` is a denormalized owner so RLS and account erasure key on
  the identity, not only on the request's Agent profile.

Access (``api_user``, RLS enabled and forced):

- the owning Agent may SELECT/INSERT/UPDATE/DELETE their own row only;
- account erasure (owner from any role, or a platform Admin) calls the confined
  SECURITY DEFINER ``erase_agent_payout_details(uuid)``;
- no staff SELECT policy. Payout makers read a decrypted destination only via
  the guarded, audited service on the owner session, like the existing payout
  recipient search.

Four additive ``audit_action`` labels record Agent save/remove and payout-maker
reveals. Enum labels remain after downgrade.

Rollback drops the table, its policies and grants; saved destinations are lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b3d5f7c9e2"
down_revision: str | Sequence[str] | None = "f8a0c2e4b6d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_payout_details"

_OWNER_AGENT = """
    current_setting('app.role', true) = 'agent'
    AND auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
    AND agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true)
"""

_AUDIT_ACTIONS = (
    "agent_payout_details_updated",
    "agent_payout_details_deleted",
    "agent_payout_details_viewed",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for action in _AUDIT_ACTIONS:
            op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{action}'")

    op.create_table(
        _TABLE,
        sa.Column("agent_profile_uuid", sa.UUID(), nullable=False),
        sa.Column("auth_user_uuid", sa.UUID(), nullable=False),
        sa.Column("upi_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("upi_hint", sa.String(length=40), nullable=True),
        sa.Column("bank_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("bank_hint", sa.String(length=60), nullable=True),
        sa.Column("key_version", sa.SmallInteger(), nullable=False),
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
            "upi_ciphertext IS NOT NULL OR bank_ciphertext IS NOT NULL",
            name=op.f("ck_agent_payout_details_has_destination"),
        ),
        sa.CheckConstraint(
            "(upi_ciphertext IS NULL) = (upi_hint IS NULL)",
            name=op.f("ck_agent_payout_details_upi_hint_pairs"),
        ),
        sa.CheckConstraint(
            "(bank_ciphertext IS NULL) = (bank_hint IS NULL)",
            name=op.f("ck_agent_payout_details_bank_hint_pairs"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_profile_uuid"],
            ["agent_profiles.id"],
            ondelete="CASCADE",
            name=op.f("fk_agent_payout_details_agent_profile_uuid_agent_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["auth_user_uuid"],
            ["auth_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_agent_payout_details_auth_user_uuid_auth_users"),
        ),
        sa.PrimaryKeyConstraint("agent_profile_uuid", name=op.f("pk_agent_payout_details")),
    )
    op.create_index(op.f("ix_agent_payout_details_auth_user_uuid"), _TABLE, ["auth_user_uuid"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO api_user")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {_TABLE}_select ON {_TABLE} FOR SELECT USING ({_OWNER_AGENT})")
    op.execute(f"CREATE POLICY {_TABLE}_insert ON {_TABLE} FOR INSERT WITH CHECK ({_OWNER_AGENT})")
    op.execute(
        f"CREATE POLICY {_TABLE}_update ON {_TABLE} "
        f"FOR UPDATE USING ({_OWNER_AGENT}) WITH CHECK ({_OWNER_AGENT})"
    )
    op.execute(f"CREATE POLICY {_TABLE}_delete ON {_TABLE} FOR DELETE USING ({_OWNER_AGENT})")
    # Account erasure runs as the owner from any role or as a platform Admin,
    # neither of which can SELECT the row through RLS. Same confined
    # SECURITY DEFINER shape as erase_personalization_preference.
    op.execute(
        """
        CREATE FUNCTION erase_agent_payout_details(target_auth_user_uuid uuid)
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
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
                RAISE EXCEPTION 'agent payout details deletion is not authorized'
                    USING ERRCODE = '42501';
            END IF;

            DELETE FROM public.agent_payout_details
            WHERE auth_user_uuid = target_auth_user_uuid;
            GET DIAGNOSTICS removed_count = ROW_COUNT;
            RETURN removed_count > 0;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION erase_agent_payout_details(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION erase_agent_payout_details(uuid) TO api_user")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION erase_agent_payout_details(uuid) FROM api_user")
    op.execute("DROP FUNCTION IF EXISTS erase_agent_payout_details(uuid)")
    for suffix in ("delete", "update", "insert", "select"):
        op.execute(f"DROP POLICY IF EXISTS {_TABLE}_{suffix} ON {_TABLE}")
    op.execute(f"REVOKE ALL PRIVILEGES ON {_TABLE} FROM api_user")
    op.drop_index(op.f("ix_agent_payout_details_auth_user_uuid"), table_name=_TABLE)
    op.drop_table(_TABLE)
