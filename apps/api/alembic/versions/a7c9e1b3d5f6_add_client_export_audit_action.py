"""add client-export AuditAction enum value

Revision ID: a7c9e1b3d5f6
Revises: b2d4f6a8c0e1
Create Date: 2026-11-16 00:00:00.000000

NOTE: Run directly against postgres:5432, NOT through pgBouncer, and follow the
rolling-restart procedure for connection-holding services (ADR-0004) — enum DDL
needs a direct connection, and any pooled connection prepared before this runs
will not see the new label.

Unblocks the admin client-roster CSV export (feature-status.md §3 #2 export
family): `services/reporting.py::export_client_rows` calls
`services/audit_log.py::record` with this action to record a bulk client-PII
download. Same ordering requirement as the precedents (`1dd0bc6bed88`,
`9af869604ca2`): `record()` runs INSIDE the caller's request transaction and
does not swallow a stale-enum failure, so this must land and the api/scheduler
restart before the client-export code ships.

Rollback: Postgres has no DROP VALUE for an enum; downgrade is a no-op (same as
every other additive enum value in this codebase).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c9e1b3d5f6"
down_revision: str | Sequence[str] | None = "b2d4f6a8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = ("client_export_downloaded",)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
