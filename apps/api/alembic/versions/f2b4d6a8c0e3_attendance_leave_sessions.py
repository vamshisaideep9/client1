"""Record the actual session covered by each approved half-day request."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f2b4d6a8c0e3"
down_revision = "e1a3c5f7b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_days", sa.Column("business_line", sa.String(12)))
    op.execute(
        """
        ALTER POLICY attendance_days_read ON attendance_days
        USING (public.attendance_can_read(staff_profile_id) AND (
            calendar_status IS NULL
            OR staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
            OR (current_setting('app.role', true) = 'admin'
                AND current_setting('app.platform_scope', true) = 'true')
            OR (business_line IS NOT NULL
                AND public.team_manager_reaches(staff_profile_id, business_line))
        ))
        """
    )
    op.add_column("attendance_requests", sa.Column("leave_session", sa.String(9)))
    op.add_column(
        "attendance_days",
        sa.Column("leave_sessions", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_check_constraint(
        "attendance_leave_session",
        "attendance_requests",
        "leave_session IS NULL OR (kind = 'leave' AND half_day AND "
        "leave_session IN ('morning', 'afternoon'))",
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_session = sa.text(
        "SELECT 1 FROM attendance_requests WHERE leave_session IS NOT NULL LIMIT 1"
    )
    has_work_line = sa.text("SELECT 1 FROM attendance_days WHERE business_line IS NOT NULL LIMIT 1")
    if connection.scalar(has_session) or connection.scalar(has_work_line):
        raise RuntimeError("Rollback would discard recorded leave sessions or work lines.")
    op.drop_constraint("attendance_leave_session", "attendance_requests", type_="check")
    op.drop_column("attendance_days", "leave_sessions")
    op.drop_column("attendance_requests", "leave_session")
    op.execute(
        "ALTER POLICY attendance_days_read ON attendance_days "
        "USING (public.attendance_can_read(staff_profile_id))"
    )
    op.drop_column("attendance_days", "business_line")
