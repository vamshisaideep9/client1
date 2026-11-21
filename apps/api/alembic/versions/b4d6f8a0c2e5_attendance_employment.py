"""Add employment dates, business-line holidays and direct attendance review."""

import sqlalchemy as sa

from alembic import op

revision = "b4d6f8a0c2e5"
down_revision = "a3c5e7b9d1f4"
branch_labels = None
depends_on = None

_ADMIN = """current_setting('app.role', true) = 'admin'
    AND current_setting('app.platform_scope', true) = 'true'"""
_SELF = "staff_profile_id::text = current_setting('app.staff_profile_uuid', true)"


def _day_policy(legacy_unassigned: str) -> None:
    op.execute(f"""
        ALTER POLICY attendance_days_read ON attendance_days
        USING (public.attendance_can_read(staff_profile_id) AND (
            ({legacy_unassigned}) OR ({_SELF}) OR ({_ADMIN})
            OR (business_line IS NOT NULL
                AND public.team_manager_reaches(staff_profile_id, business_line))
        ))
    """)


def upgrade() -> None:
    op.create_table(
        "attendance_employment",
        sa.Column("staff_profile_id", sa.UUID(), primary_key=True),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date()),
        sa.Column("business_line", sa.String(12), nullable=False),
        sa.Column("reviewer_id", sa.UUID()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["staff_profile_id"], ["staff_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["staff_profiles.id"], ondelete="SET NULL"),
        sa.CheckConstraint("end_day >= start_day", name="attendance_employment_dates"),
        sa.CheckConstraint(
            "reviewer_id <> staff_profile_id", name="attendance_employment_reviewer"
        ),
        sa.CheckConstraint("version > 0", name="attendance_employment_version"),
        sa.CheckConstraint(
            "business_line IN ('loans', 'real_estate')", name="attendance_employment_line"
        ),
    )
    op.create_index("ix_attendance_employment_reviewer", "attendance_employment", ["reviewer_id"])
    op.create_table(
        "attendance_line_holidays",
        sa.Column("business_line", sa.String(12), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.CheckConstraint(
            "business_line IN ('loans', 'real_estate')", name="attendance_holiday_line"
        ),
    )
    for table in ("attendance_employment", "attendance_line_holidays"):
        op.execute(f"GRANT SELECT ON {table} TO api_user")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY attendance_employment_read ON attendance_employment FOR SELECT TO api_user
        USING (({_ADMIN}) OR ({_SELF}))
    """)
    op.execute(f"""
        CREATE POLICY attendance_line_holidays_read ON attendance_line_holidays
        FOR SELECT TO api_user
        USING (({_ADMIN}) OR business_line = current_setting('app.business_line', true) OR EXISTS (
            SELECT 1 FROM public.attendance_employment AS e
            WHERE e.staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
              AND e.business_line = attendance_line_holidays.business_line
        ))
    """)
    op.execute("""
        CREATE FUNCTION public.attendance_direct_reach(target_id uuid, target_line text)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT current_setting('app.role', true) = 'sub_admin'
            AND current_setting('app.team_review', true) = 'true'
            AND EXISTS (
                SELECT 1 FROM public.attendance_employment AS e
                JOIN public.staff_profiles AS reviewer ON reviewer.id = e.reviewer_id
                JOIN public.auth_users AS reviewer_user
                  ON reviewer_user.id = reviewer.auth_user_uuid
                JOIN public.staff_profiles AS target ON target.id = e.staff_profile_id
                JOIN public.auth_users AS target_user ON target_user.id = target.auth_user_uuid
                WHERE e.staff_profile_id = target_id
                  AND (target_line IS NULL OR target_line = e.business_line)
                  AND reviewer.id::text = current_setting('app.staff_profile_uuid', true)
                  AND reviewer.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                  AND reviewer.role::text = 'sub_admin' AND reviewer.scope::text = 'platform'
                  AND reviewer.status::text = 'active' AND reviewer_user.status::text = 'active'
                  AND target.role::text IN ('telecaller', 'employee', 'sub_admin')
                  AND target.status::text = 'active' AND target_user.status::text = 'active'
                  AND public.sub_admin_has_line('team_manager', 'review', e.business_line)
            )
        $$
    """)
    op.execute("""
        CREATE FUNCTION public.attendance_reporting_roster(selected_team uuid)
        RETURNS TABLE (staff_profile_id uuid, name text, staff_code text, role text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT * FROM public.attendance_roster(selected_team)
            UNION
            SELECT p.id, concat_ws(' ', u.first_name, u.last_name), p.staff_code::text, p.role::text
            FROM public.attendance_employment e
            JOIN public.staff_profiles p ON p.id = e.staff_profile_id
            JOIN public.auth_users u ON u.id = p.auth_user_uuid
            WHERE selected_team IS NULL AND public.attendance_direct_reach(p.id, NULL)
        $$
    """)
    for signature in ("attendance_direct_reach(uuid, text)", "attendance_reporting_roster(uuid)"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO api_user")
    for table in ("attendance_days", "attendance_requests"):
        stage = "two_stage AND " if table == "attendance_requests" else ""
        op.execute(f"""
            CREATE POLICY {table}_direct_read ON {table} FOR SELECT TO api_user
            USING ({stage}business_line IS NOT NULL
                AND public.attendance_direct_reach(staff_profile_id, business_line))
        """)
    _day_policy("calendar_status IS NULL AND business_line IS NULL")


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("attendance_employment", "attendance_line_holidays"):
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Rollback would discard saved attendance configuration.")
    for table in ("attendance_days", "attendance_requests"):
        op.execute(f"DROP POLICY {table}_direct_read ON {table}")
    _day_policy("calendar_status IS NULL")
    op.execute("DROP FUNCTION public.attendance_reporting_roster(uuid)")
    op.execute("DROP FUNCTION public.attendance_direct_reach(uuid, text)")
    op.drop_table("attendance_line_holidays")
    op.drop_table("attendance_employment")
