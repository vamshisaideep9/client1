"""Add the Agent bulk lead submit audit action (CS-028).

Revision ID: d3f5b7c9e1a2
Revises: c2e4a6b8d0f1

NOTE: Run directly against postgres:5432, NOT through pgBouncer, and follow
the rolling-restart procedure for connection-holding services (ADR-0004):
enum DDL needs a direct connection, and a pooled connection prepared before
this runs will not see the new label.

``POST /api/v1/agent/leads/bulk`` appends one ``agent_leads_bulk_submitted``
audit entry per real (non-dry-run) upload with row counts per outcome only.
``services/audit_log.py::record`` runs inside the caller's transaction, so
this label must land, and the api/scheduler restart, before the endpoint
ships (same ordering as ``9af869604ca2``).

Rollback: PostgreSQL has no DROP VALUE for an enum; downgrade is a no-op, as
for every additive enum value in this codebase.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3f5b7c9e1a2"
down_revision: str | Sequence[str] | None = "c2e4a6b8d0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'agent_leads_bulk_submitted'")


def downgrade() -> None:
    pass
