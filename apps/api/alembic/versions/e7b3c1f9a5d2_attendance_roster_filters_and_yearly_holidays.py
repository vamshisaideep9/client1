"""Attendance roster details for filters, and yearly repeating holidays.

Revision ID: e7b3c1f9a5d2
Revises: 9c4e2a6b8d13

Product decision (2026-11-26, client feedback round 3): the attendance grid
and roster filter by department, product, role, Sub Admin group and leave
type, and holidays can repeat every year.

Roster details
--------------
``attendance_reporting_roster(uuid)`` keeps its signature and grants (a
``CREATE OR REPLACE`` cannot add result columns). The new SECURITY DEFINER
``attendance_roster_details(uuid)`` returns the same members, reached only
through that function, plus each member's department (attendance employment
line, else the staff line), product specialty and active Sub Admin groups
(``team_manager``, ``account_manager``, ``relationship_manager``). No other
staff data is exposed.

Yearly holidays
---------------
``attendance_recurring_holidays`` stores one row per repeating holiday:
month and day, name, an optional line (null for every line), ``starts_on``
and an optional ``ends_on``. ``day_without_clock`` treats a matching date in
``[starts_on, ends_on]`` as a holiday. A 29 February series only occurs in
leap years. The service creates series only from today onwards, and
"stop repeating" sets ``ends_on`` to today (or deletes a series that has not
started), so past and closed months never change. Writes go through the
service's owner session, like the other holiday tables; ``api_user`` gets
SELECT only, under FORCE RLS: platform Admin, any staff role for all-line
rows, and line rows for the caller's line or attendance employment line.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e7b3c1f9a5d2"
down_revision: str | Sequence[str] | None = "9c4e2a6b8d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "attendance_recurring_holidays"
_ADMIN = (
    "(current_setting('app.role', true) = 'admin' "
    "AND current_setting('app.platform_scope', true) = 'true')"
)
_STAFF = "(current_setting('app.role', true) IN ('telecaller', 'employee', 'sub_admin'))"

_DETAILS_SQL = """
CREATE FUNCTION public.attendance_roster_details(selected_team uuid)
RETURNS TABLE (
    staff_profile_id uuid, name text, staff_code text, role text,
    department text, product_id uuid, sub_admin_groups text[]
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT r.staff_profile_id, r.name, r.staff_code, r.role,
           coalesce(e.business_line, p.business_line::text),
           p.loan_specialty_id,
           ARRAY(
               SELECT DISTINCT grant_item ->> 'assignment'
               FROM public.sub_admin_access AS access
               CROSS JOIN LATERAL jsonb_array_elements(access.grants) AS grant_item
               WHERE access.staff_profile_uuid = p.id
                 AND access.status = 'active'
                 AND grant_item ->> 'assignment' IN (
                     'team_manager', 'account_manager', 'relationship_manager'
                 )
               ORDER BY 1
           )
    FROM public.attendance_reporting_roster(selected_team) AS r
    JOIN public.staff_profiles AS p ON p.id = r.staff_profile_id
    LEFT JOIN public.attendance_employment AS e ON e.staff_profile_id = p.id
$$
"""


def upgrade() -> None:
    op.execute(_DETAILS_SQL)
    op.execute("REVOKE ALL ON FUNCTION public.attendance_roster_details(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.attendance_roster_details(uuid) TO api_user")

    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_line", sa.String(12)),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("day", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth_users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "business_line IS NULL OR business_line IN ('loans', 'real_estate')",
            name="attendance_recurring_holiday_line",
        ),
        sa.CheckConstraint(
            "month BETWEEN 1 AND 12 AND day >= 1 AND day <= CASE "
            "WHEN month = 2 THEN 29 WHEN month IN (4, 6, 9, 11) THEN 30 ELSE 31 END",
            name="attendance_recurring_holiday_date",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="attendance_recurring_holiday_name"),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on",
            name="attendance_recurring_holiday_period",
        ),
    )
    # One open series per date and line (null line = every line).
    op.create_index(
        "uq_attendance_recurring_holidays_open",
        _TABLE,
        [sa.text("coalesce(business_line, '')"), "month", "day"],
        unique=True,
        postgresql_where=sa.text("ends_on IS NULL"),
    )
    op.create_index("ix_attendance_recurring_holidays_date", _TABLE, ["month", "day"])
    op.execute(f"GRANT SELECT ON {_TABLE} TO api_user")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {_TABLE}_read ON {_TABLE} FOR SELECT TO api_user
        USING (
            {_ADMIN}
            OR (business_line IS NULL AND {_STAFF})
            OR business_line = current_setting('app.business_line', true)
            OR EXISTS (
                SELECT 1 FROM public.attendance_employment AS e
                WHERE e.staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
                  AND e.business_line = {_TABLE}.business_line
            )
        )
    """)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {_TABLE})")):
        raise RuntimeError("Rollback would discard saved yearly holidays.")
    op.execute(f"DROP POLICY {_TABLE}_read ON {_TABLE}")
    op.drop_table(_TABLE)
    op.execute("REVOKE EXECUTE ON FUNCTION public.attendance_roster_details(uuid) FROM api_user")
    op.execute("DROP FUNCTION public.attendance_roster_details(uuid)")
