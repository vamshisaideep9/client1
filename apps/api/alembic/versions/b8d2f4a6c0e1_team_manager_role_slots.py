"""Allow one live team per manager, business line, and member role."""

import sqlalchemy as sa

from alembic import op

revision = "b8d2f4a6c0e1"
down_revision = "a5c7e9b1d3f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_staff_teams_live_manager_line_role",
        "staff_teams",
        ["manager_staff_profile_uuid", "business_line", "member_role"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_index("uq_staff_teams_live_manager_line", table_name="staff_teams")


def downgrade() -> None:
    # Creating the stricter index first preserves existing assignments if two
    # active teams would prevent rollback.
    op.create_index(
        "uq_staff_teams_live_manager_line",
        "staff_teams",
        ["manager_staff_profile_uuid", "business_line"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_index("uq_staff_teams_live_manager_line_role", table_name="staff_teams")
