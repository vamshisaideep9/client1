"""Add a sequential, human-readable lead reference number (LD-00000123).

Revision ID: 0d26342db0ba
Revises: a127c49e3db8

Product decision (2026-11-25): every lead gets ``leads.lead_number BIGINT NOT
NULL UNIQUE``. The API formats it as ``LD-`` plus at least eight digits and
shows it only to authenticated staff and Agents for leads they can already
read. The UUID stays the primary key and the target of every foreign key.

Assignment
----------
After this migration, the ``leads_lead_number_seq`` column default numbers
every insert path: public form, chatbot, Agent create and bulk upload, staff
paths and seed scripts. No application code assigns or changes a number. Gaps
from rolled-back inserts or deleted leads are acceptable. ``api_user`` gets
USAGE on the sequence because Agent and staff requests insert under
``SET LOCAL ROLE api_user``. It gets no UPDATE, so it cannot call setval.
``trg_leads_lead_number_immutable`` rejects any later change for every role,
including the owner, like the business_line guard.

Backfill for large tables
-------------------------
Existing leads are numbered from 1 in ``(created_at, id)`` order. The work is
split so that no step holds a long table lock:

1. ``ADD COLUMN`` (nullable, no default) and the sequence: metadata only.
2. Outside a transaction: a temporary partial index on unnumbered rows, built
   CONCURRENTLY, then batches of ``_BATCH_SIZE`` rows. Each batch commits on
   its own, so readers and writers are never blocked for more than one batch's
   row locks.
3. One short transaction under ACCESS EXCLUSIVE numbers the few rows inserted
   since the last batch, positions the sequence after the highest number and
   installs the column default. From then on the database numbers new rows.
4. Outside a transaction: NOT NULL through a NOT VALID check that is validated
   without blocking writes, the unique index built CONCURRENTLY and attached as
   ``uq_leads_lead_number``, and the temporary index dropped.
5. The immutability trigger, and the two confined Agent read functions
   (``agent_commission_ledger`` and ``agent_transaction_detail``) gain the
   lead number of rows they already return.

Every step is idempotent, so a run that stops partway, for example on a lock
timeout or deadlock, can be resumed by running the upgrade again. Numbering
continues after the highest number already assigned.

Rollback
--------
The downgrade restores the two Agent functions and drops the trigger, the
unique constraint and the column with its sequence. These are metadata-only
changes. The numbers are discarded. Upgrading again renumbers every lead from 1
in ``(created_at, id)`` order, so a reference already shared can change if
leads were deleted or sequence values skipped. Avoid downgrading after
references have been used.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0d26342db0ba"
down_revision: str | Sequence[str] | None = "a127c49e3db8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEQUENCE = "leads_lead_number_seq"
_PENDING_INDEX = "ix_leads_lead_number_pending"
_UNIQUE = "uq_leads_lead_number"
_NOT_NULL_CHECK = "ck_leads_lead_number_not_null"
_GUARD_FUNCTION = "enforce_lead_number_immutable"
_GUARD_TRIGGER = "trg_leads_lead_number_immutable"
_BATCH_SIZE = 5_000

# One batch: the next unnumbered rows in creation order receive the numbers
# after ``assigned``. Returns how many rows it selected, so positions of rows
# deleted between the select and the update become gaps instead of repeats.
_NUMBER_BATCH = sa.text(
    """
    WITH next_batch AS (
        SELECT id, row_number() OVER (ORDER BY created_at, id) AS position
        FROM (
            SELECT id, created_at
            FROM leads
            WHERE lead_number IS NULL
            ORDER BY created_at, id
            LIMIT :batch_size
        ) AS pending
    ), numbered AS (
        UPDATE leads
        SET lead_number = :assigned + next_batch.position
        FROM next_batch
        WHERE leads.id = next_batch.id AND leads.lead_number IS NULL
        RETURNING leads.id
    )
    SELECT count(*) FROM next_batch
    """
)

_GUARD_SQL = f"""
CREATE OR REPLACE FUNCTION {_GUARD_FUNCTION}() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.lead_number IS DISTINCT FROM OLD.lead_number THEN
        RAISE EXCEPTION 'lead_number is immutable once assigned'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$
"""

# Confined Agent read functions (e8b0d2f4a6c9, c9e1a3b5d7f2). They already
# return the lead of each row; they only gain its number. Patched in place, as
# c9e1a3b5d7f2 did, so earlier changes to the bodies are preserved.
_LEDGER = "public.agent_commission_ledger()"
_LEDGER_PATCHES = (
    ("deal_amount text)", "deal_amount text, lead_number bigint)"),
    (
        "ELSE pd.price_quoted::text END\n    FROM public.commissions AS c",
        "ELSE pd.price_quoted::text END,\n        l.lead_number\n    FROM public.commissions AS c",
    ),
)
_TRANSACTION = "public.agent_transaction_detail(uuid)"
_TRANSACTION_PATCHES = (
    ("'lead_uuid', l.id,", "'lead_uuid', l.id,\n            'lead_number', l.lead_number,"),
)


def _number_pending_leads(
    connection: sa.engine.Connection, *, assigned: int, batch_size: int = _BATCH_SIZE
) -> int:
    """Number every unnumbered lead after ``assigned``; return the last number used."""
    while True:
        selected = connection.execute(
            _NUMBER_BATCH, {"assigned": assigned, "batch_size": batch_size}
        ).scalar_one()
        if not selected:
            return assigned
        assigned += selected


def _highest_assigned(connection: sa.engine.Connection) -> int:
    return connection.execute(
        sa.text("SELECT coalesce(max(lead_number), 0) FROM leads")
    ).scalar_one()


def _constraint_exists(connection: sa.engine.Connection, name: str) -> bool:
    return bool(
        connection.execute(
            sa.text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conrelid = 'public.leads'::regclass AND conname = :name"
            ),
            {"name": name},
        ).scalar()
    )


def _patch_function(
    signature: str,
    patches: tuple[tuple[str, str], ...],
    *,
    reverse: bool,
    replace_signature: bool,
) -> None:
    connection = op.get_bind()
    definition = connection.execute(
        sa.text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
        {"signature": signature},
    ).scalar_one()
    if ("lead_number" in definition) != reverse:
        return  # Already in the requested shape (a resumed run).
    for old, new in patches:
        if reverse:
            old, new = new, old
        if definition.count(old) != 1:
            raise RuntimeError(f"Unexpected definition of {signature}.")
        definition = definition.replace(old, new, 1)
    if replace_signature:
        # A changed RETURNS TABLE needs a drop; the grant is restored below.
        op.execute(f"DROP FUNCTION {signature}")
    op.execute(definition)
    if replace_signature:
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO api_user")


def upgrade() -> None:
    # 1. Expand: metadata-only changes, committed before the backfill starts.
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_number bigint")
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE} AS bigint OWNED BY leads.lead_number")
    op.execute(f"REVOKE ALL ON SEQUENCE {_SEQUENCE} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SEQUENCE {_SEQUENCE} TO api_user")

    # 2. Batched backfill outside a transaction.
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_PENDING_INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY {_PENDING_INDEX} "
            "ON leads (created_at, id) WHERE lead_number IS NULL"
        )
        assigned = _number_pending_leads(connection, assigned=_highest_assigned(connection))

    # 3. Short exclusive window: number the rows inserted since the last batch
    # (found through the partial index, so no table scan under the lock), then
    # hand numbering to the database.
    connection = op.get_bind()
    op.execute("LOCK TABLE leads IN ACCESS EXCLUSIVE MODE")
    assigned = _number_pending_leads(connection, assigned=assigned)
    # A resumed run may find the default already handing out numbers; never
    # move the sequence backwards.
    handed_out = connection.execute(
        sa.text(f"SELECT CASE WHEN is_called THEN last_value ELSE 0 END FROM {_SEQUENCE}")
    ).scalar_one()
    highest = max(assigned, handed_out)
    connection.execute(
        sa.text(f"SELECT setval('{_SEQUENCE}', :value, :called)"),
        {"value": max(highest, 1), "called": highest > 0},
    )
    op.execute(
        f"ALTER TABLE leads ALTER COLUMN lead_number SET DEFAULT nextval('{_SEQUENCE}'::regclass)"
    )

    # 4. Contract: NOT NULL and UNIQUE without long locks.
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        op.execute(f"ALTER TABLE leads DROP CONSTRAINT IF EXISTS {_NOT_NULL_CHECK}")
        op.execute(
            f"ALTER TABLE leads ADD CONSTRAINT {_NOT_NULL_CHECK} "
            "CHECK (lead_number IS NOT NULL) NOT VALID"
        )
        op.execute(f"ALTER TABLE leads VALIDATE CONSTRAINT {_NOT_NULL_CHECK}")
        # The validated check lets SET NOT NULL skip its full-table scan.
        op.execute("ALTER TABLE leads ALTER COLUMN lead_number SET NOT NULL")
        op.execute(f"ALTER TABLE leads DROP CONSTRAINT {_NOT_NULL_CHECK}")
        if not _constraint_exists(connection, _UNIQUE):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UNIQUE}")
            op.execute(f"CREATE UNIQUE INDEX CONCURRENTLY {_UNIQUE} ON leads (lead_number)")
            op.execute(f"ALTER TABLE leads ADD CONSTRAINT {_UNIQUE} UNIQUE USING INDEX {_UNIQUE}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_PENDING_INDEX}")

    # 5. Immutability guard and the confined Agent reads.
    op.execute(_GUARD_SQL)
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_TRIGGER} ON leads")
    op.execute(
        f"CREATE TRIGGER {_GUARD_TRIGGER} BEFORE UPDATE ON leads "
        f"FOR EACH ROW EXECUTE FUNCTION {_GUARD_FUNCTION}()"
    )
    _patch_function(_LEDGER, _LEDGER_PATCHES, reverse=False, replace_signature=True)
    _patch_function(_TRANSACTION, _TRANSACTION_PATCHES, reverse=False, replace_signature=False)


def downgrade() -> None:
    _patch_function(_TRANSACTION, _TRANSACTION_PATCHES, reverse=True, replace_signature=False)
    _patch_function(_LEDGER, _LEDGER_PATCHES, reverse=True, replace_signature=True)
    op.execute(f"DROP TRIGGER IF EXISTS {_GUARD_TRIGGER} ON leads")
    op.execute(f"DROP FUNCTION IF EXISTS {_GUARD_FUNCTION}()")
    op.execute(f"DROP INDEX IF EXISTS {_PENDING_INDEX}")
    op.execute(f"ALTER TABLE leads DROP CONSTRAINT IF EXISTS {_UNIQUE}")
    op.execute(f"ALTER TABLE leads DROP CONSTRAINT IF EXISTS {_NOT_NULL_CHECK}")
    # Drops the column default and the sequence the column owns.
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lead_number")
    op.execute(f"DROP SEQUENCE IF EXISTS {_SEQUENCE}")
