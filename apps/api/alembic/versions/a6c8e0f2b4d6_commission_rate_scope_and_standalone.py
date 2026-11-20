"""Narrow rate workflow reads and record standalone Admin entry honestly.

Revision ID: a6c8e0f2b4d6
Revises: f5b7d9e1a3c4

Original Round 2 brief: Agents and staff read approved rates; only the maker
and platform Admin need unpublished workflow rows. Eligible loans/both-line
Telecallers and Employees gain approved-only SELECT, with no write grant or
management endpoint. Sub Admins retain their own workflow and approved rates.

Any recorded checker must differ from the maker, including Admin-created
rows. Direct Admin entry is standalone: approved, with no fabricated checker
or review timestamp. Normalize only old Admin self-checker records; preserve
genuine distinct reviews. The immutable creation time remains the standalone
effective date, and the existing commission_rate_set audit remains intact.

RLS stays enabled and forced, all existing grants/write policies stay intact,
and there is still one head. Downgrade restores the prior SELECT policy and
legacy Admin self-checker convention so its old CHECK remains valid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6c8e0f2b4d6"
down_revision: str | Sequence[str] | None = "f5b7d9e1a3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "product_commission_rates"
_ADMIN = (
    "(current_setting('app.role', true) = 'admin' "
    "AND current_setting('app.platform_scope', true) = 'true')"
)
_SUB_ADMIN = "(current_setting('app.role', true) = 'sub_admin')"
_MAKER = (
    "(current_setting('app.role', true) = 'sub_admin' "
    "AND created_by_role = 'sub_admin' "
    "AND created_by_uuid::text = current_setting('app.auth_user_uuid', true))"
)
_AGENT = (
    "(current_setting('app.role', true) = 'agent' "
    "AND current_setting('app.business_line', true) = 'loans' "
    "AND coalesce(current_setting('app.agent_profile_uuid', true), '') <> '')"
)
_STAFF = (
    "(current_setting('app.role', true) IN ('telecaller', 'employee') "
    "AND current_setting('app.business_line', true) IN ('loans', 'both') "
    "AND coalesce(current_setting('app.staff_profile_uuid', true), '') <> '')"
)
_REVIEWED = "status NOT IN ('approved', 'rejected', 'superseded') "
_HAS_CHECKER = "(checker_uuid IS NOT NULL AND reviewed_at IS NOT NULL)"
_STANDALONE = (
    "(created_by_role = 'admin' AND status IN ('approved', 'superseded') "
    "AND checker_uuid IS NULL AND reviewed_at IS NULL AND review_note IS NULL)"
)


def _drop_checks() -> None:
    for suffix in ("checker_not_maker", "reviewed_has_checker"):
        op.drop_constraint(op.f(f"ck_{_TABLE}_{suffix}"), _TABLE, type_="check")


def _select_policy(predicate: str) -> None:
    op.execute(f"DROP POLICY product_commission_rates_select ON {_TABLE}")
    op.execute(
        f"CREATE POLICY product_commission_rates_select ON {_TABLE} FOR SELECT USING ({predicate})"
    )


def upgrade() -> None:
    _drop_checks()
    op.execute(
        "UPDATE product_commission_rates SET checker_uuid = NULL, reviewed_at = NULL, "
        "review_note = NULL "
        "WHERE created_by_role = 'admin' AND checker_uuid = created_by_uuid"
    )
    op.create_check_constraint(
        op.f("ck_product_commission_rates_checker_not_maker"),
        _TABLE,
        "checker_uuid IS NULL OR checker_uuid <> created_by_uuid",
    )
    op.create_check_constraint(
        op.f("ck_product_commission_rates_reviewed_has_checker"),
        _TABLE,
        f"{_REVIEWED}OR {_HAS_CHECKER} OR {_STANDALONE}",
    )
    _select_policy(
        f"{_ADMIN} OR {_MAKER} OR (status = 'approved' AND ({_SUB_ADMIN} OR {_AGENT} OR {_STAFF}))"
    )


def downgrade() -> None:
    _drop_checks()
    op.execute(
        "UPDATE product_commission_rates SET checker_uuid = created_by_uuid, "
        "reviewed_at = created_at "
        "WHERE created_by_role = 'admin' AND checker_uuid IS NULL "
        "AND status IN ('approved', 'superseded')"
    )
    op.create_check_constraint(
        op.f("ck_product_commission_rates_checker_not_maker"),
        _TABLE,
        "created_by_role <> 'sub_admin' OR checker_uuid IS NULL OR checker_uuid <> created_by_uuid",
    )
    op.create_check_constraint(
        op.f("ck_product_commission_rates_reviewed_has_checker"),
        _TABLE,
        f"{_REVIEWED}OR {_HAS_CHECKER}",
    )
    _select_policy(f"{_ADMIN} OR {_SUB_ADMIN} OR (status = 'approved' AND {_AGENT})")
