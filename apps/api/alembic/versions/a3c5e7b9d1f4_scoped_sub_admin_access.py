"""Add opt-in scoped Sub Admin access.

Revision ID: a3c5e7b9d1f4
Revises: f2b4d6a8c0e3
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a3c5e7b9d1f4"
down_revision = "f2b4d6a8c0e3"
branch_labels = None
depends_on = None

_PLATFORM_ADMIN = """
    current_setting('app.role', true) = 'admin'
    AND current_setting('app.platform_scope', true) = 'true'
"""
_MAIN_ADMIN = f"""
    ({_PLATFORM_ADMIN}) AND EXISTS (
        SELECT 1 FROM public.staff_profiles AS actor
        WHERE actor.id::text = current_setting('app.staff_profile_uuid', true)
          AND actor.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
          AND actor.is_primary_admin AND actor.status::text = 'active'
    )
"""
_OWN = """
    current_setting('app.role', true) = 'sub_admin'
    AND staff_profile_uuid::text = current_setting('app.staff_profile_uuid', true)
"""
_TARGET = """
    EXISTS (
        SELECT 1 FROM public.staff_profiles AS target
        WHERE target.id = staff_profile_uuid
          AND target.role::text = 'sub_admin' AND target.scope::text = 'platform'
    )
"""


def _team_reach(*, scoped: bool) -> None:
    scope = (
        "AND public.sub_admin_has_line('team_manager', CASE WHEN "
        "current_setting('app.team_review', true) = 'true' THEN 'review' ELSE 'view' END, "
        "t.business_line::text)"
        if scoped
        else ""
    )
    op.execute(f"""
        CREATE OR REPLACE FUNCTION team_manager_reaches(
            member_staff_profile_uuid uuid, row_line text
        )
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
                     {scope}
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
    """)


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'sub_admin_access_updated'")
    op.create_table(
        "sub_admin_access",
        sa.Column("staff_profile_uuid", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("grants", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["staff_profile_uuid"], ["staff_profiles.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'inactive')",
            name=op.f("ck_sub_admin_access_valid_status"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_sub_admin_access_positive_version")),
        sa.CheckConstraint(
            "jsonb_typeof(grants) = 'array' AND jsonb_array_length(grants) <= 8 "
            "AND (status = 'active' OR grants = '[]'::jsonb)",
            name=op.f("ck_sub_admin_access_valid_grants"),
        ),
    )
    op.execute("GRANT SELECT, INSERT ON sub_admin_access TO api_user")
    op.execute("GRANT UPDATE (status, grants, version) ON sub_admin_access TO api_user")
    op.execute("ALTER TABLE sub_admin_access ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY sub_admin_access_select ON sub_admin_access FOR SELECT
        USING (({_OWN}) OR ({_MAIN_ADMIN}) OR (({_PLATFORM_ADMIN}) AND status = 'pending'))
    """)
    op.execute(f"""
        CREATE POLICY sub_admin_access_insert ON sub_admin_access FOR INSERT
        WITH CHECK (({_TARGET}) AND (
            ({_MAIN_ADMIN}) OR (({_PLATFORM_ADMIN}) AND status = 'pending' AND version = 1)
        ))
    """)
    op.execute(f"""
        CREATE POLICY sub_admin_access_update ON sub_admin_access FOR UPDATE
        USING ({_MAIN_ADMIN}) WITH CHECK (({_MAIN_ADMIN}) AND ({_TARGET}))
    """)
    op.execute("""
        CREATE FUNCTION public.sub_admin_has_line(module text, action text, line text)
        RETURNS boolean LANGUAGE sql STABLE SET search_path = '' AS $$
            SELECT CASE
                WHEN current_setting('app.role', true) IS DISTINCT FROM 'sub_admin' THEN true
                ELSE COALESCE((
                    SELECT access.status = 'active' AND
                           (SELECT count(DISTINCT grant_item ->> 'business_line')
                            FROM jsonb_array_elements(access.grants) AS grant_item
                            WHERE grant_item ->> 'assignment' = module
                              AND (grant_item -> 'actions') ? action
                              AND grant_item ->> 'business_line' IN ('loans', 'real_estate')
                              AND (line = 'both' OR grant_item ->> 'business_line' = line))
                           = CASE WHEN line = 'both' THEN 2 ELSE 1 END
                    FROM public.sub_admin_access AS access
                    WHERE access.staff_profile_uuid::text =
                        current_setting('app.staff_profile_uuid', true)
                ), true)
            END
        $$
    """)
    _team_reach(scoped=True)
    op.execute("REVOKE ALL ON FUNCTION public.sub_admin_has_line(text, text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.sub_admin_has_line(text, text, text) TO api_user")
    op.execute("""
        CREATE POLICY scoped_manager_team ON staff_teams AS RESTRICTIVE
        USING (public.sub_admin_has_line('team_manager', 'view', business_line::text))
    """)
    for table in ("payouts", "commissions"):
        op.execute(f"""
            CREATE POLICY scoped_finance_read ON {table} FOR SELECT TO api_user
            USING (
                current_setting('app.role', true) = 'sub_admin'
                AND EXISTS (
                    SELECT 1 FROM public.sub_admin_access a
                    WHERE a.staff_profile_uuid::text =
                        current_setting('app.staff_profile_uuid', true)
                )
                AND public.sub_admin_has_line('account_manager', 'view', business_line::text)
            )
        """)
    for table in ("banners", "offers", "campaign_media_assets"):
        op.execute(f"""
            CREATE POLICY scoped_media_read ON {table} AS RESTRICTIVE FOR SELECT
            USING (public.sub_admin_has_line('media_sub_admin', 'view', business_line::text))
        """)
        for operation, predicate in (
            ("insert", "WITH CHECK ({access})"),
            ("update", "USING ({access}) WITH CHECK ({access})"),
            ("delete", "USING ({access})"),
        ):
            access = "public.sub_admin_has_line('media_sub_admin', 'edit', business_line::text)"
            op.execute(f"""
                CREATE POLICY scoped_media_{operation} ON {table} AS RESTRICTIVE
                FOR {operation.upper()} {predicate.format(access=access)}
            """)

    _create_relationship_access()


def _create_relationship_access() -> None:
    op.execute("""
        CREATE FUNCTION public.relationship_can_access(agent_id uuid, action text)
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT current_setting('app.role', true) = 'sub_admin' AND EXISTS (
                SELECT 1 FROM public.sub_admin_access access
                JOIN public.staff_profiles staff ON staff.id = access.staff_profile_uuid
                JOIN public.agent_profiles agent ON agent.id = agent_id
                JOIN public.auth_users identity ON identity.id = agent.auth_user_uuid
                CROSS JOIN LATERAL jsonb_array_elements(access.grants) AS grant_item
                WHERE access.staff_profile_uuid::text =
                    current_setting('app.staff_profile_uuid', true)
                  AND staff.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                  AND staff.role::text = 'sub_admin' AND staff.status::text = 'active'
                  AND access.status = 'active' AND identity.status::text <> 'soft_deleted'
                  AND grant_item ->> 'assignment' = 'relationship_manager'
                  AND grant_item ->> 'business_line' = agent.business_line::text
                  AND (grant_item -> 'actions') ? action
                  AND (grant_item -> 'agent_profile_ids') ? agent_id::text
            )
        $$
    """)
    op.execute("""
        CREATE FUNCTION public.relationship_agents()
        RETURNS TABLE (
            id uuid, name text, agent_code text, business_line text, status text,
            kyc_status text, approved_at timestamptz, submitted_leads bigint
        ) LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public, pg_temp AS $$
            SELECT agent.id, concat_ws(' ', identity.first_name, identity.last_name),
                   agent.agent_code::text, agent.business_line::text, agent.status::text,
                   agent.kyc_status::text, agent.approved_at,
                   (SELECT count(*) FROM public.leads lead
                    WHERE lead.origin_agent_profile_uuid = agent.id
                      AND lead.business_line = agent.business_line)
            FROM public.agent_profiles agent
            JOIN public.auth_users identity ON identity.id = agent.auth_user_uuid
            WHERE agent.business_line::text IN ('loans', 'real_estate')
              AND public.relationship_can_access(agent.id, 'view')
            ORDER BY agent.agent_code, agent.id
        $$
    """)
    for signature in ("relationship_can_access(uuid, text)", "relationship_agents()"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO api_user")
    op.create_table(
        "relationship_activity",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "agent_profile_id",
            sa.UUID(),
            sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "staff_profile_id",
            sa.UUID(),
            sa.ForeignKey("staff_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('follow_up', 'recommendation')", name="ck_relationship_activity_kind"
        ),
        sa.CheckConstraint("length(btrim(note)) > 0", name="ck_relationship_activity_note"),
    )
    op.create_index(
        "ix_relationship_activity_agent",
        "relationship_activity",
        ["agent_profile_id", "created_at"],
    )
    op.execute("GRANT SELECT, INSERT ON relationship_activity TO api_user")
    op.execute("ALTER TABLE relationship_activity ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY relationship_activity_select ON relationship_activity FOR SELECT TO api_user
        USING (({_PLATFORM_ADMIN}) OR public.relationship_can_access(agent_profile_id, 'view'))
    """)
    op.execute("""
        CREATE POLICY relationship_activity_insert ON relationship_activity FOR INSERT TO api_user
        WITH CHECK (
            staff_profile_id::text = current_setting('app.staff_profile_uuid', true)
            AND public.relationship_can_access(agent_profile_id, 'follow_up')
        )
    """)


def downgrade() -> None:
    # Removing the access table would silently restore every legacy privilege.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM sub_admin_access) THEN
                RAISE EXCEPTION 'Cannot remove Sub Admin access controls with saved profiles';
            END IF;
        END $$
    """)
    op.drop_table("relationship_activity")
    op.execute("DROP FUNCTION public.relationship_agents()")
    op.execute("DROP FUNCTION public.relationship_can_access(uuid, text)")
    for table in ("banners", "offers", "campaign_media_assets"):
        for operation in ("read", "insert", "update", "delete"):
            op.execute(f"DROP POLICY scoped_media_{operation} ON {table}")
    for table in ("payouts", "commissions"):
        op.execute(f"DROP POLICY scoped_finance_read ON {table}")
    _team_reach(scoped=False)
    op.execute("DROP POLICY scoped_manager_team ON staff_teams")
    op.execute("DROP FUNCTION public.sub_admin_has_line(text, text, text)")
    op.drop_table("sub_admin_access")
