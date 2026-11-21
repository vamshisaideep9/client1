"""Keep typed regularizations and approved day effects alongside original punches."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e1a3c5f7b9d2"
down_revision = "d9f3b5e7a1c2"
branch_labels = None
depends_on = None

_ORIGINAL_DETAILS = (
    "(kind = 'leave' AND leave_type IS NOT NULL AND requested_check_in IS NULL "
    "AND requested_check_out IS NULL AND (NOT half_day OR start_day = end_day)) OR "
    "(kind = 'correction' AND start_day = end_day AND leave_type IS NULL AND NOT half_day "
    "AND requested_check_in IS NOT NULL AND requested_check_out > requested_check_in "
    "AND requested_check_out IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column("attendance_requests", sa.Column("adjustment_type", sa.String(16)))
    op.add_column(
        "attendance_days",
        sa.Column("adjustments", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.drop_constraint("attendance_request_details", "attendance_requests", type_="check")
    op.create_check_constraint(
        "attendance_request_details",
        "attendance_requests",
        f"(adjustment_type IS NULL AND ({_ORIGINAL_DETAILS})) OR "
        "(kind = 'adjustment' AND two_stage AND leave_type IS NULL AND NOT half_day "
        "AND requested_check_in IS NULL AND requested_check_out IS NULL "
        "AND adjustment_type IS NOT NULL "
        "AND adjustment_type IN ('late_waiver','early_exit','on_duty','holiday_work','comp_off') "
        "AND ((adjustment_type = 'comp_off' AND start_day < end_day) OR "
        "(adjustment_type <> 'comp_off' AND start_day = end_day)))",
    )


def downgrade() -> None:
    op.drop_constraint("attendance_request_details", "attendance_requests", type_="check")
    op.create_check_constraint(
        "attendance_request_details", "attendance_requests", _ORIGINAL_DETAILS
    )
    op.drop_column("attendance_days", "adjustments")
    op.drop_column("attendance_requests", "adjustment_type")
