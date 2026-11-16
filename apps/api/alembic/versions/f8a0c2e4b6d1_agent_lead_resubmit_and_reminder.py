"""Allow the original Agent to resubmit an expired lead; add a 7-day reminder.

Revision ID: f8a0c2e4b6d1
Revises: e7a9c1b3d5f8

2026-11-14 product amendment to FR-4.6. The fixed 30-day Agent window still
ends with the lead returning to the open Telecaller pool, but the Agent who
introduced the lead may now resubmit it for a fresh 30-day window while:

- the originating Agent is unchanged (no other Agent may restart the clock),
- the client has not registered (``client_profile_uuid IS NULL``), and
- the lead is not converted or closed.

``enforce_agent_lead_expiry_immutable`` keeps both expiry columns immutable
except for exactly that transition, which must also be requested explicitly by
the service through the transaction-local ``app.agent_lead_resubmit`` flag and
must increment ``resubmit_count``. ``enforce_agent_lead_expiry_no_reset`` is
unchanged: it fires only when Agent attribution *starts* on a row, so it still
stops any Agent from attributing a mobile whose Agent history has ended.

New columns:

- ``resubmit_count`` counts same-Agent resubmissions (audit/reporting).
- ``expiry_reminder_sent_at`` makes the 7-day reminder job idempotent per
  window; a resubmit clears it.

Enum labels (``agent_lead_expiry_reminder`` notification and
``agent_lead_resubmitted`` audit action) are additive and remain after
downgrade, like every earlier enum label.

Access: no grant or policy change. Resubmission runs in the leads service on
the owner session (same as Agent lead capture) after app-layer ownership checks.

Rollback refuses to discard resubmission history (any ``resubmit_count > 0``)
because the restored strict trigger could not represent it; otherwise it
restores the original function and drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8a0c2e4b6d1"
down_revision: str | Sequence[str] | None = "e7a9c1b3d5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_FN = "enforce_agent_lead_expiry_immutable"

_STRICT_CHECKS = """
            IF OLD.expires_at IS NOT NULL
               AND NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                RAISE EXCEPTION 'expires_at is immutable once set'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.agent_expired_at IS NOT NULL
               AND NEW.agent_expired_at IS DISTINCT FROM OLD.agent_expired_at THEN
                RAISE EXCEPTION 'agent_expired_at is immutable once set'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'agent_lead_expiry_reminder'"
        )
        op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'agent_lead_resubmitted'")

    op.add_column(
        "leads",
        sa.Column("resubmit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "leads",
        sa.Column("expiry_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_leads_resubmit_count_non_negative"), "leads", "resubmit_count >= 0"
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_IMMUTABLE_FN}() RETURNS trigger AS $$
        BEGIN
            -- Same-Agent resubmission (2026-11-14 amendment to FR-4.6). Every
            -- condition is required; anything else falls through to the
            -- original immutability checks below.
            IF coalesce(current_setting('app.agent_lead_resubmit', true), '') = 'on'
               AND OLD.agent_expired_at IS NOT NULL
               AND NEW.agent_expired_at IS NULL
               AND OLD.origin_agent_profile_uuid IS NOT NULL
               AND NEW.origin_agent_profile_uuid IS NOT DISTINCT FROM OLD.origin_agent_profile_uuid
               AND NEW.mobile IS NOT DISTINCT FROM OLD.mobile
               AND NEW.business_line IS NOT DISTINCT FROM OLD.business_line
               AND NEW.client_profile_uuid IS NULL
               AND NEW.status NOT IN ('converted', 'closed')
               AND NEW.expires_at IS NOT NULL
               AND NEW.expires_at > clock_timestamp()
               AND NEW.resubmit_count = OLD.resubmit_count + 1 THEN
                RETURN NEW;
            END IF;
{_STRICT_CHECKS}
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM leads WHERE resubmit_count > 0) THEN
            RAISE EXCEPTION 'cannot downgrade while resubmitted Agent leads exist';
          END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_IMMUTABLE_FN}() RETURNS trigger AS $$
        BEGIN
{_STRICT_CHECKS}
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.drop_constraint(op.f("ck_leads_resubmit_count_non_negative"), "leads", type_="check")
    op.drop_column("leads", "expiry_reminder_sent_at")
    op.drop_column("leads", "resubmit_count")
