"""Keep covered commission membership and expose a scoped payment trail.

Revision ID: c9e1a3b5d7f2
Revises: b7d9f1a3c5e7
"""

import sqlalchemy as sa

from alembic import op

revision = "c9e1a3b5d7f2"
down_revision = "b7d9f1a3c5e7"
branch_labels = None
depends_on = None

_AGENT_FUNCTION = "public.agent_transaction_detail(uuid)"
_OLD_ITEM_QUERY = "WHERE (c.payout_uuid = v_payout.id OR c.payout_txn_uuid = v_txn.id)"
_NEW_ITEM_QUERY = """LEFT JOIN public.commission_payout_items AS i
          ON i.payout_uuid = v_payout.id AND i.commission_uuid = c.id
        WHERE (i.payout_uuid IS NOT NULL
               OR c.payout_uuid = v_payout.id OR c.payout_txn_uuid = v_txn.id)
          AND c.business_line = v_payout.business_line"""
_AGENT_REPLACEMENTS = (
    (
        "'destination_hint', v_payout.destination_hint,",
        """'destination_hint', v_payout.destination_hint,
            'reference', CASE WHEN v_payout.gateway_payout_id ~ '^pout_[A-Za-z0-9]+$'
                              THEN v_payout.gateway_payout_id END,""",
    ),
    (_OLD_ITEM_QUERY, _NEW_ITEM_QUERY),
    (
        "'amount_paise', c.agreed_amount_paise",
        "'amount_paise', coalesce(i.amount_paise, c.agreed_amount_paise)",
    ),
    (
        "'status', c.status::text",
        "'status', CASE WHEN i.payout_uuid IS NOT NULL THEN 'paid' ELSE c.status::text END",
    ),
    ("ORDER BY c.created_at)", "ORDER BY c.created_at, c.id)"),
)

_TRAIL_SQL = """
CREATE FUNCTION public.transaction_payment_trail(target_transaction_uuid uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT jsonb_build_object(
        'status', p.status::text,
        'method', p.destination_type::text,
        'destination_hint', p.destination_hint,
        'reference', CASE WHEN p.gateway_payout_id ~ '^pout_[A-Za-z0-9]+$'
                          THEN p.gateway_payout_id END,
        'requested_at', p.created_at,
        'approved_at', (
            SELECT min(a.created_at) FROM public.audit_log AS a
            WHERE a.entity_type = 'payout' AND a.entity_uuid = p.id
              AND a.action::text = 'payout_approved'
        ),
        'issued_at', p.manual_issued_at,
        'paid_at', paid.created_at,
        'reversed_at', reversed.created_at
    )
    FROM public.transactions AS t
    JOIN public.payouts AS p
      ON (p.ledger_transaction_id = t.id OR p.reversal_transaction_id = t.id)
     AND p.recipient_user_uuid = t.user_uuid
     AND p.business_line = t.business_line AND p.type::text = t.type::text
    LEFT JOIN public.transactions AS paid
      ON paid.id = p.ledger_transaction_id AND paid.user_uuid = t.user_uuid
     AND paid.business_line = t.business_line AND paid.type = t.type
    LEFT JOIN public.transactions AS reversed
      ON reversed.id = p.reversal_transaction_id AND reversed.user_uuid = t.user_uuid
     AND reversed.business_line = t.business_line AND reversed.type = t.type
    WHERE t.id = target_transaction_uuid
      AND (t.user_uuid::text = current_setting('app.auth_user_uuid', true)
           OR (current_setting('app.platform_scope', true) = 'true'
               AND current_setting('app.role', true) = 'admin'))
    ORDER BY p.created_at DESC, p.id
    LIMIT 1;
$$
"""


def _replace_agent_query(*, reverse: bool = False) -> None:
    definition = (
        op.get_bind()
        .execute(
            sa.text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
            {"signature": _AGENT_FUNCTION},
        )
        .scalar_one()
    )
    for old, new in _AGENT_REPLACEMENTS:
        if reverse:
            old, new = new, old
        if definition.count(old) != 1:
            raise RuntimeError("Unexpected Agent transaction function definition.")
        definition = definition.replace(old, new, 1)
    op.execute(definition)


def upgrade() -> None:
    op.create_table(
        "commission_payout_items",
        sa.Column(
            "payout_uuid",
            sa.Uuid(),
            sa.ForeignKey("payouts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "commission_uuid",
            sa.Uuid(),
            sa.ForeignKey("commissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount_paise > 0", name="ck_commission_payout_items_positive_amount"),
    )
    op.create_index(
        "ix_commission_payout_items_commission_uuid", "commission_payout_items", ["commission_uuid"]
    )
    op.execute("""
        INSERT INTO commission_payout_items (payout_uuid, commission_uuid, amount_paise)
        SELECT p.id, c.id, c.agreed_amount_paise
        FROM commissions AS c
        JOIN payouts AS p
          ON (p.id = c.payout_uuid OR p.ledger_transaction_id = c.payout_txn_uuid)
         AND p.type::text = 'commission'
         AND (p.recipient_user_uuid = c.agent_auth_user_uuid
              OR (p.recipient_user_uuid IS NULL AND p.retained_ref = c.agent_auth_user_uuid::text))
         AND p.business_line = c.business_line
        """)
    op.execute("ALTER TABLE commission_payout_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE commission_payout_items FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT ON commission_payout_items TO api_user")
    op.execute("""
        CREATE POLICY commission_payout_items_select ON commission_payout_items
        FOR SELECT USING (current_setting('app.role', true) = 'admin'
                         AND current_setting('app.platform_scope', true) = 'true')
        """)
    _replace_agent_query()
    op.execute(_TRAIL_SQL)
    op.execute("REVOKE ALL ON FUNCTION public.transaction_payment_trail(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.transaction_payment_trail(uuid) TO api_user")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.transaction_payment_trail(uuid)")
    _replace_agent_query(reverse=True)
    op.drop_table("commission_payout_items")
