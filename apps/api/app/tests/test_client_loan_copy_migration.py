"""Client-approved loan copy and insurance unpublish (migration d4f6a8c0e2b5)."""

import json
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.schemas.loan_config import LoanTypeUpdate

REVISION = "d4f6a8c0e2b5"


def _migration():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    return ScriptDirectory.from_config(config).get_revision(REVISION).module


@pytest.mark.parametrize("name", ["home-loan", "personal-loan"])
def test_client_copy_passes_the_admin_catalogue_validation(name: str) -> None:
    copy = _migration().COPY[name]
    LoanTypeUpdate.model_validate(
        {
            "public_summary": copy["summary"],
            "public_description": copy["description"],
            "public_highlights": copy["highlights"],
            "public_eligibility": copy["eligibility"],
            "public_documents": copy["documents"],
            "public_faq": copy["faq"],
        }
    )
    published = json.dumps(copy, ensure_ascii=False).lower()
    for banned in ("1,000 crore", "550", "minimum age 20", "insurance"):
        assert banned not in published
    # "Guaranteed" may only appear as the explicit denial in the FAQ.
    assert "guaranteed approval" not in published


def test_single_alembic_head_includes_this_revision() -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [REVISION]


@pytest.mark.asyncio
async def test_copy_updates_only_untouched_seed_rows_and_unpublishes_insurance() -> None:
    import app.db.session as session_module

    migration = _migration()
    seed = migration.SEED
    async with session_module.AsyncSessionLocal() as db:
        connection = await db.connection()

        def verify(sync_connection):
            # Shadow the real catalogue with a transaction-local table so real
            # products, submissions and publication data are never touched.
            sync_connection.execute(
                text(
                    "CREATE TEMP TABLE loan_types (LIKE public.loan_types INCLUDING ALL) "
                    "ON COMMIT DROP"
                )
            )

            def insert(name, label, **overrides):
                values = {
                    "id": uuid.uuid4(),
                    "name": name,
                    "label": label,
                    "summary": f"{label} with guided Dhanadhara support.",
                    "description": seed["description"],
                    "featured": False,
                    **overrides,
                }
                sync_connection.execute(
                    text(
                        "INSERT INTO loan_types (id, name, label, active, category, "
                        "display_order, form_version, public_visible, public_summary, "
                        "public_description, public_highlights, public_eligibility, "
                        "public_documents, public_faq, homepage_featured, "
                        "homepage_feature_order, created_at, updated_at) "
                        "VALUES (:id, :name, :label, true, :category, 1000, 1, true, :summary, "
                        ":description, CAST(:highlights AS jsonb), CAST(:eligibility AS jsonb), "
                        "CAST(:documents AS jsonb), CAST(:faq AS jsonb), :featured, 1000, "
                        "now(), now())"
                    ),
                    {
                        **values,
                        "category": "insurance" if name.endswith("-insurance") else "loan",
                        "highlights": json.dumps(seed["highlights"]),
                        "eligibility": json.dumps(seed["eligibility"]),
                        "documents": json.dumps(seed["documents"]),
                        "faq": json.dumps(seed["faq"]),
                    },
                )

            insert("home-loan", "Home Loan")
            # An Admin already rewrote the personal-loan copy: it must survive.
            insert("personal-loan", "Personal Loan", description="Admin-written copy.")
            insert("health-insurance", "Health Insurance", featured=True)
            for name in ("life-insurance", "property-insurance", "travel-insurance"):
                insert(name, name.replace("-", " ").title())
            insert("business-loan", "Business Loan")

            def rows():
                return {
                    row["name"]: dict(row)
                    for row in sync_connection.execute(text("SELECT * FROM loan_types"))
                    .mappings()
                    .all()
                }

            before = rows()
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.upgrade()
                migration.upgrade()  # idempotent
                after = rows()

                home = after["home-loan"]
                assert home["public_summary"] == migration.COPY["home-loan"]["summary"]
                assert home["public_description"] == migration.COPY["home-loan"]["description"]
                assert home["public_faq"] == migration.COPY["home-loan"]["faq"]
                assert home["public_visible"] is True

                assert after["personal-loan"] == before["personal-loan"]
                assert after["business-loan"] == before["business-loan"]
                for name in migration.INSURANCE:
                    assert after[name]["public_visible"] is False
                    assert after[name]["homepage_featured"] is False

                migration.downgrade()
                restored = rows()
                assert restored["home-loan"] == before["home-loan"]
                assert restored["personal-loan"] == before["personal-loan"]
                for name in migration.INSURANCE:
                    assert restored[name]["public_visible"] is True
                    assert restored[name]["homepage_featured"] is False

        await connection.run_sync(verify)
        await db.rollback()
