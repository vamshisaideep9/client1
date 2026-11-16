"""Erase personalization preferences that do not belong to a Client.

Revision ID: d6f8a0b2c4e7
Revises: c5e7a9b1d3f4

2026-11-16 product decision CS-021 (amends CS-008): the consent switch and
the coarse-location settings are Client-only. ``GET/PATCH /preferences`` and
``PUT/DELETE /location`` now return 403 for every other role, and placements
ignore any preference that is not a Client's. A row left behind for an Agent
or staff account would keep an unreachable consent (and possibly a coarse
location point) on file that its owner can no longer see or withdraw, so it
is erased here.

"Not a Client" follows the login role resolution in
``auth_service._build_access_claims``: an account with an active staff profile is
staff, otherwise one with an active agent profile is an Agent, otherwise it is
a Client. Accounts whose only staff/agent profile is inactive keep their row,
because they sign in as a Client.

The table is owner-only under RLS for ``api_user`` (ENABLE, not FORCE), and
this statement runs as the migration owner, the same way the original
migration ``c9d0e1f2a3b4`` created it. No grant, policy or function changes:
``erase_personalization_preference`` and the owner policies stay as they are.

Downgrade is a no-op: an erased consent or location point is not restored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6f8a0b2c4e7"
down_revision: str | Sequence[str] | None = "c5e7a9b1d3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Kept as a constant so a test can run the exact statement in a rolled-back
# transaction against seeded rows.
DELETE_NON_CLIENT_PREFERENCES = """
DELETE FROM personalization_preferences AS preference
WHERE EXISTS (
    SELECT 1 FROM staff_profiles AS staff
    WHERE staff.auth_user_uuid = preference.auth_user_uuid
      AND staff.status = 'active'
)
OR EXISTS (
    SELECT 1 FROM agent_profiles AS agent
    WHERE agent.auth_user_uuid = preference.auth_user_uuid
      AND agent.status = 'active'
)
"""


def upgrade() -> None:
    op.execute(DELETE_NON_CLIENT_PREFERENCES)


def downgrade() -> None:
    # Erased preferences are not restored (see the module docstring).
    pass
