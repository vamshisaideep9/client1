"""Remove the Agent read branch from enquiries_rls and site_visits_rls.

Revision ID: b4d6f8a0c2e3
Revises: a1b3d5f7c9e2

Security audit 2026-11-14 (finding #3): both policies admitted
``app.role = 'agent'`` on the same business line, so any Real Estate Agent
could read every client's property enquiry and site-visit request, including
the contact name and mobile, through ``GET /enquiries`` and
``GET /site-visits``. No Agent code path reads either table; Agents work their
own leads through ``leads_rls``.

Change: recreate both policies with the identical predicate minus ``'agent'``
in the line-scoped role list. The platform-Admin branch, the owner branch and
the Telecaller/Employee/Sub Admin line branch are unchanged, because the
Telecaller lead workspace and deal linking, and the Employee vehicle-arrangement
view, read these rows through that branch. The client-facing list routes are
separately narrowed to the caller's own rows in the API.

Grants are unchanged. Rollback restores the previous predicate, including the
Agent branch.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4d6f8a0c2e3"
down_revision: str | Sequence[str] | None = "a1b3d5f7c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_ADMIN = (
    "(current_setting('app.platform_scope', true) = 'true'\n"
    "     AND current_setting('app.role', true) = 'admin')"
)


def _predicate(roles: str) -> str:
    return f"""
    {_SCOPE_ADMIN}
    OR user_uuid::text = current_setting('app.auth_user_uuid', true)
    OR (
        business_line::text = current_setting('app.business_line', true)
        AND current_setting('app.role', true) IN ({roles})
    )
"""


_NEW_ROLES = "'telecaller', 'employee', 'sub_admin'"
_OLD_ROLES = "'telecaller', 'employee', 'sub_admin', 'agent'"
_POLICIES = (("enquiries", "enquiries_rls"), ("site_visits", "site_visits_rls"))


def _replace(roles: str) -> None:
    predicate = _predicate(roles)
    for table, policy in _POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
            FOR ALL
            USING ({predicate})
            WITH CHECK ({predicate});
            """
        )


def upgrade() -> None:
    _replace(_NEW_ROLES)


def downgrade() -> None:
    _replace(_OLD_ROLES)
