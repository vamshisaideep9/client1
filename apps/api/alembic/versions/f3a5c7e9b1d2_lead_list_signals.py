"""Expose a lead's referral code and latest call outcome to its own staff.

Revision ID: f3a5c7e9b1d2
Revises: c7e9a1b3d5f7

Telecaller and Employee lead lists filter by "who referred this lead" and by
the latest call outcome / interest level. Two of those facts sit behind RLS
the caller cannot pass:

* ``referrals`` / ``referral_codes`` are readable only by the referrer and a
  platform Admin, so staff cannot see which client code brought a lead in;
* ``lead_activities`` are readable only by the telecaller who logged them, so
  an Employee working a lead's task cannot see how its last call went.

Rather than widening either policy (which would expose referred mobiles,
reward state and call notes), ``lead_list_signals`` is one confined
SECURITY DEFINER read in the shape of ``erase_agent_payout_details``. It
re-checks the caller itself and returns only four narrow columns:

* the lead must be on the request's business line, and either assigned to the
  calling Telecaller or carry a task the calling Employee raised or holds;
* the referral code only (never the referrer's identity, the referred mobile,
  conversion or reward state);
* the latest call's disposition and interest level only (never notes or
  follow-up times). A Telecaller still sees only calls they logged, exactly as
  ``lead_activities`` RLS already allows; an Employee sees the lead's latest
  call by anyone.

Any other role, a missing staff profile or an unset business line returns no
rows. No table, grant or policy changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a5c7e9b1d2"
down_revision: str | Sequence[str] | None = "c7e9a1b3d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN = "lead_list_signals"
_MAX_LEADS = 1000


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_FN}(p_lead_uuids uuid[])
        RETURNS TABLE (
            lead_uuid uuid,
            client_referral_code text,
            last_disposition text,
            last_interest_level text
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        #variable_conflict use_column
        DECLARE
            v_role text := coalesce(current_setting('app.role', true), '');
            v_staff text := coalesce(current_setting('app.staff_profile_uuid', true), '');
            v_line text := coalesce(current_setting('app.business_line', true), '');
        BEGIN
            IF v_role NOT IN ('telecaller', 'employee') OR v_staff = '' OR v_line = '' THEN
                RETURN;
            END IF;
            IF coalesce(array_length(p_lead_uuids, 1), 0) > {_MAX_LEADS} THEN
                RAISE EXCEPTION 'too many leads requested' USING ERRCODE = '22023';
            END IF;

            RETURN QUERY
            WITH visible AS (
                SELECT l.id, l.mobile, l.client_profile_uuid
                FROM public.leads AS l
                WHERE l.id = ANY (p_lead_uuids)
                  AND l.business_line::text = v_line
                  AND (
                      (
                          v_role = 'telecaller'
                          AND l.assigned_telecaller_profile_uuid IS NOT NULL
                          AND l.assigned_telecaller_profile_uuid::text = v_staff
                      )
                      OR (
                          v_role = 'employee'
                          AND EXISTS (
                              SELECT 1
                              FROM public.tasks AS t
                              WHERE t.lead_uuid = l.id
                                AND t.business_line::text = v_line
                                AND (
                                    t.raised_by_staff_profile_uuid::text = v_staff
                                    OR t.assigned_employee_profile_uuid::text = v_staff
                                )
                          )
                      )
                  )
            )
            SELECT
                v.id,
                (
                    SELECT rc.code
                    FROM public.referrals AS r
                    JOIN public.referral_codes AS rc
                      ON rc.auth_user_uuid = r.referrer_auth_user_uuid
                    WHERE r.referred_lead_uuid = v.id
                       OR r.referred_mobile = v.mobile
                       OR (
                           r.referred_auth_user_uuid IS NOT NULL
                           AND r.referred_auth_user_uuid = (
                               SELECT cp.auth_user_uuid
                               FROM public.client_profiles AS cp
                               WHERE cp.id = v.client_profile_uuid
                           )
                       )
                    ORDER BY r.created_at DESC
                    LIMIT 1
                ),
                last_call.disposition::text,
                last_call.interest_level::text
            FROM visible AS v
            LEFT JOIN LATERAL (
                SELECT a.disposition, a.interest_level
                FROM public.lead_activities AS a
                WHERE a.lead_uuid = v.id
                  AND (v_role = 'employee' OR a.telecaller_staff_profile_uuid::text = v_staff)
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 1
            ) AS last_call ON true;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {_FN}(uuid[]) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FN}(uuid[]) TO api_user")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FN}(uuid[]) FROM api_user")
    op.execute(f"DROP FUNCTION IF EXISTS {_FN}(uuid[])")
