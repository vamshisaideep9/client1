"""Add managed property display types and sale classifications."""

import sqlalchemy as sa

from alembic import op

revision = "c5e7a9b1d3f9"
down_revision = "c5e7a9b1d3f8"
branch_labels = None
depends_on = None

_TABLES = ("properties", "property_submissions")
_BUILT_IN_TYPES = {
    "individual_house": "Individual house",
    "standalone_apartment": "Standalone apartment",
    "gated_community_apartment": "Gated community apartment",
    "villa": "Villa",
    "locked_space": "Locked space",
    "unlocked_space": "Unlocked space",
    "plot": "Plot",
    "farmland": "Farmland",
    "agriland": "Agriland",
}


def upgrade() -> None:
    catalog = op.create_table(
        "property_catalog_types",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("form_subtype", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        catalog,
        [
            {"code": code, "label": label, "form_subtype": code, "active": True}
            for code, label in _BUILT_IN_TYPES.items()
        ],
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON property_catalog_types TO api_user")
    op.execute("ALTER TABLE property_catalog_types ENABLE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY property_catalog_type_read ON property_catalog_types
        FOR SELECT TO api_user USING (true)""")
    op.execute("""CREATE POLICY property_catalog_type_admin ON property_catalog_types
        FOR ALL TO api_user
        USING (current_setting('app.role', true) = 'admin'
            AND current_setting('app.platform_scope', true) = 'true')
        WITH CHECK (current_setting('app.role', true) = 'admin'
            AND current_setting('app.platform_scope', true) = 'true')""")
    for table in _TABLES:
        op.add_column(table, sa.Column("sale_classification", sa.String(12)))
        op.add_column(
            table,
            sa.Column(
                "catalog_type_code", sa.String(40), sa.ForeignKey("property_catalog_types.code")
            ),
        )
        op.create_check_constraint(
            "property_sale_classification",
            table,
            "sale_classification IS NULL OR (listing_intent = 'sale' "
            "AND sale_classification IN ('new_sale', 'resale'))",
        )


def downgrade() -> None:
    catalog = op.get_bind().execute(
        sa.text("SELECT code, label, form_subtype, active FROM property_catalog_types")
    )
    if set(catalog) != {(code, label, code, True) for code, label in _BUILT_IN_TYPES.items()}:
        raise RuntimeError("Rollback would discard property type configuration.")
    for table in _TABLES:
        if op.get_bind().scalar(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM {table} "
                "WHERE catalog_type_code IS NOT NULL OR sale_classification IS NOT NULL)"
            )
        ):
            raise RuntimeError(
                "Rollback would discard configured property types or classifications."
            )
        op.drop_constraint("property_sale_classification", table, type_="check")
        op.drop_column(table, "catalog_type_code")
        op.drop_column(table, "sale_classification")
    op.drop_table("property_catalog_types")
