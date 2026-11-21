"""Link property enquiries, site visits and call logs to their lead and request.

Revision ID: e7a9c1b3d5f8
Revises: d4f6a8c0e2b5

Additive only. Telecallers asked to see *what* a client applied for and *when*,
and to keep each application's calls separate when one client re-applies:

1. ``enquiries.lead_uuid`` and ``site_visits.lead_uuid`` (nullable FK to
   ``leads``). Both rows are already created after
   ``ensure_client_line_lead_for_user`` resolves the client's live Real Estate
   lead; the API now stamps that id. Existing rows are backfilled with the same
   client's Real Estate lead that was live when the row was created, falling
   back to the client's most recent Real Estate lead.
2. ``lead_activities`` gains five nullable request links (loan application,
   financial-service enquiry, property enquiry, site visit, property deal) with
   a check that at most one is set. Existing calls stay unlinked ("General").
   ``ON DELETE SET NULL`` keeps a call log row if a linked request is removed.

Access: no grant or policy changes. ``api_user`` already holds table-level
SELECT/INSERT on all three tables (new columns inherit them; ``lead_activities``
still has no UPDATE). ``enquiries_rls`` and ``site_visits_rls`` are unchanged;
the Telecaller API filters these rows by the new ``lead_uuid`` of a lead
assigned to the caller, and inserts validate that a linked request belongs to
the same lead.

Rollback: ``alembic downgrade -1`` drops the new columns, foreign keys, check
constraint and indexes. Request links recorded on calls are lost; no other data changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "e7a9c1b3d5f8"
down_revision = "d4f6a8c0e2b5"
branch_labels = None
depends_on = None

_ACTIVITY_LINKS = (
    ("loan_application_uuid", "loan_applications"),
    ("financial_service_enquiry_uuid", "financial_service_enquiries"),
    ("enquiry_uuid", "enquiries"),
    ("site_visit_uuid", "site_visits"),
    ("property_deal_uuid", "property_deals"),
)

_BACKFILL_SQL = """
UPDATE {table} AS t
SET lead_uuid = (
    SELECT l.id
    FROM leads AS l
    JOIN auth_users AS u ON u.mobile = l.mobile
    WHERE u.id = t.user_uuid
      AND l.business_line = 'real_estate'
    ORDER BY
      (l.created_at <= t.created_at + interval '5 minutes') DESC,
      l.created_at DESC,
      l.id
    LIMIT 1
)
WHERE t.lead_uuid IS NULL
"""


def upgrade() -> None:
    for table in ("enquiries", "site_visits"):
        op.add_column(table, sa.Column("lead_uuid", UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_lead_uuid_leads",
            table,
            "leads",
            ["lead_uuid"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_lead_uuid", table, ["lead_uuid"])
        op.execute(_BACKFILL_SQL.format(table=table))

    for column, target in _ACTIVITY_LINKS:
        op.add_column("lead_activities", sa.Column(column, UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_lead_activities_{column}",
            "lead_activities",
            target,
            [column],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_check_constraint(
        "ck_lead_activities_single_request_link",
        "lead_activities",
        "num_nonnulls({}) <= 1".format(", ".join(column for column, _ in _ACTIVITY_LINKS)),
    )


def downgrade() -> None:
    op.drop_constraint("ck_lead_activities_single_request_link", "lead_activities", type_="check")
    for column, _target in reversed(_ACTIVITY_LINKS):
        op.drop_constraint(f"fk_lead_activities_{column}", "lead_activities", type_="foreignkey")
        op.drop_column("lead_activities", column)

    for table in ("site_visits", "enquiries"):
        op.drop_index(f"ix_{table}_lead_uuid", table_name=table)
        op.drop_constraint(f"fk_{table}_lead_uuid_leads", table, type_="foreignkey")
        op.drop_column(table, "lead_uuid")
