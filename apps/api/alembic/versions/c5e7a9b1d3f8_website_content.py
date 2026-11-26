"""Add delegated website drafts and immutable publication revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "c5e7a9b1d3f8"
down_revision = "c5e7a9b1d3f6"
branch_labels = None
depends_on = None

_MAIN = "current_setting('app.website_main_admin', true) = 'true'"
_PROFILE = "NULLIF(current_setting('app.staff_profile_uuid', true), '')::uuid"
_EDITOR = f"""({_MAIN} OR (
    current_setting('app.role', true) IN ('admin', 'sub_admin')
    AND EXISTS (SELECT 1 FROM website_editor_grants WHERE profile_id = {_PROFILE})
))"""


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'website_content_changed'")
    op.create_table(
        "website_editor_grants",
        sa.Column(
            "profile_id",
            UUID(),
            sa.ForeignKey("staff_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "website_documents",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("draft", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer()),
        sa.CheckConstraint("version > 0", name="website_document_version_positive"),
    )
    op.create_table(
        "website_revisions",
        sa.Column("key", sa.String(160), sa.ForeignKey("website_documents.key"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", UUID(), nullable=False),
    )
    op.execute("""INSERT INTO website_documents (key, draft, version, published_revision)
        SELECT 'page/home-closing', jsonb_build_object('title', title, 'body', coalesce(body, '')),
            1, 1 FROM content_blocks WHERE slug = 'homepage-closing' AND status = 'published'""")
    op.execute("""INSERT INTO website_revisions (key, revision, content, published_at, actor_id)
        SELECT 'page/home-closing', 1,
            jsonb_build_object('title', title, 'body', coalesce(body, '')),
            updated_at, created_by_uuid
        FROM content_blocks WHERE slug = 'homepage-closing' AND status = 'published'""")
    op.execute("GRANT SELECT, INSERT, DELETE ON website_editor_grants TO api_user")
    op.execute("GRANT SELECT, INSERT ON website_documents TO api_user")
    op.execute("GRANT UPDATE (draft, version, published_revision) ON website_documents TO api_user")
    op.execute("GRANT SELECT, INSERT ON website_revisions TO api_user")
    for table in ("website_editor_grants", "website_documents", "website_revisions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY website_grants_read ON website_editor_grants
        FOR SELECT TO api_user USING ({_MAIN} OR profile_id = {_PROFILE})""")
    op.execute(f"""CREATE POLICY website_grants_main ON website_editor_grants
        FOR ALL TO api_user USING ({_MAIN}) WITH CHECK ({_MAIN})""")
    op.execute(f"""CREATE POLICY website_documents_read ON website_documents
        FOR SELECT TO api_user USING ({_EDITOR})""")
    op.execute(f"""CREATE POLICY website_documents_create ON website_documents
        FOR INSERT TO api_user WITH CHECK ({_EDITOR} AND published_revision IS NULL)""")
    op.execute(f"""CREATE POLICY website_documents_edit ON website_documents
        FOR UPDATE TO api_user USING ({_EDITOR}) WITH CHECK ({_EDITOR})""")
    # Publication is a separate statement from saving drafts. Guard the pointer
    # as well as revision inserts, including writes outside the service.
    op.execute(f"""CREATE FUNCTION enforce_website_publication() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF NEW.published_revision IS DISTINCT FROM OLD.published_revision
                AND current_user = 'api_user' AND NOT COALESCE(({_MAIN}), false) THEN
                RAISE EXCEPTION 'Only Main Admin can publish website content'
                    USING ERRCODE = '42501';
            END IF;
            RETURN NEW;
        END;
        $$""")
    op.execute("""CREATE TRIGGER website_publication_guard
        BEFORE UPDATE OF published_revision ON website_documents
        FOR EACH ROW EXECUTE FUNCTION enforce_website_publication()""")
    op.execute(f"""CREATE POLICY website_revisions_read ON website_revisions
        FOR SELECT TO api_user USING ({_EDITOR})""")
    op.execute(f"""CREATE POLICY website_revisions_publish ON website_revisions
        FOR INSERT TO api_user WITH CHECK ({_MAIN})""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM website_editor_grants)")):
        raise RuntimeError("Rollback would discard delegated website access.")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM website_documents "
            "WHERE key <> 'page/home-closing' OR version <> 1)"
        )
    ):
        raise RuntimeError("Rollback would discard website drafts and publication history.")
    op.drop_table("website_revisions")
    op.drop_table("website_documents")
    op.execute("DROP FUNCTION enforce_website_publication()")
    op.drop_table("website_editor_grants")
