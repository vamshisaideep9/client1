"""Add IST minute windows and item prizes to existing contests."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f4c6a8e0b2d3"
down_revision = "c9e1a3b5d7f2"
branch_labels = None
depends_on = None

CASH_SHAPE = (
    "(audience <> 'team' AND prize_paise BETWEEN 1 AND 1000000000 "
    "AND manager_prize_paise IS NULL AND member_prize_paise IS NULL "
    "AND member_min_contribution IS NULL) "
    "OR (audience = 'team' AND prize_paise IS NULL "
    "AND manager_prize_paise BETWEEN 0 AND 1000000000 "
    "AND member_prize_paise BETWEEN 0 AND 1000000000 "
    "AND manager_prize_paise + member_prize_paise > 0 "
    "AND (member_prize_paise = 0 OR member_min_contribution >= 1))"
)
ITEM_SHAPE = (
    "prize_paise IS NULL AND manager_prize_paise IS NULL AND member_prize_paise IS NULL "
    "AND budget_cap_paise IS NULL AND "
    "((audience <> 'team' AND item_prize IS NOT NULL AND manager_item_prize IS NULL "
    "AND member_item_prize IS NULL) OR "
    "(audience = 'team' AND item_prize IS NULL "
    "AND (manager_item_prize IS NOT NULL OR member_item_prize IS NOT NULL))) "
    "AND (member_min_contribution IS NULL) = (member_item_prize IS NULL)"
)
NO_ITEM = "item_prize IS NULL AND manager_item_prize IS NULL AND member_item_prize IS NULL"
NO_MANUAL_MARK = "paid_marked_by_uuid IS NULL AND paid_marked_at IS NULL AND paid_reference IS NULL"


def _replace(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def _mark_paid_condition(recipient: str) -> str:
    return (
        f"({NO_MANUAL_MARK}) OR ({recipient} AND payment_status = 'paid' "
        "AND paid_marked_at IS NOT NULL)"
    )


def upgrade() -> None:
    op.add_column(
        "contests", sa.Column("start_time", sa.Time(), nullable=False, server_default="00:00")
    )
    op.add_column(
        "contests", sa.Column("end_time", sa.Time(), nullable=False, server_default="23:59")
    )
    op.add_column(
        "contests", sa.Column("prize_kind", sa.String(4), nullable=False, server_default="cash")
    )
    for field in ("item_prize", "manager_item_prize", "member_item_prize"):
        op.add_column("contests", sa.Column(field, postgresql.JSONB()))
    op.add_column("contest_results", sa.Column("item_prize", postgresql.JSONB()))
    op.create_check_constraint(
        op.f("ck_contests_minute_window"),
        "contests",
        "EXTRACT(SECOND FROM start_time) = 0 AND EXTRACT(SECOND FROM end_time) = 0 "
        "AND start_time < TIME '24:00' AND end_time < TIME '24:00' "
        "AND (ends_on > starts_on OR end_time >= start_time)",
    )
    # Keep the historical cash CHECK's NULL behavior for existing rows.
    _replace(
        "contests",
        "ck_contests_prize_shape",
        f"(prize_kind = 'cash' AND ({NO_ITEM}) AND ({CASH_SHAPE})) "
        f"OR (prize_kind = 'item' AND ({ITEM_SHAPE}))",
    )
    for table, fields in (
        ("contests", ("item_prize", "manager_item_prize", "member_item_prize")),
        ("contest_results", ("item_prize",)),
    ):
        op.create_check_constraint(
            op.f(f"ck_{table}_item_prize_shape"),
            table,
            " AND ".join(
                f"({field} IS NULL OR (jsonb_typeof({field}) = 'object' "
                f"AND jsonb_typeof({field}->'label') = 'string' "
                f"AND length(btrim({field}->>'label')) BETWEEN 1 AND 120) IS TRUE)"
                for field in fields
            ),
        )
    _replace(
        "contest_results",
        "ck_contest_results_payment_matches_prize",
        "(payment_status = 'none') = (prize_paise = 0 AND (NOT won OR item_prize IS NULL))",
    )
    _replace(
        "contest_results",
        "ck_contest_results_mark_paid_staff_only",
        _mark_paid_condition("(agent_profile_uuid IS NULL OR item_prize IS NOT NULL)"),
    )
    op.create_check_constraint(
        op.f("ck_contest_results_item_has_no_cash"),
        "contest_results",
        "item_prize IS NULL OR (prize_paise = 0 AND payout_uuid IS NULL "
        "AND payout_txn_uuid IS NULL AND payment_status <> 'payout_pending')",
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'contest_updated'")


def downgrade() -> None:
    # The older API cannot represent these contest rules or fulfill item awards.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM contests WHERE prize_kind = 'item'
                       OR start_time <> TIME '00:00' OR end_time <> TIME '23:59')
                OR EXISTS (SELECT 1 FROM contest_results WHERE item_prize IS NOT NULL)
            THEN RAISE EXCEPTION 'Cannot downgrade while minute windows or item prizes are in use';
            END IF;
        END $$;
        """
    )
    op.execute(
        "UPDATE notifications SET type = 'contest_live' WHERE type::text = 'contest_updated'"
    )
    # Keep the unused PostgreSQL enum value to avoid rewriting the notifications table.
    _replace("contests", "ck_contests_prize_shape", CASH_SHAPE)
    _replace(
        "contest_results",
        "ck_contest_results_payment_matches_prize",
        "(payment_status = 'none') = (prize_paise = 0)",
    )
    _replace(
        "contest_results",
        "ck_contest_results_mark_paid_staff_only",
        _mark_paid_condition("agent_profile_uuid IS NULL"),
    )
    for table, constraint in (
        ("contest_results", "item_has_no_cash"),
        ("contest_results", "item_prize_shape"),
        ("contests", "item_prize_shape"),
        ("contests", "minute_window"),
    ):
        op.drop_constraint(op.f(f"ck_{table}_{constraint}"), table, type_="check")
    op.drop_column("contest_results", "item_prize")
    for field in (
        "item_prize",
        "manager_item_prize",
        "member_item_prize",
        "prize_kind",
        "end_time",
        "start_time",
    ):
        op.drop_column("contests", field)
