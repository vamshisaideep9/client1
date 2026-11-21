"""Lead signals gain products, banks, property facets and a transaction summary.

Revision ID: f1b3d5a7c9e2
Revises: e8b0d2f4a6c9

2026-11-16 product decision (CS-023, batch C of the stakeholder feedback):
every lead list filters by financial product, bank, loan or deal status,
property category and subtype, and the Telecaller list also filters by the
loan transactions the Telecaller recorded (has a transaction or not, date
range, bank, amount range). Agent analytics filter by the same product facets.

The lists filter rows that are already loaded, so the facts travel with each
row. They come from the two confined readers the lists already use, now
returning more columns:

``lead_list_signals(uuid[])`` (Telecaller, Employee and, new, Agent):

- caller checks are unchanged for Telecaller (the lead is assigned to them)
  and Employee (they raised or hold a task on it), on the request's line. An
  Agent gets only leads they introduced (``origin = agent`` and
  ``origin_agent_profile_uuid`` = the request's Agent profile, whose account
  is the caller), on the request's line — the reach of
  ``agent_lead_history``. Any other role, a missing profile or an unset line
  returns no rows;
- new columns: ``loan_items`` — one entry per loan application on the lead's
  line (id, loan type id and label, bank id and name, status, requested
  amount) — and ``deal_items`` — one entry per property deal (id, status, the
  property's category and subtype, quoted price). One entry per application
  or deal lets a filter combine product, bank, status and amount on the same
  application. These are values the callers already read today (Telecaller
  and Employee through ``loan_applications`` / ``property_deals`` RLS and the
  public catalogue, Agents through ``agent_lead_history``); the API returns
  ids, labels and enums to the browser and uses the amounts only server-side,
  for analytics filters, after checking the Admin's field rules;
- a loan-transaction summary (count, distinct bank names, min/max amount,
  first/last date, and the latest 50 transactions' date, bank and amount so
  one transaction can be required to match every transaction filter) for the
  assigned Telecaller only, which is exactly the reach of
  ``loan_txn_history`` RLS. Employees and Agents cannot read that table and
  get NULLs. The API then applies the Admin's Telecaller field rules
  (``loan_transaction.bank_name`` / ``amount`` / ``txn_date``) before any
  value leaves the server;
- an Agent never receives the client referral code or call outcomes.

``team_lead_signals(uuid[])`` (Sub Admin managers): the same new columns for
leads the manager reaches. The transaction summary is returned only when the
manager reaches the lead through its assigned Telecaller (the
``loan_applications`` manager policy), never through an Employee's task; the
API applies the Telecaller field rules, as for the member's own list.

Both functions keep SECURITY DEFINER with ``search_path = pg_catalog, public,
pg_temp``, EXECUTE revoked from PUBLIC and granted to ``api_user``. The return
types change, so each is dropped and recreated. No table, policy or grant
changes. Downgrade restores the previous column sets (keeping the pg_temp
search-path hardening, which does not change behaviour).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1b3d5a7c9e2"
down_revision: str | Sequence[str] | None = "e8b0d2f4a6c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp"
_MAX_LEADS = 1000
# Per lead; telecallers record a handful of transactions per application.
_MAX_TXN_ITEMS = 50

_LEAD_SIGNALS = "lead_list_signals(uuid[])"
_TEAM_SIGNALS = "team_lead_signals(uuid[])"

# The client referral code that brought a lead in (unchanged from f3a5c7e9b1d2).
_REFERRAL_CODE = """
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
"""

# Product and property facts of a visible lead ``v`` (with ``v.business_line``):
# one entry per loan application and per property deal on the lead's line.
_FACETS = """
    coalesce(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', la.id,
                    'loan_type_id', la.loan_type_id,
                    'loan_type_label', lt.label,
                    'bank_id', la.bank_id,
                    'bank_name', b.name,
                    'status', la.status::text,
                    'amount', la.amount_requested
                )
                ORDER BY la.opened_at, la.id
            )
            FROM public.loan_applications AS la
            LEFT JOIN public.loan_types AS lt ON lt.id = la.loan_type_id
            LEFT JOIN public.banks AS b ON b.id = la.bank_id
            WHERE la.lead_uuid = v.id AND la.business_line = v.business_line
        ),
        '[]'::jsonb
    ),
    coalesce(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'id', pd.id,
                    'status', pd.status::text,
                    'category', p.category::text,
                    'subtype', p.property_subtype::text,
                    'amount', pd.price_quoted
                )
                ORDER BY pd.opened_at, pd.id
            )
            FROM public.property_deals AS pd
            LEFT JOIN public.properties AS p ON p.id = pd.property_id
            WHERE pd.lead_uuid = v.id AND pd.business_line = v.business_line
        ),
        '[]'::jsonb
    ),
    txn.txn_count,
    txn.txn_bank_names,
    txn.txn_amount_min,
    txn.txn_amount_max,
    txn.txn_first_date,
    txn.txn_last_date,
    txn.txn_items
"""

# Transactions recorded on the lead's loan applications, on the lead's line.
# Joined ``ON v.sees_txn``: a caller without that reach gets NULLs.
_TXN_SUMMARY = f"""
    LEFT JOIN LATERAL (
        SELECT
            count(*)::integer AS txn_count,
            coalesce(
                array_agg(DISTINCT btrim(h.bank_name) ORDER BY btrim(h.bank_name))
                    FILTER (WHERE nullif(btrim(h.bank_name), '') IS NOT NULL),
                ARRAY[]::text[]
            ) AS txn_bank_names,
            min(h.amount) AS txn_amount_min,
            max(h.amount) AS txn_amount_max,
            min(h.txn_date) AS txn_first_date,
            max(h.txn_date) AS txn_last_date,
            -- The latest transactions themselves, so a filter can require one
            -- transaction to match bank, date and amount together.
            (
                SELECT coalesce(
                    jsonb_agg(
                        jsonb_build_object(
                            'txn_date', t.txn_date,
                            'bank_name', nullif(btrim(t.bank_name), ''),
                            'amount', t.amount
                        )
                        ORDER BY t.txn_date DESC NULLS LAST, t.created_at DESC
                    ),
                    '[]'::jsonb
                )
                FROM (
                    SELECT h2.txn_date, h2.bank_name, h2.amount, h2.created_at
                    FROM public.loan_txn_history AS h2
                    JOIN public.loan_applications AS la2
                      ON la2.id = h2.loan_application_uuid
                    WHERE la2.lead_uuid = v.id
                      AND la2.business_line = v.business_line
                      AND h2.business_line = v.business_line
                    ORDER BY h2.txn_date DESC NULLS LAST, h2.created_at DESC
                    LIMIT {_MAX_TXN_ITEMS}
                ) AS t
            ) AS txn_items
        FROM public.loan_txn_history AS h
        JOIN public.loan_applications AS la ON la.id = h.loan_application_uuid
        WHERE la.lead_uuid = v.id
          AND la.business_line = v.business_line
          AND h.business_line = v.business_line
    ) AS txn ON v.sees_txn
"""

_FACET_COLUMNS = """
    loan_items jsonb,
    deal_items jsonb,
    txn_count integer,
    txn_bank_names text[],
    txn_amount_min numeric,
    txn_amount_max numeric,
    txn_first_date date,
    txn_last_date date,
    txn_items jsonb
"""

_NEW_LEAD_SIGNALS = f"""
CREATE FUNCTION lead_list_signals(p_lead_uuids uuid[])
RETURNS TABLE (
    lead_uuid uuid,
    client_referral_code text,
    last_disposition text,
    last_interest_level text,
    {_FACET_COLUMNS}
)
LANGUAGE plpgsql
STABLE
{_DEFINER}
AS $$
#variable_conflict use_column
DECLARE
    v_role text := coalesce(current_setting('app.role', true), '');
    v_staff text := coalesce(current_setting('app.staff_profile_uuid', true), '');
    v_agent text := coalesce(current_setting('app.agent_profile_uuid', true), '');
    v_user text := coalesce(current_setting('app.auth_user_uuid', true), '');
    v_line text := coalesce(current_setting('app.business_line', true), '');
BEGIN
    IF v_line = '' THEN
        RETURN;
    END IF;
    IF v_role IN ('telecaller', 'employee') THEN
        IF v_staff = '' THEN
            RETURN;
        END IF;
    ELSIF v_role = 'agent' THEN
        IF v_agent = '' OR v_user = '' THEN
            RETURN;
        END IF;
    ELSE
        RETURN;
    END IF;
    IF coalesce(array_length(p_lead_uuids, 1), 0) > {_MAX_LEADS} THEN
        RAISE EXCEPTION 'too many leads requested' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH visible AS (
        SELECT
            l.id,
            l.mobile,
            l.client_profile_uuid,
            l.business_line,
            -- A visible lead of a Telecaller is assigned to them: the reach of
            -- loan_txn_history RLS.
            (v_role = 'telecaller') AS sees_txn
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
              OR (
                  v_role = 'agent'
                  AND l.origin::text = 'agent'
                  AND l.origin_agent_profile_uuid IS NOT NULL
                  AND l.origin_agent_profile_uuid::text = v_agent
                  AND EXISTS (
                      SELECT 1
                      FROM public.agent_profiles AS ap
                      WHERE ap.id = l.origin_agent_profile_uuid
                        AND ap.auth_user_uuid::text = v_user
                  )
              )
          )
    )
    SELECT
        v.id,
        CASE WHEN v_role = 'agent' THEN NULL ELSE ({_REFERRAL_CODE}) END,
        last_call.disposition::text,
        last_call.interest_level::text,
        {_FACETS}
    FROM visible AS v
    LEFT JOIN LATERAL (
        SELECT a.disposition, a.interest_level
        FROM public.lead_activities AS a
        WHERE v_role <> 'agent'
          AND a.lead_uuid = v.id
          AND (v_role = 'employee' OR a.telecaller_staff_profile_uuid::text = v_staff)
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 1
    ) AS last_call ON true
    {_TXN_SUMMARY};
END;
$$
"""

_NEW_TEAM_SIGNALS = f"""
CREATE FUNCTION team_lead_signals(p_lead_uuids uuid[])
RETURNS TABLE (
    lead_uuid uuid,
    client_referral_code text,
    agent_code text,
    last_disposition text,
    last_interest_level text,
    {_FACET_COLUMNS}
)
LANGUAGE plpgsql
STABLE
{_DEFINER}
AS $$
#variable_conflict use_column
BEGIN
    IF coalesce(current_setting('app.role', true), '') <> 'sub_admin' THEN
        RETURN;
    END IF;
    IF coalesce(array_length(p_lead_uuids, 1), 0) > {_MAX_LEADS} THEN
        RAISE EXCEPTION 'too many leads requested' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH visible AS (
        SELECT
            l.id,
            l.mobile,
            l.client_profile_uuid,
            l.origin,
            l.origin_agent_profile_uuid,
            l.business_line,
            -- Transactions only through the lead's own Telecaller (the
            -- loan_applications manager policy), never through a task.
            team_manager_reaches(l.assigned_telecaller_profile_uuid, l.business_line::text)
                AS sees_txn
        FROM public.leads AS l
        WHERE l.id = ANY (p_lead_uuids)
          AND team_manager_reaches_lead(l.id)
    )
    SELECT
        v.id,
        ({_REFERRAL_CODE}),
        (
            SELECT ap.agent_code::text
            FROM public.agent_profiles AS ap
            WHERE v.origin::text = 'agent' AND ap.id = v.origin_agent_profile_uuid
        ),
        last_call.disposition::text,
        last_call.interest_level::text,
        {_FACETS}
    FROM visible AS v
    LEFT JOIN LATERAL (
        SELECT a.disposition, a.interest_level
        FROM public.lead_activities AS a
        WHERE a.lead_uuid = v.id AND a.business_line = v.business_line
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 1
    ) AS last_call ON true
    {_TXN_SUMMARY};
END;
$$
"""

# --- Previous definitions, restored on downgrade -------------------------------

_OLD_LEAD_SIGNALS = f"""
CREATE FUNCTION lead_list_signals(p_lead_uuids uuid[])
RETURNS TABLE (
    lead_uuid uuid,
    client_referral_code text,
    last_disposition text,
    last_interest_level text
)
LANGUAGE plpgsql
STABLE
{_DEFINER}
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
        ({_REFERRAL_CODE}),
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

_OLD_TEAM_SIGNALS = f"""
CREATE FUNCTION team_lead_signals(p_lead_uuids uuid[])
RETURNS TABLE (
    lead_uuid uuid,
    client_referral_code text,
    agent_code text,
    loan_statuses text[],
    last_disposition text,
    last_interest_level text
)
LANGUAGE plpgsql
STABLE
{_DEFINER}
AS $$
#variable_conflict use_column
BEGIN
    IF coalesce(current_setting('app.role', true), '') <> 'sub_admin' THEN
        RETURN;
    END IF;
    IF coalesce(array_length(p_lead_uuids, 1), 0) > {_MAX_LEADS} THEN
        RAISE EXCEPTION 'too many leads requested' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH visible AS (
        SELECT l.id, l.mobile, l.client_profile_uuid, l.origin,
               l.origin_agent_profile_uuid, l.business_line
        FROM public.leads AS l
        WHERE l.id = ANY (p_lead_uuids)
          AND team_manager_reaches_lead(l.id)
    )
    SELECT
        v.id,
        ({_REFERRAL_CODE}),
        (
            SELECT ap.agent_code::text
            FROM public.agent_profiles AS ap
            WHERE v.origin::text = 'agent' AND ap.id = v.origin_agent_profile_uuid
        ),
        ARRAY(
            SELECT DISTINCT la.status::text
            FROM public.loan_applications AS la
            WHERE la.lead_uuid = v.id
            ORDER BY 1
        ),
        last_call.disposition::text,
        last_call.interest_level::text
    FROM visible AS v
    LEFT JOIN LATERAL (
        SELECT a.disposition, a.interest_level
        FROM public.lead_activities AS a
        WHERE a.lead_uuid = v.id AND a.business_line = v.business_line
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 1
    ) AS last_call ON true;
END;
$$
"""


def _replace(signature: str, definition: str) -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute(definition)
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO api_user")


def upgrade() -> None:
    _replace(_LEAD_SIGNALS, _NEW_LEAD_SIGNALS)
    _replace(_TEAM_SIGNALS, _NEW_TEAM_SIGNALS)


def downgrade() -> None:
    _replace(_TEAM_SIGNALS, _OLD_TEAM_SIGNALS)
    _replace(_LEAD_SIGNALS, _OLD_LEAD_SIGNALS)
