"""Erase the deleted person's lead email and remember cleared assignments.

Revision ID: f5b7d9e1a3c4
Revises: e4a6c8d0f2b3

CS-028 adds email under requirement. The existing confined account-closure
function runs before the identity is tombstoned and already authorizes only
the account owner or a platform Admin. Extend it to remove that person's
email from active and historical journeys, selected by their verified mobile
or Client profile. An Agent's third-party prospects are not selected by their
referrer, and financial records retain their existing retention policy.

No table, grant or RLS policy is added. Fixed search path, schema-qualified
relations, PUBLIC revoked and the same api_user EXECUTE grant. The function
also records the current Telecaller when closing clears the assignment.
Downgrade restores the old closure behavior; erased email is never restored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f5b7d9e1a3c4"
down_revision: str | Sequence[str] | None = "e4a6c8d0f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_closure(*, erase_email: bool) -> None:
    extra_updates = ""
    historical_rows = ""
    if erase_email:
        extra_updates = """
            last_telecaller_profile_uuid = coalesce(
                assigned_telecaller_profile_uuid, last_telecaller_profile_uuid
            ),
            requirement = CASE WHEN jsonb_typeof(requirement) = 'object'
                THEN requirement - 'email' ELSE requirement END,
        """
        historical_rows = (
            " OR requirement ? 'email' OR assigned_telecaller_profile_uuid IS NOT NULL"
        )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION close_account_leads(target_auth_user_uuid uuid)
        RETURNS integer AS $$
        DECLARE
            closed_count integer;
        BEGIN
            IF (
                target_auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
                OR (
                    current_setting('app.role', true) = 'admin'
                    AND current_setting('app.platform_scope', true) = 'true'
                )
            ) IS NOT TRUE THEN
                RAISE EXCEPTION 'lead closure is not authorized'
                    USING ERRCODE = '42501';
            END IF;

            UPDATE public.leads
            SET status = 'closed',
                {extra_updates}
                assigned_telecaller_profile_uuid = NULL,
                updated_at = now()
            WHERE (status <> 'closed'{historical_rows})
              AND (
                  mobile = (
                      SELECT auth.mobile
                      FROM public.auth_users AS auth
                      WHERE auth.id = target_auth_user_uuid
                  )
                  OR client_profile_uuid IN (
                      SELECT client.id
                      FROM public.client_profiles AS client
                      WHERE client.auth_user_uuid = target_auth_user_uuid
                  )
              );
            GET DIAGNOSTICS closed_count = ROW_COUNT;
            RETURN closed_count;
        END;
        $$ LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION close_account_leads(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION close_account_leads(uuid) TO api_user")


def upgrade() -> None:
    _replace_closure(erase_email=True)


def downgrade() -> None:
    _replace_closure(erase_email=False)
