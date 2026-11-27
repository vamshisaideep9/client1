"""Agent lead assignees: who works each lead an Agent introduced.

Revision ID: 7a3e9c1b5d42
Revises: 5c8e2a7f1b94

Product decision (2026-11-26, client feedback round 3): an Agent sees the
Telecaller and the Officer working each lead they introduced, as display name,
staff role and staff code (never a phone number or email), plus the lead's
product label. The Agent's field rule that hides staff names on the lead
history does not apply to this field.

Why a confined function and not a policy or grant
-------------------------------------------------
Agents have no read of ``staff_profiles``, ``auth_users`` or ``tasks``, and a
PERMISSIVE policy on those tables would also widen every RLS-only route that
reads them. As with ``agent_lead_history`` (e8b0d2f4a6c9), the reach lives in
one SECURITY DEFINER read function that re-checks the caller on every call:

- the request role is ``agent`` with a non-empty account, Agent profile and
  business line;
- only leads the calling Agent introduced (``origin_agent_profile_uuid``) on
  the request's line, whose Agent profile belongs to the calling account;
- the Telecaller is the lead's ``assigned_telecaller_profile_uuid``;
- the Officer is the assignee of the lead's latest non-cancelled task on the
  lead's line that has an assignee;
- returned columns: lead id, product label, and for each person the display
  name, staff role and staff code. Mobile numbers, emails, profile ids and
  task details are never returned.

No table, grant or policy changes. Rollback drops the function.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7a3e9c1b5d42"
down_revision: str | Sequence[str] | None = "5c8e2a7f1b94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGNATURE = "agent_lead_assignees(uuid[])"

_FUNCTION_SQL = """
CREATE FUNCTION agent_lead_assignees(target_lead_uuids uuid[])
RETURNS TABLE (
    lead_uuid uuid,
    product_label text,
    telecaller_name text,
    telecaller_role text,
    telecaller_staff_code text,
    officer_name text,
    officer_role text,
    officer_staff_code text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT
        l.id,
        lt.label::text,
        nullif(btrim(concat_ws(' ', tu.first_name, tu.last_name)), ''),
        tsp.role::text,
        tsp.staff_code::text,
        o.name,
        o.role,
        o.staff_code
    FROM public.leads AS l
    JOIN public.agent_profiles AS ap ON ap.id = l.origin_agent_profile_uuid
    LEFT JOIN public.loan_types AS lt ON lt.id = l.product_id
    LEFT JOIN public.staff_profiles AS tsp ON tsp.id = l.assigned_telecaller_profile_uuid
    LEFT JOIN public.auth_users AS tu ON tu.id = tsp.auth_user_uuid
    LEFT JOIN LATERAL (
        SELECT
            nullif(btrim(concat_ws(' ', ou.first_name, ou.last_name)), '') AS name,
            osp.role::text AS role,
            osp.staff_code::text AS staff_code
        FROM public.tasks AS t
        JOIN public.staff_profiles AS osp ON osp.id = t.assigned_employee_profile_uuid
        LEFT JOIN public.auth_users AS ou ON ou.id = osp.auth_user_uuid
        WHERE t.lead_uuid = l.id
          AND t.business_line = l.business_line
          AND t.status::text <> 'cancelled'
        ORDER BY t.created_at DESC, t.id DESC
        LIMIT 1
    ) AS o ON true
    WHERE coalesce(current_setting('app.role', true), '') = 'agent'
      AND coalesce(current_setting('app.auth_user_uuid', true), '') <> ''
      AND coalesce(current_setting('app.agent_profile_uuid', true), '') <> ''
      AND coalesce(current_setting('app.business_line', true), '') <> ''
      AND l.id = ANY (target_lead_uuids)
      AND l.origin_agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true)
      AND ap.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
      AND l.business_line::text = current_setting('app.business_line', true)
$$
"""


def upgrade() -> None:
    op.execute(_FUNCTION_SQL)
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO api_user")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_SIGNATURE} FROM api_user")
    op.execute(f"DROP FUNCTION IF EXISTS {_SIGNATURE}")
