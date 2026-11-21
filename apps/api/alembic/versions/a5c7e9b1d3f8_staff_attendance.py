"""Staff attendance, approved leave and versioned attendance policy."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a5c7e9b1d3f8"
down_revision = "f4c6a8e0b2d3"
branch_labels = None
depends_on = None

ADMIN = (
    "(current_setting('app.role', true) = 'admin' "
    "AND current_setting('app.platform_scope', true) = 'true')"
)
STAFF = "(current_setting('app.role', true) IN ('telecaller', 'employee'))"
MANAGER = "(current_setting('app.role', true) = 'sub_admin')"


def _read_policy(table: str, expression: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT ON {table} TO api_user")
    op.execute(f"CREATE POLICY {table}_read ON {table} FOR SELECT TO api_user USING ({expression})")


def upgrade() -> None:
    op.create_table(
        "attendance_policies",
        sa.Column("version", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("shift_start_minute", sa.Integer(), nullable=False),
        sa.Column("shift_minutes", sa.Integer(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False),
        sa.Column("half_day_minutes", sa.Integer(), nullable=False),
        sa.Column("full_day_minutes", sa.Integer(), nullable=False),
        sa.Column("weekly_off", postgresql.JSONB(), nullable=False),
        sa.Column("leave_quotas", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.UUID(), sa.ForeignKey("auth_users.id", ondelete="SET NULL")),
        sa.CheckConstraint(
            "shift_start_minute BETWEEN 0 AND 1439 AND shift_minutes BETWEEN 1 AND 1440 "
            "AND grace_minutes BETWEEN 0 AND shift_minutes "
            "AND half_day_minutes BETWEEN 1 AND full_day_minutes "
            "AND full_day_minutes <= shift_minutes",
            name="attendance_policy_thresholds",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(weekly_off) = 'array' AND jsonb_array_length(weekly_off) < 7 "
            "AND jsonb_typeof(leave_quotas) = 'object'",
            name="attendance_policy_config",
        ),
    )
    op.create_table(
        "attendance_holidays",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name="attendance_holiday_name"),
    )
    op.create_table(
        "attendance_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "staff_profile_id",
            sa.UUID(),
            sa.ForeignKey("staff_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requester_id", sa.UUID(), sa.ForeignKey("auth_users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("leave_type", sa.String(32)),
        sa.Column("half_day", sa.Boolean(), nullable=False),
        sa.Column("requested_check_in", sa.DateTime(timezone=True)),
        sa.Column("requested_check_out", sa.DateTime(timezone=True)),
        sa.Column("approved_units", postgresql.JSONB(), nullable=False),
        sa.Column("correction_before", postgresql.JSONB()),
        sa.Column("decisions", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "end_day - start_day BETWEEN 0 AND 30 AND length(btrim(reason)) BETWEEN 3 AND 500 "
            "AND status IN ('pending','approved','rejected','cancelled')",
            name="attendance_request_period_status",
        ),
        sa.CheckConstraint(
            "(kind = 'leave' AND leave_type IS NOT NULL AND requested_check_in IS NULL "
            "AND requested_check_out IS NULL AND (NOT half_day OR start_day = end_day)) OR "
            "(kind = 'correction' AND start_day = end_day AND leave_type IS NULL AND NOT half_day "
            "AND requested_check_in IS NOT NULL AND requested_check_out > requested_check_in "
            "AND requested_check_out IS NOT NULL)",
            name="attendance_request_details",
        ),
    )
    op.create_index(
        "ix_attendance_requests_staff_period",
        "attendance_requests",
        ["staff_profile_id", "kind", "status", "start_day", "end_day"],
    )
    op.create_table(
        "attendance_days",
        sa.Column(
            "staff_profile_id",
            sa.UUID(),
            sa.ForeignKey("staff_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column(
            "policy_version",
            sa.Integer(),
            sa.ForeignKey("attendance_policies.version"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("original_check_in", sa.DateTime(timezone=True)),
        sa.Column("original_check_out", sa.DateTime(timezone=True)),
        sa.Column("check_in", sa.DateTime(timezone=True)),
        sa.Column("check_out", sa.DateTime(timezone=True)),
        sa.Column("worked_minutes", sa.Integer(), nullable=False),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column(
            "leave_request_id",
            sa.UUID(),
            sa.ForeignKey("attendance_requests.id", ondelete="SET NULL"),
        ),
        sa.Column("leave_units", sa.Integer(), nullable=False),
        sa.Column(
            "correction_request_id",
            sa.UUID(),
            sa.ForeignKey("attendance_requests.id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "worked_minutes BETWEEN 0 AND 2880 AND leave_units BETWEEN 0 AND 2 "
            "AND (leave_units = 0 OR leave_request_id IS NOT NULL) "
            "AND (check_out IS NULL OR (check_in IS NOT NULL AND check_out >= check_in)) "
            "AND (original_check_out IS NULL OR (original_check_in IS NOT NULL "
            "AND original_check_out >= original_check_in))",
            name="attendance_day_measurements",
        ),
        sa.CheckConstraint(
            "status IN ('checked_in','present','half_day','short_day','absent','missing_checkout',"
            "'on_leave','holiday','week_off') "
            "AND source IN ('clock','rollover','leave','correction')",
            name="attendance_day_status_source",
        ),
    )
    op.create_index("ix_attendance_days_by_date", "attendance_days", ["day", "staff_profile_id"])
    op.create_index(
        "ix_attendance_days_open",
        "attendance_days",
        ["staff_profile_id"],
        unique=True,
        postgresql_where=sa.text("status = 'checked_in'"),
    )
    op.create_table(
        "attendance_rollover_state",
        sa.Column(
            "staff_profile_id",
            sa.UUID(),
            sa.ForeignKey("staff_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("through_day", sa.Date(), nullable=False),
    )
    _read_policy("attendance_policies", f"{ADMIN} OR {STAFF} OR {MANAGER}")
    _read_policy("attendance_holidays", f"{ADMIN} OR {STAFF} OR {MANAGER}")
    op.execute(
        f"""
        CREATE FUNCTION attendance_can_read(profile_id uuid)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT {ADMIN} OR EXISTS (
                SELECT 1 FROM public.staff_profiles p
                JOIN public.auth_users u ON u.id = p.auth_user_uuid
                WHERE p.id = profile_id
                AND p.status::text = 'active' AND u.status::text = 'active'
                AND p.role::text IN ('telecaller', 'employee')
                AND ((p.role::text = current_setting('app.role', true)
                    AND p.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                    AND p.id::text = current_setting('app.staff_profile_uuid', true))
                    OR public.team_manager_reaches(p.id, NULL))
            )
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION attendance_can_read(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION attendance_can_read(uuid) TO api_user")
    _read_policy("attendance_requests", "public.attendance_can_read(staff_profile_id)")
    _read_policy("attendance_days", "public.attendance_can_read(staff_profile_id)")
    op.execute("ALTER TABLE attendance_rollover_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE attendance_rollover_state FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY attendance_rollover_deny ON attendance_rollover_state USING (false)")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'attendance_updated'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'attendance_exported'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'attendance_request_updated'")
    op.execute(
        f"""
        CREATE FUNCTION attendance_roster(team_id uuid)
        RETURNS TABLE (staff_profile_id uuid, name text, staff_code text, role text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT p.id, concat_ws(' ', u.first_name, u.last_name), p.staff_code::text, p.role::text
              FROM public.staff_profiles p
              JOIN public.auth_users u ON u.id = p.auth_user_uuid
             WHERE p.role::text IN ('telecaller', 'employee') AND p.status::text = 'active'
               AND u.status::text = 'active'
               AND ({ADMIN} OR public.team_manager_reaches(p.id, NULL))
               AND (team_id IS NULL OR EXISTS (
                   SELECT 1 FROM public.staff_team_members m
                     JOIN public.staff_teams t ON t.id = m.team_uuid
                    WHERE m.staff_profile_uuid = p.id AND t.id = team_id AND t.archived_at IS NULL
                      AND ({ADMIN} OR t.manager_staff_profile_uuid::text =
                           current_setting('app.staff_profile_uuid', true))
               ))
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION attendance_roster(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION attendance_roster(uuid) TO api_user")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM attendance_policies)
                OR EXISTS (SELECT 1 FROM attendance_requests)
            THEN RAISE EXCEPTION 'Cannot downgrade an attendance system in use';
            END IF;
        END $$;
        """
    )
    op.execute("DROP FUNCTION attendance_roster(uuid)")
    op.execute("DELETE FROM notifications WHERE type::text = 'attendance_request_updated'")
    for table in (
        "attendance_rollover_state",
        "attendance_days",
        "attendance_requests",
        "attendance_holidays",
        "attendance_policies",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION attendance_can_read(uuid)")
