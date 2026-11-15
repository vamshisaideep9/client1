"""Add the Under review and two agreement stages to the loan journey.

Revision ID: a7c9e1b3d5f2
Revises: f3a5c7e9b1d2

Client request (2026-11-15): after "Submitted to bank" comes "Under review";
"Sanctioned" is shown as "Approved"; after it come "Agreement collected" and
"Agreement submitted to bank", then "Disbursed". Only the three new labels are
added to the ``loan_status`` enum, each placed after its predecessor so enum
ordering follows the journey. The stored value ``sanctioned`` is unchanged
(only its display label changes), so existing rows, sanction terms, history
and reports need no rewrite.

NOTE: enum DDL needs a direct connection (not pgBouncer), and connections
prepared before this runs will not know the new labels: restart api and
scheduler after applying, as for every additive enum migration (ADR-0004).

Rollback: Postgres has no DROP VALUE for an enum; downgrade is a no-op and
the labels are left unused, matching every other additive enum value here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: str | Sequence[str] | None = "f3a5c7e9b1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (new value, existing value it follows)
_NEW_VALUES = (
    ("under_review", "submitted_to_bank"),
    ("agreement_collected", "sanctioned"),
    ("agreement_submitted_to_bank", "agreement_collected"),
)


def upgrade() -> None:
    for value, after in _NEW_VALUES:
        op.execute(f"ALTER TYPE loan_status ADD VALUE IF NOT EXISTS '{value}' AFTER '{after}'")


def downgrade() -> None:
    pass
