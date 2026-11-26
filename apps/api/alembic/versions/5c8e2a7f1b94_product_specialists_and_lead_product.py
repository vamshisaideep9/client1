"""Product specialists for Telecallers and Officers, and each lead's product.

Revision ID: 5c8e2a7f1b94
Revises: 0d26342db0ba

Product decision (2026-11-26): Admin can give a Loans or dual-line Telecaller
or Officer (``employee``) one active financial product of any category (loan,
credit card or insurance) as a specialty. Leads route to Telecallers, and
field tasks to Officers, specialist first, then unspecialised staff, then
anyone on the line. Real Estate stays line-only.

Changes
-------
* ``staff_profiles``: the specialty check now admits ``employee`` as well as
  ``telecaller``, still only on the loans or both lines.
  ``validate_staff_loan_specialty`` keeps its platform-Admin-only write rule
  and now requires an *active* product of any category.
* ``employee_assignment_cursors``: one cursor per ``(business_line, pool)``,
  mirroring ``lead_assignment_cursors`` (b7d9f1a3c5e7). The existing per-line
  rows become the ``all`` pool, so no assignment or rotation is rewritten.
  The cursor validator also requires the referenced Officer to belong to the
  pool. The table keeps FORCE RLS with no ``api_user`` grant.
* ``leads.product_id``: nullable, ``ON DELETE RESTRICT`` to ``loan_types``,
  indexed with ``(business_line, status)``. The service sets it when a lead is
  captured or routed, and on the first application or enquiry when it is
  still unknown. Existing loans leads are backfilled here: the single distinct
  loan-application product, else the single distinct card/insurance enquiry
  product, else ``requirement->>'product_slug'`` matched to
  ``loan_types.name``. Ambiguous leads stay null. Real Estate leads stay null.

Access
------
``leads`` keeps its table-level ``api_user`` grant and its row policies, which
apply to every column, so no grant or policy changes. No SECURITY DEFINER
function reads the new column. Request sessions never write it: Agent and
Client sessions cannot change workflow columns
(``enforce_lead_detail_ownership``), and capture, routing and application
paths run on the owner session.

The backfill runs in committed batches outside one long transaction, and the
index is built CONCURRENTLY, so writers are not blocked for long. Every step is
idempotent; a run that stops partway can be resumed by upgrading again.

Rollback
--------
The downgrade drops ``leads.product_id`` and its index, removes Officer and
non-loan specialties (they would violate the restored rules), restores the
loan-only Telecaller check and trigger body, and folds the Officer cursors back
to one per line (the ``all`` row is kept). Pool history is discarded. Downgrade
only after quiescing assignment, like b7d9f1a3c5e7.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c8e2a7f1b94"
down_revision: str | Sequence[str] | None = "0d26342db0ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPECIALTY_CHECK = "ck_staff_profiles_loan_specialty_role_line"
# b7d9f1a3c5e7 created the check through the naming convention, which prefixed
# the given name a second time. Its downgrade drops it under that name.
_LEGACY_SPECIALTY_CHECK = "ck_staff_profiles_ck_staff_profiles_loan_specialty_role_line"
_CURSOR_PK = "pk_employee_assignment_cursors"
_CURSOR_POOL_CHECK = "ck_employee_assignment_cursors_pool"
_CURSOR_TRIGGER = "trg_validate_employee_assignment_cursor"
_CURSOR_FN = "validate_employee_assignment_cursor"
_LEAD_PRODUCT_FK = "fk_leads_product_id_loan_types"
_LEAD_PRODUCT_INDEX = "ix_leads_product_line_status"
_BATCH_SIZE = 5_000

_POOL_PREDICATE = (
    "pool = 'all' OR (business_line::text = 'loans' AND "
    "(pool = 'unspecialised' OR pool ~ "
    "'^product:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))"
)


def _specialty_function(product_rule: str, message: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION validate_staff_loan_specialty() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'UPDATE'
            AND NEW.loan_specialty_id IS NOT DISTINCT FROM OLD.loan_specialty_id THEN
            RETURN NEW;
          END IF;
          IF current_user = 'api_user' AND NOT (
            coalesce(current_setting('app.role', true), '') = 'admin' AND
            coalesce(current_setting('app.platform_scope', true), '') = 'true'
          ) THEN
            RAISE EXCEPTION 'only platform Admin may set a specialty' USING ERRCODE = '42501';
          END IF;
          IF NEW.loan_specialty_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.loan_types p WHERE p.id = NEW.loan_specialty_id
              AND {product_rule}
          ) THEN
            RAISE EXCEPTION '{message}' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
    """


def _cursor_function(pool_rule: str, message: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION {_CURSOR_FN}() RETURNS trigger AS $$
        BEGIN
            IF NEW.last_employee_profile_uuid IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM public.staff_profiles staff
                WHERE staff.id = NEW.last_employee_profile_uuid
                  AND staff.role::text = 'employee'
                  AND staff.status::text = 'active'
                  AND staff.business_line::text IN (NEW.business_line::text, 'both')
                  {pool_rule}
            ) THEN
                RAISE EXCEPTION '{message}'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;
    """


_POOL_RULE = (
    "AND (NEW.pool = 'all'\n"
    "                    OR (NEW.pool = 'unspecialised' AND staff.loan_specialty_id IS NULL)\n"
    "                    OR NEW.pool = 'product:' || staff.loan_specialty_id::text)"
)

# One batch of loans leads after ``after`` in id order. A lead with loan
# applications takes their product only when there is exactly one; otherwise a
# lead with card/insurance enquiries takes their product only when there is
# exactly one; otherwise an exact ``product_slug`` match. Returns the batch's
# last id (NULL when the scan is complete).
_BACKFILL_BATCH = sa.text(
    """
    WITH batch AS (
        SELECT id, requirement
        FROM leads
        WHERE business_line = 'loans' AND product_id IS NULL AND id > :after
        ORDER BY id
        LIMIT :batch_size
    ), applications AS (
        SELECT a.lead_uuid, count(DISTINCT a.loan_type_id) AS products,
               min(a.loan_type_id::text)::uuid AS product_id
        FROM loan_applications a JOIN batch ON batch.id = a.lead_uuid
        GROUP BY a.lead_uuid
    ), enquiries AS (
        SELECT e.lead_uuid, count(DISTINCT e.product_id) AS products,
               min(e.product_id::text)::uuid AS product_id
        FROM financial_service_enquiries e JOIN batch ON batch.id = e.lead_uuid
        GROUP BY e.lead_uuid
    ), resolved AS (
        SELECT batch.id,
               CASE
                   WHEN applications.lead_uuid IS NOT NULL THEN
                       CASE WHEN applications.products = 1 THEN applications.product_id END
                   WHEN enquiries.lead_uuid IS NOT NULL THEN
                       CASE WHEN enquiries.products = 1 THEN enquiries.product_id END
                   ELSE slug.id
               END AS product_id
        FROM batch
        LEFT JOIN applications ON applications.lead_uuid = batch.id
        LEFT JOIN enquiries ON enquiries.lead_uuid = batch.id
        LEFT JOIN loan_types slug ON slug.name = batch.requirement ->> 'product_slug'
    ), updated AS (
        UPDATE leads SET product_id = resolved.product_id
        FROM resolved
        WHERE leads.id = resolved.id
          AND resolved.product_id IS NOT NULL
          AND leads.product_id IS NULL
        RETURNING leads.id
    )
    SELECT max(id::text)::uuid FROM batch
    """
)


def _backfill_lead_products(
    connection: sa.engine.Connection, *, batch_size: int = _BATCH_SIZE
) -> int:
    """Classify every unclassified loans lead; return how many batches ran."""
    after: str | None = "00000000-0000-0000-0000-000000000000"
    batches = 0
    while after is not None:
        after = connection.execute(
            _BACKFILL_BATCH, {"after": after, "batch_size": batch_size}
        ).scalar_one()
        if after is not None:
            batches += 1
    return batches


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND conname = :name"
            ),
            {"table": f"public.{table}", "name": name},
        )
        .scalar()
    )


def upgrade() -> None:
    # 1. Specialty rules: Telecallers and Officers, any active product.
    for name in (_LEGACY_SPECIALTY_CHECK, _SPECIALTY_CHECK):
        op.execute(f"ALTER TABLE staff_profiles DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        f"ALTER TABLE staff_profiles ADD CONSTRAINT {_SPECIALTY_CHECK} CHECK ("
        "loan_specialty_id IS NULL OR "
        "(role::text IN ('telecaller', 'employee') AND business_line IS NOT NULL "
        "AND business_line::text IN ('loans', 'both')))"
    )
    op.execute(_specialty_function("p.active", "specialty must be an active product"))

    # 2. Officer cursors: one per (line, pool), like lead_assignment_cursors.
    op.execute(
        "ALTER TABLE employee_assignment_cursors "
        "ADD COLUMN IF NOT EXISTS pool varchar(64) NOT NULL DEFAULT 'all'"
    )
    op.execute(f"ALTER TABLE employee_assignment_cursors DROP CONSTRAINT IF EXISTS {_CURSOR_PK}")
    op.execute(
        f"ALTER TABLE employee_assignment_cursors ADD CONSTRAINT {_CURSOR_PK} "
        "PRIMARY KEY (business_line, pool)"
    )
    op.execute(
        f"ALTER TABLE employee_assignment_cursors DROP CONSTRAINT IF EXISTS {_CURSOR_POOL_CHECK}"
    )
    op.execute(
        f"ALTER TABLE employee_assignment_cursors ADD CONSTRAINT {_CURSOR_POOL_CHECK} "
        f"CHECK ({_POOL_PREDICATE})"
    )
    op.execute(
        _cursor_function(
            _POOL_RULE, "assignment cursor must reference an eligible same-pool Employee"
        )
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_CURSOR_TRIGGER} ON employee_assignment_cursors")
    op.execute(
        f"CREATE TRIGGER {_CURSOR_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF business_line, pool, last_employee_profile_uuid "
        f"ON employee_assignment_cursors FOR EACH ROW EXECUTE FUNCTION {_CURSOR_FN}()"
    )

    # 3. Each lead's product: metadata-only column, then a NOT VALID foreign key
    # so adding it does not scan the table under a strong lock.
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS product_id uuid")
    if not _constraint_exists("leads", _LEAD_PRODUCT_FK):
        op.execute(
            f"ALTER TABLE leads ADD CONSTRAINT {_LEAD_PRODUCT_FK} FOREIGN KEY (product_id) "
            "REFERENCES loan_types (id) ON DELETE RESTRICT NOT VALID"
        )

    # 4. Batched backfill and concurrent index, outside one long transaction.
    with op.get_context().autocommit_block():
        _backfill_lead_products(op.get_bind())
        op.execute(f"ALTER TABLE leads VALIDATE CONSTRAINT {_LEAD_PRODUCT_FK}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_LEAD_PRODUCT_INDEX} "
            "ON leads (product_id, business_line, status)"
        )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_LEAD_PRODUCT_INDEX}")
    op.execute(f"ALTER TABLE leads DROP CONSTRAINT IF EXISTS {_LEAD_PRODUCT_FK}")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS product_id")

    op.execute("DELETE FROM employee_assignment_cursors WHERE pool <> 'all'")
    op.execute(f"DROP TRIGGER IF EXISTS {_CURSOR_TRIGGER} ON employee_assignment_cursors")
    op.execute(_cursor_function("", "assignment cursor must reference an eligible Employee"))
    op.execute(
        f"CREATE TRIGGER {_CURSOR_TRIGGER} "
        "BEFORE INSERT OR UPDATE OF business_line, last_employee_profile_uuid "
        f"ON employee_assignment_cursors FOR EACH ROW EXECUTE FUNCTION {_CURSOR_FN}()"
    )
    op.execute(
        f"ALTER TABLE employee_assignment_cursors DROP CONSTRAINT IF EXISTS {_CURSOR_POOL_CHECK}"
    )
    op.execute(f"ALTER TABLE employee_assignment_cursors DROP CONSTRAINT IF EXISTS {_CURSOR_PK}")
    op.execute("ALTER TABLE employee_assignment_cursors DROP COLUMN IF EXISTS pool")
    op.execute(
        f"ALTER TABLE employee_assignment_cursors ADD CONSTRAINT {_CURSOR_PK} "
        "PRIMARY KEY (business_line)"
    )

    # Officer and non-loan specialties cannot satisfy the restored rules.
    op.execute(
        "UPDATE staff_profiles SET loan_specialty_id = NULL "
        "WHERE loan_specialty_id IS NOT NULL AND (role::text <> 'telecaller' "
        "OR NOT EXISTS (SELECT 1 FROM loan_types p "
        "WHERE p.id = staff_profiles.loan_specialty_id AND p.category = 'loan'))"
    )
    for name in (_LEGACY_SPECIALTY_CHECK, _SPECIALTY_CHECK):
        op.execute(f"ALTER TABLE staff_profiles DROP CONSTRAINT IF EXISTS {name}")
    op.execute(
        f"ALTER TABLE staff_profiles ADD CONSTRAINT {_LEGACY_SPECIALTY_CHECK} CHECK ("
        "loan_specialty_id IS NULL OR "
        "(role::text = 'telecaller' AND business_line IS NOT NULL "
        "AND business_line::text IN ('loans', 'both')))"
    )
    op.execute(
        _specialty_function(
            "p.active AND p.category = 'loan'", "specialty must be an active loan product"
        )
    )
