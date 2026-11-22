"""Record closed attendance totals as immutable revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c5e7a9b1d3f6"
down_revision = "c5e7a9b1d3f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_month_revisions",
        sa.Column("month", sa.Date(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("totals", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("extract(day from month) = 1", name="attendance_close_month_start"),
        sa.CheckConstraint("version > 0", name="attendance_close_version"),
    )
    op.create_index(
        "uq_attendance_month_closed",
        "attendance_month_revisions",
        ["month"],
        unique=True,
        postgresql_where=sa.text("reopened_at IS NULL"),
    )
    op.execute("GRANT SELECT ON attendance_month_revisions TO api_user")
    op.execute("ALTER TABLE attendance_month_revisions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY attendance_month_admin_read ON attendance_month_revisions
        FOR SELECT TO api_user
        USING (current_setting('app.role', true) = 'admin'
            AND current_setting('app.platform_scope', true) = 'true')
    """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM attendance_month_revisions)")):
        raise RuntimeError("Rollback would discard closed attendance revisions.")
    op.drop_table("attendance_month_revisions")
