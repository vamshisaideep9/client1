"""Agent dashboard: commission ledger, payout trail, lead history, cancelled cheque.

Revision ID: e8b0d2f4a6c9
Revises: d6f8a0b2c4e7

2026-11-16 product decision (CS-022, batch B of the stakeholder feedback): an
Agent sees each commission with its client and deal, the payout trail behind a
commission transaction, and the full history of a lead they introduced. An
Agent may also attach an optional cancelled cheque to their saved payout
details, which payout makers can view (audited).

Why confined functions and not new SELECT policies
--------------------------------------------------
The Agent needs a narrow read of loan applications, service enquiries,
property deals, enquiries, site visits, call logs, catalogue names, the audit
trail and the payout behind their own ledger rows. A PERMISSIVE SELECT policy
on those tables would also feed the RLS-only routes that serve full rows to any
caller (``GET /loans/applications``, ``GET /loans/enquiries``,
``GET /property-deals``): an Agent would receive the applicant's form answers,
status reasons and rates. So, as with ``lead_list_signals``, the reach lives in
three SECURITY DEFINER read functions that re-check the caller and return only
the projected columns. No table policy or grant changes; payouts and the audit
log stay Admin-only under RLS.

Reach (each function checks it on every call):

- the request role is ``agent`` with a non-empty Agent profile, account and
  business line;
- ``agent_commission_ledger()``: commissions keyed to the caller's account,
  Agent profile and line (stricter than ``commissions_select``), with the
  lead, the linked loan application or property deal, product, bank, property
  title/category and the settled ledger row's timestamp;
- ``agent_lead_history(uuid)``: only a lead the calling Agent introduced
  (``origin_agent_profile_uuid``) on the request's line, whose Agent profile
  belongs to the calling account. Sub-rows must share the lead's line. Notes,
  amounts and staff names are returned to the API, which applies the Admin
  field rules before responding; status reasons, rates, fees, form answers,
  contact details and messages are never returned;
- ``agent_transaction_detail(uuid)``: a transaction owned by the calling
  account, the payout that produced or reversed it (recipient must be the
  caller) and the commission it paid (caller's account and line). Maker and
  checker appear as display name and staff role; the gateway ids, idempotency
  key, reference fingerprint and failure text are never returned.

Cancelled cheque: ``agent_payout_details`` gains three nullable columns, set
together, with a closed content-type set. Owner RLS on the table is unchanged.

Rollback drops the functions and the cheque columns. Stored cheque objects stay
in private storage under ``private/agent-payout-cheques/`` (the earlier code has
no sweep for that prefix), so remove that prefix after a rollback.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8b0d2f4a6c9"
down_revision: str | Sequence[str] | None = "d6f8a0b2c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_payout_details"
_FUNCTIONS = (
    "agent_commission_ledger()",
    "agent_lead_history(uuid)",
    "agent_transaction_detail(uuid)",
)
# Bounded sections: a lead's history is small in practice; the caps keep one
# response bounded even for a long-running lead.
_HISTORY_CAP = 100
_CALL_CAP = 200

_AGENT_CONTEXT = """
    coalesce(current_setting('app.role', true), '') = 'agent'
    AND coalesce(current_setting('app.auth_user_uuid', true), '') <> ''
    AND coalesce(current_setting('app.agent_profile_uuid', true), '') <> ''
    AND coalesce(current_setting('app.business_line', true), '') <> ''
"""

_LEDGER_SQL = f"""
CREATE FUNCTION agent_commission_ledger()
RETURNS TABLE (
    commission_uuid uuid,
    business_line text,
    deal_type text,
    deal_uuid uuid,
    agreed_amount_paise bigint,
    commission_status text,
    payout_txn_uuid uuid,
    created_at timestamptz,
    paid_at timestamptz,
    lead_uuid uuid,
    lead_name text,
    lead_status text,
    lead_agent_expired_at timestamptz,
    product_uuid uuid,
    product_label text,
    bank_uuid uuid,
    bank_name text,
    property_uuid uuid,
    property_title text,
    property_category text,
    deal_status text,
    deal_amount text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT
        c.id,
        c.business_line::text,
        CASE WHEN c.loan_application_uuid IS NOT NULL
             THEN 'loan_application' ELSE 'property_deal' END,
        coalesce(c.loan_application_uuid, c.property_deal_uuid),
        c.agreed_amount_paise,
        c.status::text,
        c.payout_txn_uuid,
        c.created_at,
        txn.created_at,
        l.id,
        l.name,
        l.status::text,
        l.agent_expired_at,
        la.loan_type_id,
        lt.label,
        la.bank_id,
        b.name,
        pd.property_id,
        p.title,
        p.category,
        coalesce(la.status::text, pd.status::text),
        CASE WHEN la.id IS NOT NULL
             THEN coalesce(la.amount_sanctioned, la.amount_requested)::text
             ELSE pd.price_quoted::text END
    FROM public.commissions AS c
    JOIN public.leads AS l ON l.id = c.lead_uuid
    LEFT JOIN public.loan_applications AS la
      ON la.id = c.loan_application_uuid AND la.lead_uuid = c.lead_uuid
    LEFT JOIN public.loan_types AS lt ON lt.id = la.loan_type_id
    LEFT JOIN public.banks AS b ON b.id = la.bank_id
    LEFT JOIN public.property_deals AS pd
      ON pd.id = c.property_deal_uuid AND pd.lead_uuid = c.lead_uuid
    LEFT JOIN public.properties AS p ON p.id = pd.property_id
    LEFT JOIN public.transactions AS txn
      ON txn.id = c.payout_txn_uuid AND txn.user_uuid = c.agent_auth_user_uuid
    WHERE {_AGENT_CONTEXT}
      AND c.agent_auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
      AND c.agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true)
      AND c.business_line::text = current_setting('app.business_line', true)
    ORDER BY c.created_at DESC, c.id
$$
"""

_HISTORY_SQL = f"""
CREATE FUNCTION agent_lead_history(target_lead_uuid uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_lead public.leads%ROWTYPE;
    v_line text;
    v_request_ids uuid[];
BEGIN
    IF NOT ({_AGENT_CONTEXT}) THEN
        RETURN NULL;
    END IF;

    SELECT l.* INTO v_lead
    FROM public.leads AS l
    JOIN public.agent_profiles AS ap ON ap.id = l.origin_agent_profile_uuid
    WHERE l.id = target_lead_uuid
      AND l.origin_agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true)
      AND ap.auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
      AND l.business_line::text = current_setting('app.business_line', true);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    v_line := v_lead.business_line::text;

    SELECT coalesce(array_agg(x.id), ARRAY[]::uuid[]) INTO v_request_ids
    FROM (
        SELECT la.id FROM public.loan_applications AS la
        WHERE la.lead_uuid = v_lead.id AND la.business_line::text = v_line
        UNION ALL
        SELECT pd.id FROM public.property_deals AS pd
        WHERE pd.lead_uuid = v_lead.id AND pd.business_line::text = v_line
    ) AS x;

    RETURN jsonb_build_object(
        'applications', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT la.opened_at AS sort_at, jsonb_build_object(
                    'id', la.id,
                    'product_label', lt.label,
                    'bank_name', b.name,
                    'status', la.status::text,
                    'amount_requested', la.amount_requested::text,
                    'amount_sanctioned', la.amount_sanctioned::text,
                    'opened_at', la.opened_at,
                    'closed_at', la.closed_at,
                    'disbursed_at', la.disbursed_at
                ) AS item
                FROM public.loan_applications AS la
                LEFT JOIN public.loan_types AS lt ON lt.id = la.loan_type_id
                LEFT JOIN public.banks AS b ON b.id = la.bank_id
                WHERE la.lead_uuid = v_lead.id AND la.business_line::text = v_line
                ORDER BY la.opened_at DESC
                LIMIT {_HISTORY_CAP}
            ) AS s
        ),
        'service_enquiries', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT e.submitted_at AS sort_at, jsonb_build_object(
                    'id', e.id,
                    'product_label', lt.label,
                    'product_category', e.product_category,
                    'status', e.status,
                    'submitted_at', e.submitted_at
                ) AS item
                FROM public.financial_service_enquiries AS e
                LEFT JOIN public.loan_types AS lt ON lt.id = e.product_id
                WHERE e.lead_uuid = v_lead.id AND e.business_line::text = v_line
                ORDER BY e.submitted_at DESC
                LIMIT {_HISTORY_CAP}
            ) AS s
        ),
        'deals', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT pd.opened_at AS sort_at, jsonb_build_object(
                    'id', pd.id,
                    'property_title', p.title,
                    'property_category', p.category,
                    'status', pd.status::text,
                    'price_quoted', pd.price_quoted::text,
                    'booking_amount', pd.booking_amount::text,
                    'opened_at', pd.opened_at,
                    'closed_at', pd.closed_at
                ) AS item
                FROM public.property_deals AS pd
                LEFT JOIN public.properties AS p ON p.id = pd.property_id
                WHERE pd.lead_uuid = v_lead.id AND pd.business_line::text = v_line
                ORDER BY pd.opened_at DESC
                LIMIT {_HISTORY_CAP}
            ) AS s
        ),
        'enquiries', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT q.created_at AS sort_at, jsonb_build_object(
                    'id', q.id,
                    'title', q.title,
                    'locality', q.locality,
                    'city', q.city,
                    'status', q.status::text,
                    'created_at', q.created_at
                ) AS item
                FROM public.enquiries AS q
                WHERE q.lead_uuid = v_lead.id AND q.business_line::text = v_line
                ORDER BY q.created_at DESC
                LIMIT {_HISTORY_CAP}
            ) AS s
        ),
        'site_visits', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT v.created_at AS sort_at, jsonb_build_object(
                    'id', v.id,
                    'title', v.title,
                    'locality', v.locality,
                    'city', v.city,
                    'preferred_date', v.preferred_date,
                    'preferred_time_slot', v.preferred_time_slot::text,
                    'status', v.status::text,
                    'created_at', v.created_at
                ) AS item
                FROM public.site_visits AS v
                WHERE v.lead_uuid = v_lead.id AND v.business_line::text = v_line
                ORDER BY v.created_at DESC
                LIMIT {_HISTORY_CAP}
            ) AS s
        ),
        'calls', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at DESC), '[]'::jsonb)
            FROM (
                SELECT a.created_at AS sort_at, jsonb_build_object(
                    'id', a.id,
                    'disposition', a.disposition::text,
                    'interest_level', a.interest_level::text,
                    'notes', a.notes,
                    'follow_up_at', a.follow_up_at,
                    'created_at', a.created_at,
                    'staff_name', nullif(btrim(concat_ws(' ', u.first_name, u.last_name)), '')
                ) AS item
                FROM public.lead_activities AS a
                LEFT JOIN public.staff_profiles AS sp ON sp.id = a.telecaller_staff_profile_uuid
                LEFT JOIN public.auth_users AS u ON u.id = sp.auth_user_uuid
                WHERE a.lead_uuid = v_lead.id AND a.business_line::text = v_line
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT {_CALL_CAP}
            ) AS s
        ),
        'timeline', (
            SELECT coalesce(jsonb_agg(s.item ORDER BY s.sort_at), '[]'::jsonb)
            FROM (
                SELECT al.created_at AS sort_at, jsonb_build_object(
                    'event', al.action::text,
                    'at', al.created_at,
                    'request_id', CASE WHEN al.entity_type = 'lead' THEN NULL
                                       ELSE al.entity_uuid END,
                    'from_status', CASE
                        WHEN al.action::text = 'team_lead_status_updated' THEN al.detail ->> 'from'
                        WHEN al.action::text IN (
                            'loan_application_updated', 'property_deal_updated',
                            'agent_lead_expired'
                        ) THEN al.detail ->> 'previous_status'
                        ELSE NULL END,
                    'to_status', CASE
                        WHEN al.action::text = 'team_lead_status_updated' THEN al.detail ->> 'to'
                        WHEN al.action::text IN (
                            'loan_application_updated', 'property_deal_updated'
                        ) THEN al.detail ->> 'status'
                        ELSE NULL END
                ) AS item
                FROM public.audit_log AS al
                WHERE (
                        al.entity_type = 'lead'
                        AND al.entity_uuid = v_lead.id
                        AND al.action::text IN (
                            'lead_assigned', 'agent_lead_expired', 'agent_lead_resubmitted',
                            'team_lead_status_updated', 'team_lead_reassigned'
                        )
                    )
                   OR (
                        al.entity_type IN ('loan_application', 'property_deal')
                        AND al.entity_uuid = ANY (v_request_ids)
                        AND al.action::text IN ('loan_application_updated', 'property_deal_updated')
                        AND (al.detail ->> 'status') IS DISTINCT FROM
                            (al.detail ->> 'previous_status')
                    )
                ORDER BY al.created_at DESC
                LIMIT {_CALL_CAP}
            ) AS s
        )
    );
END;
$$
"""

_TRANSACTION_SQL = f"""
CREATE FUNCTION agent_transaction_detail(target_transaction_uuid uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_txn public.transactions%ROWTYPE;
    v_payout public.payouts%ROWTYPE;
    v_payout_json jsonb := NULL;
    v_items jsonb := '[]'::jsonb;
BEGIN
    IF NOT ({_AGENT_CONTEXT}) THEN
        RETURN NULL;
    END IF;

    SELECT t.* INTO v_txn
    FROM public.transactions AS t
    WHERE t.id = target_transaction_uuid
      AND t.user_uuid IS NOT NULL
      AND t.user_uuid::text = current_setting('app.auth_user_uuid', true);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT p.* INTO v_payout
    FROM public.payouts AS p
    WHERE (p.ledger_transaction_id = v_txn.id OR p.reversal_transaction_id = v_txn.id)
      AND p.recipient_user_uuid IS NOT NULL
      AND p.recipient_user_uuid::text = current_setting('app.auth_user_uuid', true)
    ORDER BY p.created_at DESC
    LIMIT 1;

    IF FOUND THEN
        v_payout_json := jsonb_build_object(
            'status', v_payout.status::text,
            'method', v_payout.destination_type::text,
            'provider', v_payout.provider::text,
            'destination_hint', v_payout.destination_hint,
            'requested_at', v_payout.created_at,
            'approved_at', (
                SELECT min(al.created_at) FROM public.audit_log AS al
                WHERE al.entity_type = 'payout'
                  AND al.entity_uuid = v_payout.id
                  AND al.action::text = 'payout_approved'
            ),
            'issued_at', v_payout.manual_issued_at,
            'paid_at', (
                SELECT t.created_at FROM public.transactions AS t
                WHERE t.id = v_payout.ledger_transaction_id
            ),
            'reversed_at', (
                SELECT t.created_at FROM public.transactions AS t
                WHERE t.id = v_payout.reversal_transaction_id
            ),
            'maker', (
                SELECT jsonb_build_object(
                    'name', nullif(btrim(concat_ws(' ', u.first_name, u.last_name)), ''),
                    'role', (
                        SELECT sp.role::text FROM public.staff_profiles AS sp
                        WHERE sp.auth_user_uuid = u.id
                          AND sp.role::text IN ('admin', 'sub_admin')
                        ORDER BY (sp.role::text = 'admin') DESC, sp.created_at
                        LIMIT 1
                    )
                )
                FROM public.auth_users AS u WHERE u.id = v_payout.maker_user_uuid
            ),
            'checker', (
                SELECT jsonb_build_object(
                    'name', nullif(btrim(concat_ws(' ', u.first_name, u.last_name)), ''),
                    'role', (
                        SELECT sp.role::text FROM public.staff_profiles AS sp
                        WHERE sp.auth_user_uuid = u.id
                          AND sp.role::text IN ('admin', 'sub_admin')
                        ORDER BY (sp.role::text = 'admin') DESC, sp.created_at
                        LIMIT 1
                    )
                )
                FROM public.auth_users AS u WHERE u.id = v_payout.checker_user_uuid
            )
        );

        SELECT coalesce(jsonb_agg(jsonb_build_object(
            'commission_id', c.id,
            'amount_paise', c.agreed_amount_paise,
            'status', c.status::text,
            'deal_type', CASE WHEN c.loan_application_uuid IS NOT NULL
                              THEN 'loan_application' ELSE 'property_deal' END,
            'deal_uuid', coalesce(c.loan_application_uuid, c.property_deal_uuid),
            'lead_uuid', l.id,
            'lead_name', l.name,
            'product_label', lt.label,
            'bank_name', b.name,
            'property_title', pr.title,
            'deal_status', coalesce(la.status::text, pd.status::text),
            'deal_amount', CASE WHEN la.id IS NOT NULL
                                THEN coalesce(la.amount_sanctioned, la.amount_requested)::text
                                ELSE pd.price_quoted::text END,
            'entered_at', c.created_at
        ) ORDER BY c.created_at), '[]'::jsonb) INTO v_items
        FROM public.commissions AS c
        JOIN public.leads AS l ON l.id = c.lead_uuid
        LEFT JOIN public.loan_applications AS la
          ON la.id = c.loan_application_uuid AND la.lead_uuid = c.lead_uuid
        LEFT JOIN public.loan_types AS lt ON lt.id = la.loan_type_id
        LEFT JOIN public.banks AS b ON b.id = la.bank_id
        LEFT JOIN public.property_deals AS pd
          ON pd.id = c.property_deal_uuid AND pd.lead_uuid = c.lead_uuid
        LEFT JOIN public.properties AS pr ON pr.id = pd.property_id
        WHERE (c.payout_uuid = v_payout.id OR c.payout_txn_uuid = v_txn.id)
          AND c.agent_auth_user_uuid::text = current_setting('app.auth_user_uuid', true)
          AND c.agent_profile_uuid::text = current_setting('app.agent_profile_uuid', true)
          AND c.business_line::text = current_setting('app.business_line', true);
    END IF;

    RETURN jsonb_build_object('payout', v_payout_json, 'items', v_items);
END;
$$
"""


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("cheque_object_key", sa.String(length=300), nullable=True))
    op.add_column(_TABLE, sa.Column("cheque_content_type", sa.String(length=40), nullable=True))
    op.add_column(
        _TABLE, sa.Column("cheque_uploaded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_agent_payout_details_cheque_fields_pair"),
        _TABLE,
        "(cheque_object_key IS NULL) = (cheque_content_type IS NULL) "
        "AND (cheque_object_key IS NULL) = (cheque_uploaded_at IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_agent_payout_details_cheque_content_type_allowed"),
        _TABLE,
        "cheque_content_type IS NULL "
        "OR cheque_content_type IN ('image/jpeg', 'image/png', 'application/pdf')",
    )

    for statement in (_LEDGER_SQL, _HISTORY_SQL, _TRANSACTION_SQL):
        op.execute(statement)
    for signature in _FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO api_user")


def downgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM api_user")
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.drop_constraint(
        op.f("ck_agent_payout_details_cheque_content_type_allowed"), _TABLE, type_="check"
    )
    op.drop_constraint(op.f("ck_agent_payout_details_cheque_fields_pair"), _TABLE, type_="check")
    op.drop_column(_TABLE, "cheque_uploaded_at")
    op.drop_column(_TABLE, "cheque_content_type")
    op.drop_column(_TABLE, "cheque_object_key")
