"""Telecaller specialty pools and confined task/own-team metadata (Batch 3).

Legacy rotation becomes the all-eligible pool. No assignment is rewritten.
Downgrade discards only the added pool history and optional specialty metadata.
"""

import sqlalchemy as sa

from alembic import op

revision = "b7d9f1a3c5e7"
down_revision = "a6c8e0f2b4d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'staff_specialty_updated'")
    op.add_column("staff_profiles", sa.Column("loan_specialty_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_staff_profiles_loan_specialty_id_loan_types",
        "staff_profiles",
        "loan_types",
        ["loan_specialty_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_staff_profiles_loan_specialty_role_line",
        "staff_profiles",
        "loan_specialty_id IS NULL OR "
        "(role::text = 'telecaller' AND business_line IS NOT NULL "
        "AND business_line::text IN ('loans', 'both'))",
    )
    op.execute("""
        CREATE FUNCTION validate_staff_loan_specialty() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'UPDATE'
            AND NEW.loan_specialty_id IS NOT DISTINCT FROM OLD.loan_specialty_id THEN
            RETURN NEW;
          END IF;
          IF current_user = 'api_user' AND NOT (
            coalesce(current_setting('app.role', true), '') = 'admin' AND
            coalesce(current_setting('app.platform_scope', true), '') = 'true'
          ) THEN
            RAISE EXCEPTION 'only platform Admin may set a specialty' USING ERRCODE = '42501';
          END IF;
          IF NEW.loan_specialty_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.loan_types p WHERE p.id = NEW.loan_specialty_id
              AND p.active AND p.category = 'loan'
          ) THEN
            RAISE EXCEPTION 'specialty must be an active loan product' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_staff_loan_specialty BEFORE INSERT OR UPDATE ON staff_profiles "
        "FOR EACH ROW EXECUTE FUNCTION validate_staff_loan_specialty()"
    )
    op.add_column(
        "lead_assignment_cursors",
        sa.Column(
            "pool",
            sa.String(64),
            nullable=False,
            server_default="all",
        ),
    )
    op.drop_constraint("pk_lead_assignment_cursors", "lead_assignment_cursors", type_="primary")
    op.create_primary_key(
        "pk_lead_assignment_cursors", "lead_assignment_cursors", ["business_line", "pool"]
    )
    op.create_check_constraint(
        "ck_lead_assignment_cursors_pool",
        "lead_assignment_cursors",
        "pool = 'all' OR (business_line::text = 'loans' AND "
        "(pool = 'unspecialised' OR pool ~ "
        "'^product:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_lead_assignment_cursor() RETURNS trigger AS $$
        BEGIN
          IF NEW.last_telecaller_profile_uuid IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.staff_profiles staff
            WHERE staff.id = NEW.last_telecaller_profile_uuid
              AND staff.role::text = 'telecaller'
              AND staff.business_line IN (NEW.business_line, 'both')
              AND (NEW.pool = 'all'
                OR (NEW.pool = 'unspecialised' AND staff.loan_specialty_id IS NULL)
                OR NEW.pool = 'product:' || staff.loan_specialty_id::text)
          ) THEN
            RAISE EXCEPTION 'assignment cursor must reference a same-pool telecaller'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER trg_validate_lead_assignment_cursor ON lead_assignment_cursors")
    op.execute(
        "CREATE TRIGGER trg_validate_lead_assignment_cursor BEFORE INSERT OR UPDATE OF "
        "business_line, pool, last_telecaller_profile_uuid ON lead_assignment_cursors "
        "FOR EACH ROW EXECUTE FUNCTION validate_lead_assignment_cursor()"
    )
    # A caller supplies task IDs, never a target person. Role, line and actual task
    # participation are checked inside the definer; no auth_users grant is added.
    op.execute("""
        CREATE FUNCTION task_staff_names(task_ids uuid[])
        RETURNS TABLE (task_uuid uuid, raised_by_telecaller_name text,
                       raised_by_telecaller_code text,
                       assigned_employee_name text, assigned_employee_code text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
          SELECT t.id,
                 CASE WHEN ru.status::text <> 'soft_deleted'
                   THEN nullif(btrim(ru.first_name || ' ' || ru.last_name), '') END,
                 CASE WHEN ru.status::text <> 'soft_deleted' THEN raiser.staff_code::text END,
                 CASE WHEN eu.status::text <> 'soft_deleted'
                   THEN nullif(btrim(eu.first_name || ' ' || eu.last_name), '') END,
                 CASE WHEN eu.status::text <> 'soft_deleted' THEN employee.staff_code::text END
          FROM public.tasks t
          JOIN public.staff_profiles actor
            ON actor.id::text = current_setting('app.staff_profile_uuid', true)
            AND actor.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
            AND actor.role::text = current_setting('app.role', true)
            AND actor.status::text = 'active'
            AND actor.business_line IN (t.business_line, 'both')
          JOIN public.auth_users au ON au.id = actor.auth_user_uuid
            AND au.status::text NOT IN ('soft_deleted', 'suspended')
          LEFT JOIN public.staff_profiles raiser ON raiser.id = t.raised_by_staff_profile_uuid
          LEFT JOIN public.auth_users ru ON ru.id = raiser.auth_user_uuid
          LEFT JOIN public.staff_profiles employee ON employee.id = t.assigned_employee_profile_uuid
          LEFT JOIN public.auth_users eu ON eu.id = employee.auth_user_uuid
          WHERE t.id = ANY(task_ids)
            AND t.business_line::text = current_setting('app.business_line', true)
            AND ((actor.role::text = 'employee' AND t.assigned_employee_profile_uuid = actor.id)
              OR (actor.role::text = 'telecaller' AND t.raised_by_staff_profile_uuid = actor.id))
        $$
    """)
    op.execute("""
        CREATE FUNCTION own_profile_teams()
        RETURNS TABLE (staff_profile_uuid uuid, business_line text, name text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
          SELECT DISTINCT p.id, t.business_line::text, t.name::text
          FROM public.staff_profiles p
          JOIN public.auth_users u ON u.id = p.auth_user_uuid
          JOIN public.staff_teams t ON t.archived_at IS NULL
            AND ((p.role::text = 'sub_admin' AND t.manager_staff_profile_uuid = p.id)
              OR (p.role::text IN ('telecaller', 'employee')
                AND t.member_role = p.role::text
                AND p.business_line IN (t.business_line, 'both')
                AND EXISTS (SELECT 1 FROM public.staff_team_members m
                  WHERE m.team_uuid = t.id AND m.staff_profile_uuid = p.id
                    AND m.business_line = t.business_line)))
          WHERE p.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
            AND p.status::text = 'active' AND u.status::text <> 'soft_deleted'
          ORDER BY p.id, t.business_line::text, t.name::text
        $$
    """)
    for function in ("task_staff_names(uuid[])", "own_profile_teams()"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO api_user")


def downgrade() -> None:
    for function in ("task_staff_names(uuid[])", "own_profile_teams()"):
        op.execute(f"DROP FUNCTION {function}")
    op.execute("DELETE FROM lead_assignment_cursors WHERE pool <> 'all'")
    op.execute("DROP TRIGGER trg_validate_lead_assignment_cursor ON lead_assignment_cursors")
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_lead_assignment_cursor() RETURNS trigger AS $$
        BEGIN
          IF NEW.last_telecaller_profile_uuid IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.staff_profiles staff
            WHERE staff.id = NEW.last_telecaller_profile_uuid
              AND staff.role::text = 'telecaller'
              AND staff.business_line IN (NEW.business_line, 'both')
          ) THEN
            RAISE EXCEPTION 'assignment cursor must reference a same-line telecaller'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER trg_validate_lead_assignment_cursor BEFORE INSERT OR UPDATE OF "
        "business_line, last_telecaller_profile_uuid ON lead_assignment_cursors "
        "FOR EACH ROW EXECUTE FUNCTION validate_lead_assignment_cursor()"
    )
    op.drop_constraint("ck_lead_assignment_cursors_pool", "lead_assignment_cursors", type_="check")
    op.drop_constraint("pk_lead_assignment_cursors", "lead_assignment_cursors", type_="primary")
    op.drop_column("lead_assignment_cursors", "pool")
    op.create_primary_key(
        "pk_lead_assignment_cursors", "lead_assignment_cursors", ["business_line"]
    )
    op.execute("DROP TRIGGER trg_staff_loan_specialty ON staff_profiles")
    op.execute("DROP FUNCTION validate_staff_loan_specialty()")
    op.drop_constraint(
        "ck_staff_profiles_loan_specialty_role_line", "staff_profiles", type_="check"
    )
    op.drop_constraint(
        "fk_staff_profiles_loan_specialty_id_loan_types", "staff_profiles", type_="foreignkey"
    )
    op.drop_column("staff_profiles", "loan_specialty_id")
