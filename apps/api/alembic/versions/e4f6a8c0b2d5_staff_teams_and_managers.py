"""Sub Admin managers over single-role Telecaller / Employee teams.

Revision ID: e4f6a8c0b2d5
Revises: a7c9e1b3d5f2

2026-11-15 product decision (CS-019, item 9 of the staff feedback list): the
Main Admin may make a Sub Admin the manager of a team. A team belongs to one
operational line and holds one member role (all Telecallers or all
Employees). A manager runs at most one live team per line; a staff member sits
in at most one team per line. Routing is unchanged -- teams only supervise.

A Sub Admin carries ``platform_scope = 'true'`` and an EMPTY
``app.business_line``, so every existing line-scoped branch that lists
``sub_admin`` already matches no operational row. Manager reach is therefore
granted only by the new PERMISSIVE policies below, which OR with the existing
ones and never widen them. Each new policy calls one confined SECURITY DEFINER
predicate, ``team_manager_reaches(member, line)``, that reads the team tables
live: removing a member, archiving a team, changing its manager or
deactivating the Sub Admin's staff profile takes effect on the next query
with no token change.

Manager reach (row line must equal the team line):

- SELECT on leads, lead_activities, tasks and every request table linked to a
  reached lead (loan_applications, financial_service_enquiries, enquiries,
  site_visits, property_deals), plus SELECT on a lead that carries a task
  assigned to a managed Employee (client name for field work);
- SELECT on the members' staff_profiles rows. Member NAMES come only from
  ``team_roster_names(uuid[])`` (id, first and last name): auth_users is NOT
  opened, because its rows carry the password hash, email and income fields.

There is deliberately NO manager UPDATE policy on leads or tasks. Moving work
goes through ``team_manager_reassign_lead`` / ``team_manager_reassign_task``:
confined SECURITY DEFINER functions that lock the row, re-check that both the
current and the new assignee are reached by the caller in the row's line (one
live team per manager per line makes that the same team), that the work is
open and the target is an active member of the team's role, and then change
only the assignee (and status where the new assignee has not started). The
lead detail-ownership trigger exempts non-``api_user`` writers, and the
assignment-scope trigger still validates the new telecaller.

Rollback drops the new policies, the functions and both tables. Added
``audit_action`` values stay, as PostgreSQL cannot drop enum values.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4f6a8c0b2d5"
down_revision: str | Sequence[str] | None = "a7c9e1b3d5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_VALUES = (
    "staff_team_created",
    "staff_team_updated",
    "staff_team_archived",
    "staff_team_member_added",
    "staff_team_member_removed",
    "team_lead_viewed",
    "team_lead_reassigned",
    "team_task_reassigned",
)

_PLATFORM_ADMIN = (
    "(current_setting('app.platform_scope', true) = 'true' "
    "AND current_setting('app.role', true) = 'admin')"
)

_PRIMARY_ADMIN = """
EXISTS (
    SELECT 1
    FROM public.staff_profiles AS actor
    WHERE actor.id::text = current_setting('app.staff_profile_uuid', true)
      AND actor.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
      AND actor.role::text = 'admin'
      AND actor.scope::text = 'platform'
      AND actor.status::text = 'active'
      AND actor.is_primary_admin = true
)
"""

_OWN_MANAGER = (
    "(current_setting('app.role', true) = 'sub_admin' "
    "AND current_setting('app.staff_profile_uuid', true) <> '' "
    "AND manager_staff_profile_uuid::text = current_setting('app.staff_profile_uuid', true))"
)

_ACTIVE_MANAGER = """
EXISTS (
    SELECT 1
    FROM public.staff_profiles AS manager
    WHERE manager.id = manager_staff_profile_uuid
      AND manager.role::text = 'sub_admin'
      AND manager.scope::text = 'platform'
      AND manager.status::text = 'active'
)
"""

_REASSIGN_FUNCTIONS = (
    "team_manager_reassign_lead(uuid, uuid)",
    "team_manager_reassign_task(uuid, uuid)",
    "team_roster_names(uuid[])",
)

# (policy name, table, command, predicate) -- every manager policy is SELECT.
_REACH_LEAD = (
    "lead_uuid IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM public.leads AS reached "
    "WHERE reached.id = {table}.lead_uuid "
    "AND team_manager_reaches(reached.assigned_telecaller_profile_uuid, "
    "reached.business_line::text))"
)
_MANAGER_POLICIES: tuple[tuple[str, str, str, str], ...] = (
    (
        "leads_team_manager_select",
        "leads",
        "SELECT",
        "team_manager_reaches(assigned_telecaller_profile_uuid, business_line::text)",
    ),
    # An Employee-team manager needs the client on a member's field task.
    (
        "leads_team_manager_task_select",
        "leads",
        "SELECT",
        "EXISTS (SELECT 1 FROM public.tasks AS managed_task "
        "WHERE managed_task.lead_uuid = leads.id "
        "AND managed_task.business_line = leads.business_line "
        "AND team_manager_reaches(managed_task.assigned_employee_profile_uuid, "
        "managed_task.business_line::text))",
    ),
    (
        "lead_activities_team_manager_select",
        "lead_activities",
        "SELECT",
        "team_manager_reaches(telecaller_staff_profile_uuid, business_line::text)",
    ),
    (
        "tasks_team_manager_select",
        "tasks",
        "SELECT",
        "team_manager_reaches(assigned_employee_profile_uuid, business_line::text)",
    ),
    (
        "loan_applications_team_manager_select",
        "loan_applications",
        "SELECT",
        _REACH_LEAD.format(table="loan_applications"),
    ),
    (
        "financial_service_enquiries_team_manager_select",
        "financial_service_enquiries",
        "SELECT",
        _REACH_LEAD.format(table="financial_service_enquiries"),
    ),
    (
        "enquiries_team_manager_select",
        "enquiries",
        "SELECT",
        _REACH_LEAD.format(table="enquiries"),
    ),
    (
        "site_visits_team_manager_select",
        "site_visits",
        "SELECT",
        _REACH_LEAD.format(table="site_visits"),
    ),
    (
        "property_deals_team_manager_select",
        "property_deals",
        "SELECT",
        _REACH_LEAD.format(table="property_deals"),
    ),
    (
        "staff_profiles_team_manager_select",
        "staff_profiles",
        "SELECT",
        "team_manager_reaches(id, NULL)",
    ),
)


def upgrade() -> None:
    for value in _AUDIT_VALUES:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    business_line = postgresql.ENUM(name="business_line_enum", create_type=False)

    op.create_table(
        "staff_teams",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("business_line", business_line, nullable=False),
        sa.Column("member_role", sa.String(length=16), nullable=False),
        sa.Column("manager_staff_profile_uuid", sa.UUID(), nullable=False),
        sa.Column("created_by_auth_user_uuid", sa.UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_staff_teams_business_line_operational"),
        ),
        sa.CheckConstraint(
            "member_role IN ('telecaller', 'employee')",
            name=op.f("ck_staff_teams_member_role_supported"),
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 80",
            name=op.f("ck_staff_teams_name_present"),
        ),
        sa.ForeignKeyConstraint(
            ["manager_staff_profile_uuid"],
            ["staff_profiles.id"],
            name=op.f("fk_staff_teams_manager_staff_profile_uuid_staff_profiles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_auth_user_uuid"],
            ["auth_users.id"],
            name=op.f("fk_staff_teams_created_by_auth_user_uuid_auth_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_teams")),
    )
    op.create_index(
        "uq_staff_teams_live_manager_line",
        "staff_teams",
        ["manager_staff_profile_uuid", "business_line"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "staff_team_members",
        sa.Column("team_uuid", sa.UUID(), nullable=False),
        sa.Column("staff_profile_uuid", sa.UUID(), nullable=False),
        sa.Column("business_line", business_line, nullable=False),
        sa.Column("added_by_auth_user_uuid", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "business_line::text IN ('loans', 'real_estate')",
            name=op.f("ck_staff_team_members_business_line_operational"),
        ),
        sa.ForeignKeyConstraint(
            ["team_uuid"],
            ["staff_teams.id"],
            name=op.f("fk_staff_team_members_team_uuid_staff_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staff_profile_uuid"],
            ["staff_profiles.id"],
            name=op.f("fk_staff_team_members_staff_profile_uuid_staff_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_auth_user_uuid"],
            ["auth_users.id"],
            name=op.f("fk_staff_team_members_added_by_auth_user_uuid_auth_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "team_uuid", "staff_profile_uuid", name=op.f("pk_staff_team_members")
        ),
        sa.UniqueConstraint(
            "staff_profile_uuid",
            "business_line",
            name=op.f("uq_staff_team_members_staff_profile_uuid"),
        ),
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON staff_teams TO api_user")
    op.execute("GRANT SELECT, INSERT, DELETE ON staff_team_members TO api_user")
    op.execute("ALTER TABLE staff_teams ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE staff_team_members ENABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY staff_teams_select ON staff_teams
        FOR SELECT
        USING ({_PLATFORM_ADMIN} OR {_OWN_MANAGER})
        """
    )
    op.execute(
        f"""
        CREATE POLICY staff_teams_insert ON staff_teams
        FOR INSERT
        WITH CHECK ({_PRIMARY_ADMIN} AND archived_at IS NULL AND {_ACTIVE_MANAGER})
        """
    )
    # An archived team may keep a since-deactivated manager; a live team may not.
    op.execute(
        f"""
        CREATE POLICY staff_teams_update ON staff_teams
        FOR UPDATE
        USING ({_PRIMARY_ADMIN})
        WITH CHECK ({_PRIMARY_ADMIN} AND (archived_at IS NOT NULL OR {_ACTIVE_MANAGER}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY staff_team_members_select ON staff_team_members
        FOR SELECT
        USING (
            {_PLATFORM_ADMIN}
            OR EXISTS (
                SELECT 1
                FROM public.staff_teams AS team
                WHERE team.id = staff_team_members.team_uuid
                  AND current_setting('app.role', true) = 'sub_admin'
                  AND current_setting('app.staff_profile_uuid', true) <> ''
                  AND team.manager_staff_profile_uuid::text
                      = current_setting('app.staff_profile_uuid', true)
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY staff_team_members_insert ON staff_team_members
        FOR INSERT
        WITH CHECK (
            {_PRIMARY_ADMIN}
            AND EXISTS (
                SELECT 1
                FROM public.staff_teams AS team
                JOIN public.staff_profiles AS member
                  ON member.id = staff_team_members.staff_profile_uuid
                WHERE team.id = staff_team_members.team_uuid
                  AND team.archived_at IS NULL
                  AND team.business_line = staff_team_members.business_line
                  AND member.role::text = team.member_role
                  AND member.scope::text = 'line'
                  AND member.status::text = 'active'
                  AND member.business_line::text IN (team.business_line::text, 'both')
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY staff_team_members_delete ON staff_team_members
        FOR DELETE
        USING ({_PRIMARY_ADMIN})
        """
    )

    # Confined predicate: owner-privileged so it can read the team tables and
    # staff profiles regardless of the caller's RLS, but it only ever answers
    # for the CALLER's own staff profile and only for an active Sub Admin.
    op.execute(
        """
        CREATE FUNCTION team_manager_reaches(member_staff_profile_uuid uuid, row_line text)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
            SELECT current_setting('app.role', true) = 'sub_admin'
               AND coalesce(current_setting('app.staff_profile_uuid', true), '') <> ''
               AND member_staff_profile_uuid IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM public.staff_team_members AS m
                   JOIN public.staff_teams AS t ON t.id = m.team_uuid
                   JOIN public.staff_profiles AS manager
                     ON manager.id = t.manager_staff_profile_uuid
                   JOIN public.staff_profiles AS member
                     ON member.id = m.staff_profile_uuid
                   WHERE m.staff_profile_uuid = member_staff_profile_uuid
                     AND (row_line IS NULL OR t.business_line::text = row_line)
                     AND t.archived_at IS NULL
                     AND t.manager_staff_profile_uuid::text
                         = current_setting('app.staff_profile_uuid', true)
                     AND manager.auth_user_uuid::text
                         = current_setting('app.auth_user_uuid', true)
                     AND manager.role::text = 'sub_admin'
                     AND manager.status::text = 'active'
                     AND member.role::text = t.member_role
               )
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION team_manager_reaches(uuid, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION team_manager_reaches(uuid, text) TO api_user")

    for name, table, _command, predicate in _MANAGER_POLICIES:
        op.execute(f"CREATE POLICY {name} ON {table} FOR SELECT USING ({predicate})")

    op.execute(
        """
        CREATE FUNCTION team_manager_reassign_lead(target_lead_uuid uuid, new_assignee uuid)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            lead_row public.leads%ROWTYPE;
        BEGIN
            SELECT * INTO lead_row FROM public.leads WHERE id = target_lead_uuid FOR UPDATE;
            IF NOT FOUND OR NOT team_manager_reaches(
                lead_row.assigned_telecaller_profile_uuid, lead_row.business_line::text
            ) THEN
                RAISE EXCEPTION 'lead is not in the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF lead_row.status::text NOT IN ('assigned', 'working') THEN
                RAISE EXCEPTION 'only open leads can be reassigned'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF new_assignee IS NULL
               OR new_assignee = lead_row.assigned_telecaller_profile_uuid
               OR NOT team_manager_reaches(new_assignee, lead_row.business_line::text)
               OR NOT EXISTS (
                   SELECT 1 FROM public.staff_profiles AS target
                   WHERE target.id = new_assignee
                     AND target.role::text = 'telecaller'
                     AND target.status::text = 'active'
               ) THEN
                RAISE EXCEPTION 'target is not another active member of the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            UPDATE public.leads
               SET assigned_telecaller_profile_uuid = new_assignee,
                   status = 'assigned',
                   updated_at = now()
             WHERE id = target_lead_uuid;
            RETURN lead_row.assigned_telecaller_profile_uuid;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION team_manager_reassign_task(target_task_uuid uuid, new_assignee uuid)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
        DECLARE
            task_row public.tasks%ROWTYPE;
        BEGIN
            SELECT * INTO task_row FROM public.tasks WHERE id = target_task_uuid FOR UPDATE;
            IF NOT FOUND OR NOT team_manager_reaches(
                task_row.assigned_employee_profile_uuid, task_row.business_line::text
            ) THEN
                RAISE EXCEPTION 'task is not in the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF task_row.status::text NOT IN ('assigned', 'in_progress', 'blocked') THEN
                RAISE EXCEPTION 'only open tasks can be reassigned'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF new_assignee IS NULL
               OR new_assignee = task_row.assigned_employee_profile_uuid
               OR NOT team_manager_reaches(new_assignee, task_row.business_line::text)
               OR NOT EXISTS (
                   SELECT 1 FROM public.staff_profiles AS target
                   WHERE target.id = new_assignee
                     AND target.role::text = 'employee'
                     AND target.status::text = 'active'
                     AND target.business_line::text IN (task_row.business_line::text, 'both')
               ) THEN
                RAISE EXCEPTION 'target is not another active member of the caller''s team'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            -- The new Employee has not started; a blocked task stays blocked.
            UPDATE public.tasks
               SET assigned_employee_profile_uuid = new_assignee,
                   status = CASE WHEN status::text = 'in_progress'
                                 THEN 'assigned'::task_status ELSE status END,
                   updated_at = now()
             WHERE id = target_task_uuid;
            RETURN task_row.assigned_employee_profile_uuid;
        END;
        $$
        """
    )
    # Names only, and only for staff profiles the caller reaches as a manager.
    op.execute(
        """
        CREATE FUNCTION team_roster_names(profile_ids uuid[])
        RETURNS TABLE (staff_profile_uuid uuid, first_name text, last_name text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp
        AS $$
            SELECT member.id, person.first_name::text, person.last_name::text
            FROM public.staff_profiles AS member
            JOIN public.auth_users AS person ON person.id = member.auth_user_uuid
            WHERE member.id = ANY(profile_ids)
              AND team_manager_reaches(member.id, NULL)
        $$
        """
    )
    for function in _REASSIGN_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO api_user")


def downgrade() -> None:
    for function in _REASSIGN_FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM api_user")
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    for name, table, _command, _predicate in reversed(_MANAGER_POLICIES):
        op.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
    op.execute("REVOKE EXECUTE ON FUNCTION team_manager_reaches(uuid, text) FROM api_user")
    op.execute("DROP FUNCTION IF EXISTS team_manager_reaches(uuid, text)")
    for policy in ("delete", "insert", "select"):
        op.execute(f"DROP POLICY IF EXISTS staff_team_members_{policy} ON staff_team_members")
    for policy in ("update", "insert", "select"):
        op.execute(f"DROP POLICY IF EXISTS staff_teams_{policy} ON staff_teams")
    op.execute("REVOKE ALL PRIVILEGES ON staff_team_members FROM api_user")
    op.execute("REVOKE ALL PRIVILEGES ON staff_teams FROM api_user")
    op.drop_table("staff_team_members")
    op.drop_index("uq_staff_teams_live_manager_line", table_name="staff_teams")
    op.drop_table("staff_teams")
