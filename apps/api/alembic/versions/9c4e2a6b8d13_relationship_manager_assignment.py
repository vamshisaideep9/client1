"""Relationship Manager assignment: one RM per Agent, Agent and lead reads.

Revision ID: 9c4e2a6b8d13
Revises: 7a3e9c1b5d42

Product decision (2026-11-26, client feedback round 3): the Main Admin assigns
exactly one Relationship Manager (a Sub Admin ``relationship_manager`` grant)
to an Agent from the Agent side; the Agent sees their RM; the RM reads the
Agent's leads read-only. The service moves an Agent out of any other RM grant
under row locks; this migration only replaces and adds read functions.

Changes
-------
* ``relationship_agent_lines(agent_id, action)`` (new): the lines of the
  calling Sub Admin's active ``relationship_manager`` grants that list the
  Agent and carry the action, for an active Sub Admin on its own account and
  an Agent that is not soft-deleted. The lines must be equal; a grant on
  either line would match a ``both``-line Agent, which
  ``ck_agent_profiles_business_line_operational`` does not allow today (kept
  so a later dual-line Agent cannot fall through).
* ``relationship_can_access(agent_id, action)``: now true exactly when that
  list is non-empty, so ``both``-line Agents match a grant on either line.
  Same signature and return type, so ``relationship_activity`` policies keep
  using it unchanged.
* ``relationship_agents()``: also lists ``both``-line Agents; the lead count
  covers only the lines the caller's grant reaches.
* ``relationship_agent_leads(agent_id)`` (new): read-only lead rows of an
  assigned Agent on the reachable lines: id, lead number, line, status,
  whether the Agent window expired, product label and timestamps. Never the
  lead's name, mobile, email, requirement or notes. At most 500 rows.
* ``agent_relationship_managers(agent_ids)`` (new): the Relationship Manager
  of each Agent (staff profile id, display name, staff code, grant line) for
  a platform Admin, or for the calling Agent's own profile only. Agents cannot
  read ``sub_admin_access`` or ``staff_profiles``. When legacy data lists an
  Agent under several RMs, the lowest staff code is reported.

No table, grant or policy changes. Every function is SECURITY DEFINER with a
fixed ``search_path``, revoked from PUBLIC and granted to ``api_user``.
Rollback restores the previous ``relationship_can_access`` and
``relationship_agents`` bodies and drops the new functions.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9c4e2a6b8d13"
down_revision: str | Sequence[str] | None = "7a3e9c1b5d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_FUNCTIONS = (
    "relationship_agent_lines(uuid, text)",
    "relationship_agent_leads(uuid)",
    "agent_relationship_managers(uuid[])",
)

_LINES_SQL = """
CREATE FUNCTION public.relationship_agent_lines(agent_id uuid, action text)
RETURNS text[] LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT coalesce(array_agg(DISTINCT grant_item ->> 'business_line'), ARRAY[]::text[])
    FROM public.sub_admin_access access
    JOIN public.staff_profiles staff ON staff.id = access.staff_profile_uuid
    JOIN public.agent_profiles agent ON agent.id = agent_id
    JOIN public.auth_users identity ON identity.id = agent.auth_user_uuid
    CROSS JOIN LATERAL jsonb_array_elements(access.grants) AS grant_item
    WHERE current_setting('app.role', true) = 'sub_admin'
      AND access.staff_profile_uuid::text = current_setting('app.staff_profile_uuid', true)
      AND staff.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
      AND staff.role::text = 'sub_admin' AND staff.status::text = 'active'
      AND access.status = 'active' AND identity.status::text <> 'soft_deleted'
      AND grant_item ->> 'assignment' = 'relationship_manager'
      AND grant_item ->> 'business_line' IN ('loans', 'real_estate')
      AND (
          grant_item ->> 'business_line' = agent.business_line::text
          OR agent.business_line::text = 'both'
      )
      AND (grant_item -> 'actions') ? action
      AND (grant_item -> 'agent_profile_ids') ? agent_id::text
$$
"""

_CAN_ACCESS_SQL = """
CREATE OR REPLACE FUNCTION public.relationship_can_access(agent_id uuid, action text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT cardinality(public.relationship_agent_lines(agent_id, action)) > 0
$$
"""

_AGENTS_SQL = """
CREATE OR REPLACE FUNCTION public.relationship_agents()
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
              AND lead.business_line::text = ANY (reach.lines))
    FROM public.agent_profiles agent
    JOIN public.auth_users identity ON identity.id = agent.auth_user_uuid
    CROSS JOIN LATERAL (
        SELECT public.relationship_agent_lines(agent.id, 'view') AS lines
    ) AS reach
    WHERE agent.business_line::text IN ('loans', 'real_estate', 'both')
      AND cardinality(reach.lines) > 0
    ORDER BY agent.agent_code, agent.id
$$
"""

_LEADS_SQL = """
CREATE FUNCTION public.relationship_agent_leads(agent_id uuid)
RETURNS TABLE (
    id uuid, lead_number bigint, business_line text, status text,
    agent_expired boolean, product_label text,
    created_at timestamptz, updated_at timestamptz
) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT lead.id, lead.lead_number, lead.business_line::text, lead.status::text,
           lead.agent_expired_at IS NOT NULL, product.label::text,
           lead.created_at, lead.updated_at
    FROM public.leads lead
    LEFT JOIN public.loan_types product ON product.id = lead.product_id
    CROSS JOIN LATERAL (
        SELECT public.relationship_agent_lines(agent_id, 'view') AS lines
    ) AS reach
    WHERE lead.origin_agent_profile_uuid = agent_id
      AND lead.business_line::text = ANY (reach.lines)
    ORDER BY lead.created_at DESC, lead.id DESC
    LIMIT 500
$$
"""

_MANAGERS_SQL = """
CREATE FUNCTION public.agent_relationship_managers(target_agent_ids uuid[])
RETURNS TABLE (
    agent_profile_id uuid, staff_profile_id uuid, name text, staff_code text,
    business_line text
) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
    SELECT DISTINCT ON (agent.id)
           agent.id, staff.id,
           nullif(btrim(concat_ws(' ', manager.first_name, manager.last_name)), ''),
           staff.staff_code::text, grant_item ->> 'business_line'
    FROM public.agent_profiles agent
    JOIN public.sub_admin_access access ON access.status = 'active'
    JOIN public.staff_profiles staff ON staff.id = access.staff_profile_uuid
    JOIN public.auth_users manager ON manager.id = staff.auth_user_uuid
    CROSS JOIN LATERAL jsonb_array_elements(access.grants) AS grant_item
    WHERE agent.id = ANY (target_agent_ids)
      AND (
          (
              current_setting('app.role', true) = 'admin'
              AND current_setting('app.platform_scope', true) = 'true'
          )
          OR (
              current_setting('app.role', true) = 'agent'
              AND agent.id::text = current_setting('app.agent_profile_uuid', true)
              AND agent.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
          )
      )
      AND staff.role::text = 'sub_admin' AND staff.status::text = 'active'
      AND manager.status::text <> 'soft_deleted'
      AND grant_item ->> 'assignment' = 'relationship_manager'
      AND grant_item ->> 'business_line' IN ('loans', 'real_estate')
      AND (
          grant_item ->> 'business_line' = agent.business_line::text
          OR agent.business_line::text = 'both'
      )
      AND (grant_item -> 'agent_profile_ids') ? agent.id::text
    ORDER BY agent.id, staff.staff_code, staff.id
$$
"""

# The bodies from a3c5e7b9d1f4, restored on downgrade.
_PREVIOUS_CAN_ACCESS_SQL = """
CREATE OR REPLACE FUNCTION public.relationship_can_access(agent_id uuid, action text)
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
"""

_PREVIOUS_AGENTS_SQL = """
CREATE OR REPLACE FUNCTION public.relationship_agents()
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
"""


def upgrade() -> None:
    op.execute(_LINES_SQL)
    op.execute(_CAN_ACCESS_SQL)
    op.execute(_AGENTS_SQL)
    op.execute(_LEADS_SQL)
    op.execute(_MANAGERS_SQL)
    for signature in _NEW_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO api_user")


def downgrade() -> None:
    op.execute(_PREVIOUS_CAN_ACCESS_SQL)
    op.execute(_PREVIOUS_AGENTS_SQL)
    for signature in reversed(_NEW_FUNCTIONS):
        op.execute(f"REVOKE EXECUTE ON FUNCTION public.{signature} FROM api_user")
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
