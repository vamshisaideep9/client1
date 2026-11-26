"""Each lead's stored product: migration backfill and the staff read models."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import text, update

import app.db.session as db_session
from app.models.lead import Lead
from app.models.loan import LoanType
from app.tests.test_employee_api import _employee_token, _seed_employee, _seed_task
from app.tests.test_telecaller_api import (
    _seed_assigned_lead,
    _seed_telecaller,
    _telecaller_token,
)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _product(category: str = "loan") -> LoanType:
    async with db_session.AsyncSessionLocal() as db:
        row = LoanType(
            name=f"lead-product-{uuid.uuid4().hex}",
            label=f"Lead Product {uuid.uuid4().hex[:6]}",
            category=category,
        )
        db.add(row)
        await db.commit()
        return row


async def _set_product(lead_id: str | uuid.UUID, product_id: uuid.UUID | None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(Lead).where(Lead.id == uuid.UUID(str(lead_id))).values(product_id=product_id)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Migration backfill (5c8e2a7f1b94), against temporary shadow tables
# ---------------------------------------------------------------------------


async def test_backfill_classifies_only_unambiguous_loans_leads_across_batches() -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    migration = ScriptDirectory.from_config(config).get_revision("5c8e2a7f1b94").module
    a, b, c, d = (str(uuid.uuid4()) for _ in range(4))

    def lead(n: int) -> str:
        return f"00000000-0000-0000-0000-{n:012d}"

    # (lead, line, stored product, requirement, application products, enquiry products)
    rows = [
        (lead(1), "loans", None, None, [a, a], []),  # one product, twice -> a
        (lead(2), "loans", None, {"product_slug": "slug-a"}, [a, b], []),  # ambiguous -> null
        (lead(3), "loans", None, None, [], [c]),  # enquiry only -> c
        (lead(4), "loans", None, None, [], [c, d]),  # ambiguous enquiries -> null
        (lead(5), "loans", None, {"product_slug": "slug-a"}, [], []),  # slug -> a
        (lead(6), "loans", None, {"product_slug": "missing"}, [], []),  # unknown -> null
        (lead(7), "real_estate", None, {"product_slug": "slug-a"}, [], []),  # never
        (lead(8), "loans", b, None, [a], []),  # already stored -> kept
        (lead(9), "loans", None, None, [a], [c]),  # applications first -> a
    ]

    async with db_session.AsyncSessionLocal() as db:
        connection = await db.connection()

        def run(sync_connection) -> tuple[int, dict[str, str | None]]:
            # Unqualified names in the migration resolve to these temp tables.
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE loan_types (id uuid PRIMARY KEY, name text UNIQUE) "
                    "ON COMMIT DROP"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE leads (id uuid PRIMARY KEY, business_line text, "
                    "product_id uuid, requirement jsonb) ON COMMIT DROP"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE loan_applications (lead_uuid uuid, loan_type_id uuid) "
                    "ON COMMIT DROP"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE financial_service_enquiries (lead_uuid uuid, "
                    "product_id uuid) ON COMMIT DROP"
                )
            )
            for product_id, name in ((a, "slug-a"), (b, "slug-b"), (c, "slug-c"), (d, "slug-d")):
                sync_connection.execute(
                    text("INSERT INTO loan_types VALUES (:id, :name)"),
                    {"id": product_id, "name": name},
                )
            for lead_id, line, stored, requirement, applications, enquiries in rows:
                sync_connection.execute(
                    text("INSERT INTO leads VALUES (:id, :line, :stored, CAST(:req AS jsonb))"),
                    {
                        "id": lead_id,
                        "line": line,
                        "stored": stored,
                        "req": None if requirement is None else json.dumps(requirement),
                    },
                )
                for product_id in applications:
                    sync_connection.execute(
                        text("INSERT INTO loan_applications VALUES (:lead, :product)"),
                        {"lead": lead_id, "product": product_id},
                    )
                for product_id in enquiries:
                    sync_connection.execute(
                        text("INSERT INTO financial_service_enquiries VALUES (:lead, :product)"),
                        {"lead": lead_id, "product": product_id},
                    )
            batches = migration._backfill_lead_products(sync_connection, batch_size=2)
            # A resumed run is a no-op.
            migration._backfill_lead_products(sync_connection, batch_size=2)
            stored = sync_connection.execute(
                text("SELECT id::text, product_id::text FROM leads")
            ).all()
            return batches, {row[0]: row[1] for row in stored}

        batches, stored = await connection.run_sync(run)
        await db.rollback()

    assert batches >= 3  # eight unclassified loans leads in batches of two
    assert stored == {
        lead(1): a,
        lead(2): None,
        lead(3): c,
        lead(4): None,
        lead(5): a,
        lead(6): None,
        lead(7): None,
        lead(8): b,
        lead(9): a,
    }


async def test_lead_product_column_keeps_leads_grants_and_policies() -> None:
    async with db_session.AsyncSessionLocal() as db:
        privileges = set(
            await db.scalars(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = 'leads' "
                    "AND grantee = 'api_user'"
                )
            )
        )
        restricted = await db.scalar(
            text(
                "SELECT confdeltype::text FROM pg_constraint "
                "WHERE conname = 'fk_leads_product_id_loan_types'"
            )
        )
        indexed = await db.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_leads_product_line_status'")
        )
        rls = (
            await db.execute(
                text(
                    "SELECT relrowsecurity FROM pg_class WHERE relname = 'leads' AND relkind = 'r'"
                )
            )
        ).scalar_one()
    assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= privileges
    assert restricted == "r"
    assert "(product_id, business_line, status)" in indexed
    assert rls is True


# ---------------------------------------------------------------------------
# Read models: Telecaller leads and Officer tasks carry the stored product
# ---------------------------------------------------------------------------


async def test_telecaller_lead_reads_carry_the_stored_product(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_telecaller("loans")
    token = _telecaller_token(auth_uuid, staff_uuid)
    card = await _product("credit_card")
    classified = await _seed_assigned_lead("loans", staff_uuid)
    unknown = await _seed_assigned_lead("loans", staff_uuid)
    await _set_product(classified, card.id)

    listed = await client.get("/api/v1/telecaller/leads", headers=_headers(token))
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()}
    assert rows[classified]["product_id"] == str(card.id)
    assert rows[classified]["product_label"] == card.label
    assert rows[unknown]["product_id"] is None and rows[unknown]["product_label"] is None

    detail = await client.get(f"/api/v1/telecaller/leads/{classified}", headers=_headers(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["product_label"] == card.label

    patched = await client.patch(
        f"/api/v1/telecaller/leads/{classified}",
        headers=_headers(token),
        json={"status": "working"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["product_id"] == str(card.id)


async def test_officer_task_reads_carry_the_lead_product(client: AsyncClient) -> None:
    auth_uuid, staff_uuid = await _seed_employee("loans")
    token = _employee_token(auth_uuid, staff_uuid)
    insurance = await _product("insurance")
    due = datetime.now(UTC).replace(hour=23, minute=0, second=0, microsecond=0)
    if due <= datetime.now(UTC):
        due += timedelta(minutes=30)
    task_id = await _seed_task("loans", staff_uuid, due_at=due)
    other_id = await _seed_task("loans", staff_uuid)
    async with db_session.AsyncSessionLocal() as db:
        lead_id = await db.scalar(
            text("SELECT lead_uuid FROM tasks WHERE id = :id"), {"id": task_id}
        )
    await _set_product(lead_id, insurance.id)

    listed = await client.get("/api/v1/employee/tasks", headers=_headers(token))
    assert listed.status_code == 200, listed.text
    rows = {row["id"]: row for row in listed.json()}
    assert rows[task_id]["product_id"] == str(insurance.id)
    assert rows[task_id]["product_label"] == insurance.label
    assert rows[other_id]["product_id"] is None

    detail = await client.get(f"/api/v1/employee/tasks/{task_id}", headers=_headers(token))
    assert detail.status_code == 200 and detail.json()["product_label"] == insurance.label

    home = await client.get("/api/v1/employee/home", headers=_headers(token))
    assert home.status_code == 200, home.text
    today = {row["id"]: row for row in home.json()["tasks_today"]}
    if task_id in today:  # due later today in UTC; skipped only right at midnight
        assert today[task_id]["product_id"] == str(insurance.id)
