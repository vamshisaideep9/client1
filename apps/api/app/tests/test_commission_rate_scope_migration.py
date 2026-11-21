"""Rate policy upgrade normalizes fabricated reviews without erasing real ones."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

import app.db.session as session_module


@pytest.mark.asyncio
async def test_upgrade_downgrade_upgrade_preserves_distinct_reviews(monkeypatch) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    migration = ScriptDirectory.from_config(config).get_revision("a6c8e0f2b4d6").module
    created = datetime(2026, 11, 1, tzinfo=UTC)
    reviewed = datetime(2026, 11, 2, tzinfo=UTC)
    maker, reviewer = uuid4(), uuid4()

    async with session_module.AsyncSessionLocal() as db:
        connection = await db.connection()

        def verify(sync_connection):
            # Every unqualified DDL/DML statement in this additive migration
            # resolves to the shadow table, never the real ledger.
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE product_commission_rates "
                    "(LIKE public.product_commission_rates INCLUDING ALL) ON COMMIT DROP"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE POLICY product_commission_rates_select ON product_commission_rates "
                    "FOR SELECT USING (true)"
                )
            )
            monkeypatch.setattr(
                migration, "op", Operations(MigrationContext.configure(sync_connection))
            )
            migration.downgrade()
            ids = {}
            for kind, role, checker, note in (
                ("standalone", "admin", maker, None),
                ("standalone_superseded", "admin", maker, None),
                ("distinct_admin", "admin", reviewer, "Real Admin review"),
                ("distinct_maker", "sub_admin", reviewer, "Real maker review"),
            ):
                ids[kind] = sync_connection.scalar(
                    text(
                        "INSERT INTO product_commission_rates (loan_type_id, kind, percent_bps, "
                        "status, created_by_uuid, created_by_role, checker_uuid, reviewed_at, "
                        "review_note, created_at) VALUES (:product, 'percent', 100, :status, "
                        ":maker, :role, :checker, :reviewed, :note, :created) RETURNING id"
                    ),
                    {
                        "product": uuid4(),
                        "status": (
                            "superseded"
                            if kind == "standalone_superseded"
                            else "approved"
                            if role == "admin"
                            else "rejected"
                        ),
                        "maker": maker,
                        "role": role,
                        "checker": checker,
                        "reviewed": reviewed,
                        "note": note,
                        "created": created,
                    },
                )

            def rows():
                return {
                    row.id: row
                    for row in sync_connection.execute(
                        text("SELECT * FROM product_commission_rates")
                    )
                }

            original = rows()

            def assert_latest():
                current = rows()
                for key in ("standalone", "standalone_superseded"):
                    standalone = current[ids[key]]
                    assert standalone.checker_uuid is None and standalone.reviewed_at is None
                    assert standalone.review_note is None and standalone.created_at == created
                    for column, value in original[ids[key]]._mapping.items():
                        if column not in {"checker_uuid", "reviewed_at", "review_note"}:
                            assert standalone._mapping[column] == value
                for key, note in (
                    ("distinct_admin", "Real Admin review"),
                    ("distinct_maker", "Real maker review"),
                ):
                    assert current[ids[key]].checker_uuid == reviewer
                    assert current[ids[key]].reviewed_at == reviewed
                    assert current[ids[key]].review_note == note
                    assert current[ids[key]].created_at == created
                    assert current[ids[key]] == original[ids[key]]

            migration.upgrade()
            assert_latest()
            assert rows()[ids["standalone"]].version == 1
            migration.downgrade()
            old = rows()[ids["standalone"]]
            assert old.checker_uuid == maker and old.reviewed_at == created
            migration.upgrade()
            assert_latest()
            assert rows()[ids["standalone"]].version == 1

        await connection.run_sync(verify)
        await db.rollback()
