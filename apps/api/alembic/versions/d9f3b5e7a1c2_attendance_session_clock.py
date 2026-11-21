"""Store session-based clock calculations without changing historical rows."""

import sqlalchemy as sa

from alembic import op

revision = "d9f3b5e7a1c2"
down_revision = "b8d2f4a6c0e1"
branch_labels = None
depends_on = None

_ATTENDANCE_TABLES = ("attendance_days", "attendance_requests")
_PLATFORM_ADMIN = (
    "(current_setting('app.role', true) = 'admin' "
    "AND current_setting('app.platform_scope', true) = 'true')"
)


def _replace_roster(include_sub_admins: bool) -> None:
    roles = "'telecaller', 'employee'"
    if include_sub_admins:
        roles += ", 'sub_admin'"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION attendance_roster(team_id uuid)
        RETURNS TABLE (staff_profile_id uuid, name text, staff_code text, role text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT p.id, concat_ws(' ', u.first_name, u.last_name), p.staff_code::text, p.role::text
            FROM public.staff_profiles p
            JOIN public.auth_users u ON u.id = p.auth_user_uuid
            WHERE p.role::text IN ({roles})
            AND p.status::text = 'active' AND u.status::text = 'active'
            AND ({_PLATFORM_ADMIN} OR public.team_manager_reaches(p.id, NULL))
            AND (team_id IS NULL OR EXISTS (
                SELECT 1 FROM public.staff_team_members m
                JOIN public.staff_teams t ON t.id = m.team_uuid
                WHERE m.staff_profile_uuid = p.id AND t.id = team_id AND t.archived_at IS NULL
                AND ({_PLATFORM_ADMIN} OR t.manager_staff_profile_uuid::text =
                     current_setting('app.staff_profile_uuid', true))
            ))
        $$
        """
    )


def upgrade() -> None:
    _replace_roster(include_sub_admins=True)
    op.add_column(
        "attendance_policies",
        sa.Column("session_clock", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("attendance_days", sa.Column("system_check_out", sa.DateTime(timezone=True)))
    op.add_column("attendance_days", sa.Column("calendar_status", sa.String(12)))
    op.add_column("attendance_days", sa.Column("morning_covered", sa.Boolean()))
    op.add_column("attendance_days", sa.Column("afternoon_covered", sa.Boolean()))
    op.add_column(
        "attendance_days",
        sa.Column("early_exit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("attendance_days", sa.Column("uncovered_units", sa.SmallInteger()))
    op.add_column("attendance_days", sa.Column("lop_units", sa.SmallInteger()))
    op.add_column("attendance_requests", sa.Column("business_line", sa.String(12)))
    op.add_column(
        "attendance_requests",
        sa.Column("two_stage", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        ALTER POLICY attendance_requests_read ON attendance_requests
        USING (public.attendance_can_read(staff_profile_id) AND (
            business_line IS NULL
            OR staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
            OR (current_setting('app.role', true) = 'admin'
                AND current_setting('app.platform_scope', true) = 'true')
            OR public.team_manager_reaches(staff_profile_id, business_line)
        ))
        """
    )
    for table in _ATTENDANCE_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_sub_admin_self ON {table} FOR SELECT TO api_user
            USING (
                current_setting('app.role', true) = 'sub_admin'
                AND staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
                AND EXISTS (
                    SELECT 1 FROM public.staff_profiles p
                    WHERE p.id = staff_profile_id
                      AND p.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                      AND p.role::text = 'sub_admin' AND p.status::text = 'active'
                )
            )
            """
        )
    op.create_check_constraint(
        "attendance_day_session_measurements",
        "attendance_days",
        "(uncovered_units IS NULL OR uncovered_units BETWEEN 0 AND 4) "
        "AND (lop_units IS NULL OR lop_units BETWEEN 0 AND 4) "
        "AND (calendar_status IS NULL OR calendar_status IN ('absent','holiday','week_off')) "
        "AND (system_check_out IS NULL OR original_check_in IS NOT NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT 1 FROM attendance_policies WHERE session_clock LIMIT 1")):
        raise RuntimeError("The session clock is configured. Keep its policy and records.")
    _replace_roster(include_sub_admins=False)
    for table in _ATTENDANCE_TABLES:
        op.execute(f"DROP POLICY {table}_sub_admin_self ON {table}")
    op.execute(
        "ALTER POLICY attendance_requests_read ON attendance_requests "
        "USING (public.attendance_can_read(staff_profile_id))"
    )
    op.drop_column("attendance_requests", "two_stage")
    op.drop_column("attendance_requests", "business_line")
    op.drop_constraint("attendance_day_session_measurements", "attendance_days", type_="check")
    for column in (
        "system_check_out",
        "calendar_status",
        "morning_covered",
        "afternoon_covered",
        "early_exit",
        "uncovered_units",
        "lop_units",
    ):
        op.drop_column("attendance_days", column)
    op.drop_column("attendance_policies", "session_clock")
