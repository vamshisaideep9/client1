"""Track public chatbot inquiries independently of their lead."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "a127c49e3db8"
down_revision = "c5e7a9b1d3f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_inquiries",
        sa.Column("reference", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("leads.id", ondelete="CASCADE")),
        sa.Column("service", sa.String(120), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("name", sa.String(100)),
        sa.Column("location", sa.String(120), nullable=False),
        sa.Column("preferences", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_chat_inquiries_lead_id", "chat_inquiries", ["lead_id"])
    op.execute("ALTER TABLE chat_inquiries ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON chat_inquiries FROM PUBLIC, api_user")
    op.execute(
        "GRANT SELECT (reference, lead_id, service, action, name, location, "
        "preferences, created_at)"
        " ON chat_inquiries TO api_user"
    )
    op.execute("""
        CREATE POLICY chat_inquiries_read ON chat_inquiries FOR SELECT TO api_user
        USING (
            EXISTS (
                SELECT 1 FROM public.leads AS lead WHERE lead.id = chat_inquiries.lead_id
                AND (
                    (
                        current_setting('app.role', true) = 'admin'
                        AND current_setting('app.platform_scope', true) = 'true'
                    )
                    OR (
                        current_setting('app.role', true) = 'telecaller'
                        AND lead.business_line::text = current_setting('app.business_line', true)
                        AND lead.assigned_telecaller_profile_uuid::text =
                            current_setting('app.staff_profile_uuid', true)
                    )
                )
            )
        )
    """)
    op.execute("""
        CREATE FUNCTION erase_account_chat_inquiries(target uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            IF (
                target::text = current_setting('app.auth_user_uuid', true)
                OR (
                    current_setting('app.role', true) = 'admin'
                    AND current_setting('app.platform_scope', true) = 'true'
                )
            ) IS NOT TRUE THEN
                RAISE EXCEPTION 'inquiry erasure is not authorized' USING ERRCODE = '42501';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(account.mobile, 0))
                FROM public.auth_users AS account WHERE account.id = target;
            DELETE FROM public.chat_inquiries AS inquiry USING public.leads AS lead
            WHERE inquiry.lead_id = lead.id AND (
                lead.mobile = (SELECT mobile FROM public.auth_users WHERE id = target)
                OR lead.client_profile_uuid IN (
                    SELECT id FROM public.client_profiles WHERE auth_user_uuid = target
                )
            );
        END
        $$;
    """)
    op.execute("REVOKE ALL ON FUNCTION erase_account_chat_inquiries(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION erase_account_chat_inquiries(uuid) TO api_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION erase_account_chat_inquiries(uuid)")
    op.drop_table("chat_inquiries")
