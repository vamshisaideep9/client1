"""Add an optional developer / builder name to properties and submissions.

Revision ID: b7d9f1a3c5e2
Revises: a4c6e8f0b2d4

Lets buyers find every listing by one developer (for example all "My Home"
projects across Hyderabad localities) through the catalog search and the
Developer filter, instead of relying on the brand appearing in each title.

Additive and nullable: existing rows keep NULL and remain valid; owners and
Admin can backfill through the normal edit/correction flow. Approval copies the
value from the submission to the published property with the other facts.

RLS: not touched. `properties_rls` and the `property_submissions` policies are
row-level predicates with no column dimension. GRANT: not touched either; the
existing `GRANT SELECT ON properties`, `GRANT UPDATE ON properties` and
`GRANT SELECT, INSERT ON property_submissions` are table-wide and already cover
columns added later. No new table, so no rls-exempt marker is needed.

The lower(developer_name) index supports case-insensitive developer lookups on
the published catalog without a sequential scan as it grows.

Rollback: downgrade() drops the index and both columns, discarding any authored
developer names. Revert the app image first, then `alembic downgrade -1`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d9f1a3c5e2"
down_revision: str | None = "a4c6e8f0b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("developer_name", sa.String(120), nullable=True))
    op.add_column(
        "property_submissions", sa.Column("developer_name", sa.String(120), nullable=True)
    )
    op.execute(
        "CREATE INDEX ix_properties_developer_name_lower "
        "ON properties (lower(developer_name)) WHERE developer_name IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_properties_developer_name_lower")
    op.drop_column("property_submissions", "developer_name")
    op.drop_column("properties", "developer_name")
