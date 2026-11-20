"""Remember a lead's last Telecaller and when it was last resubmitted (CS-028).

Revision ID: c2e4a6b8d0f1
Revises: b9e1a3c5d7f0

2026-11-19 product decision (CS-028, batch 2 "Agent leads"): a lead the
originating Agent resubmits after its 30-day window goes back to the
Telecaller who last held it when that Telecaller is still eligible, and every
lead list can show how often (and when) a lead was resubmitted.

New ``leads`` columns:

- ``last_telecaller_profile_uuid`` (FK ``staff_profiles``, ``ON DELETE SET
  NULL``): the Telecaller whose assignment was most recently cleared — by the
  expiry job, the stale-assignee repair in the retry job, or an Admin
  release. Written in the same statement / transaction that clears the
  assignment. ``resubmit_agent_lead`` prefers this Telecaller.
- ``last_resubmitted_at`` (timestamptz): set by ``resubmit_agent_lead``.

Database backstop, trigger ``trg_leads_last_telecaller_guard`` (``BEFORE
INSERT OR UPDATE OF`` the two columns), fixed search path, invoker rights:

- a new lead carries neither value;
- ``last_telecaller_profile_uuid`` may only become the row's previous assignee
  in the same update that clears the assignment (or NULL, which the FK's
  ``SET NULL`` needs). No path can point it at an arbitrary Telecaller.
- ``last_resubmitted_at`` may only change together with a
  ``resubmit_count`` increment, i.e. on the resubmission transition that
  ``enforce_agent_lead_expiry_immutable`` already guards.

Access: ``api_user`` already holds the table-wide UPDATE grant on ``leads``
and the existing RLS policies decide which rows a session may update; the
trigger above constrains these two columns for every session, including the
owner/bypass session the jobs and lead services use. No grant or policy
change. Existing rows start NULL (no backfill: the previous holder of an
already-released lead is only in the audit log).

Rollback drops the trigger, its function, the index and both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2e4a6b8d0f1"
down_revision: str | Sequence[str] | None = "b9e1a3c5d7f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN = "enforce_lead_last_telecaller"
_TRIGGER = "trg_leads_last_telecaller_guard"


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "last_telecaller_profile_uuid",
            sa.UUID(),
            sa.ForeignKey(
                "staff_profiles.id",
                ondelete="SET NULL",
                name=op.f("fk_leads_last_telecaller_profile_uuid_staff_profiles"),
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "leads",
        sa.Column("last_resubmitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_leads_last_telecaller_profile_uuid",
        "leads",
        ["last_telecaller_profile_uuid"],
        postgresql_where=sa.text("last_telecaller_profile_uuid IS NOT NULL"),
    )
    op.execute(
        f"""
        CREATE FUNCTION {_FN}() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.last_telecaller_profile_uuid IS NOT NULL
                   OR NEW.last_resubmitted_at IS NOT NULL THEN
                    RAISE EXCEPTION 'a new lead has no previous Telecaller or resubmission'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.last_telecaller_profile_uuid IS DISTINCT FROM OLD.last_telecaller_profile_uuid
               AND NEW.last_telecaller_profile_uuid IS NOT NULL
               AND NOT (
                   OLD.assigned_telecaller_profile_uuid IS NOT NULL
                   AND NEW.assigned_telecaller_profile_uuid IS NULL
                   AND NEW.last_telecaller_profile_uuid = OLD.assigned_telecaller_profile_uuid
               ) THEN
                RAISE EXCEPTION
                    'last_telecaller_profile_uuid records only the assignee being cleared'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.last_resubmitted_at IS DISTINCT FROM OLD.last_resubmitted_at
               AND NEW.resubmit_count IS DISTINCT FROM OLD.resubmit_count + 1 THEN
                RAISE EXCEPTION 'last_resubmitted_at changes only on a resubmission'
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
        CREATE TRIGGER {_TRIGGER}
        BEFORE INSERT OR UPDATE OF last_telecaller_profile_uuid, last_resubmitted_at ON leads
        FOR EACH ROW EXECUTE FUNCTION {_FN}()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON leads")
    op.execute(f"DROP FUNCTION IF EXISTS {_FN}()")
    op.drop_index("ix_leads_last_telecaller_profile_uuid", table_name="leads")
    op.drop_column("leads", "last_resubmitted_at")
    op.drop_column("leads", "last_telecaller_profile_uuid")
