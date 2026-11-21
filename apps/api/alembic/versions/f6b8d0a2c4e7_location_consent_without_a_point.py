"""Location consent without a saved point (CS-026).

Revision ID: f6b8d0a2c4e7
Revises: e5a7c9b1d3f6

CS-026 lets a consenting Client's profile pincode drive location-based
campaign targeting, but only behind the separate, revocable location consent
that CS-008 introduced (``location_enabled`` + ``location_consented_at``).
That consent could previously exist only together with a captured coarse
point. A Client may now give it with no point at all, so the profile pincode
alone is used.

``ck_personalization_preferences_location_consistent`` changes from
"consent iff a point" to:

- no consent: no consent time and no point (unchanged);
- consent: a consent time, and the point (latitude, longitude, captured
  time) either complete or entirely absent.

``location_requires_personalization`` is unchanged, so location consent still
cannot outlive personalization consent. No grant, policy or column changes.

Rollback restores the old rule. Rows holding location consent without a point
would violate it, so the downgrade first withdraws that consent (sets
``location_enabled`` false and clears the consent time); those Clients would
need to give it again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6b8d0a2c4e7"
down_revision: str | Sequence[str] | None = "e5a7c9b1d3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "personalization_preferences"
_NAME = "ck_personalization_preferences_location_consistent"

_OLD = (
    "(NOT location_enabled AND latitude_e2 IS NULL AND longitude_e2 IS NULL "
    "AND location_captured_at IS NULL AND location_consented_at IS NULL) OR "
    "(location_enabled AND latitude_e2 IS NOT NULL AND longitude_e2 IS NOT NULL "
    "AND location_captured_at IS NOT NULL AND location_consented_at IS NOT NULL)"
)
_NEW = (
    "(NOT location_enabled AND latitude_e2 IS NULL AND longitude_e2 IS NULL "
    "AND location_captured_at IS NULL AND location_consented_at IS NULL) OR "
    "(location_enabled AND location_consented_at IS NOT NULL AND ("
    "(latitude_e2 IS NOT NULL AND longitude_e2 IS NOT NULL "
    "AND location_captured_at IS NOT NULL) OR "
    "(latitude_e2 IS NULL AND longitude_e2 IS NULL AND location_captured_at IS NULL)))"
)


def upgrade() -> None:
    # op.f(): the name is already final, so the metadata naming convention
    # must not prefix it a second time.
    op.drop_constraint(op.f(_NAME), _TABLE, type_="check")
    op.create_check_constraint(op.f(_NAME), _TABLE, _NEW)


def downgrade() -> None:
    op.execute(
        f"UPDATE {_TABLE} SET location_enabled = false, location_consented_at = NULL "
        "WHERE location_enabled AND latitude_e2 IS NULL"
    )
    op.drop_constraint(op.f(_NAME), _TABLE, type_="check")
    op.create_check_constraint(op.f(_NAME), _TABLE, _OLD)
