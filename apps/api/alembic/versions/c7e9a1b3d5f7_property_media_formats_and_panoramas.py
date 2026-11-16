"""Allow AVIF/PNG listing media and up to ten 360 panoramas per listing.

Revision ID: c7e9a1b3d5f7
Revises: b4d6f8a0c2e3

2026-11-14 product decision (CS-018): property listing photos accept JPEG,
PNG, WebP and AVIF; 360 panoramas accept the same formats (previously JPEG or
WebP only) and a listing may carry up to ten of them (previously one).

Changes on ``property_submission_media`` and the public ``property_media``:

- the kind/content-type checks admit ``image/avif`` for images and
  ``image/png``/``image/avif`` for panoramas;
- the one-panorama partial unique indexes are replaced by a trigger that
  allows at most ten panoramas per submission or property, so the database
  still backstops the API limit;
- the position checks widen to the new media totals (submission: 10 images +
  2 PDFs + 10 panoramas = 22, positions 0-21; public: 10 images + 10
  panoramas, positions 0-19).

No table, grant or RLS policy changes. Downgrade refuses to run while any row
uses a format or count the old constraints cannot hold, rather than deleting
listing media.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e9a1b3d5f7"
down_revision: str | Sequence[str] | None = "b4d6f8a0c2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMAGE_TYPES = "'image/jpeg','image/png','image/webp','image/avif'"
_MAX_PANORAMAS = 10

_TRIGGER_FN = "enforce_max_listing_panoramas"


def _set_media_types(image_types: str, panorama_types: str) -> None:
    op.drop_constraint(
        "property_submission_media_kind_content_type",
        "property_submission_media",
        type_="check",
    )
    op.create_check_constraint(
        "property_submission_media_kind_content_type",
        "property_submission_media",
        f"(kind = 'image' AND content_type IN ({image_types})) "
        "OR (kind = 'document' AND content_type = 'application/pdf') "
        f"OR (kind = 'panorama' AND content_type IN ({panorama_types}))",
    )
    op.drop_constraint("property_media_kind_content_type", "property_media", type_="check")
    op.create_check_constraint(
        "property_media_kind_content_type",
        "property_media",
        f"(kind = 'image' AND content_type IN ({image_types})) "
        f"OR (kind = 'panorama' AND content_type IN ({panorama_types}))",
    )


def _set_positions(submission_max: int, public_max: int) -> None:
    op.drop_constraint(
        "property_submission_media_position", "property_submission_media", type_="check"
    )
    op.create_check_constraint(
        "property_submission_media_position",
        "property_submission_media",
        f"position BETWEEN 0 AND {submission_max}",
    )
    op.drop_constraint("property_media_position", "property_media", type_="check")
    op.create_check_constraint(
        "property_media_position", "property_media", f"position BETWEEN 0 AND {public_max}"
    )


def upgrade() -> None:
    _set_media_types(_IMAGE_TYPES, _IMAGE_TYPES)
    _set_positions(21, 19)

    op.drop_index(
        "uq_property_submission_media_one_panorama", table_name="property_submission_media"
    )
    op.drop_index("uq_property_media_one_panorama", table_name="property_media")
    # TG_ARGV[0] names the parent column. A row-level BEFORE INSERT/UPDATE count
    # is enough here: each listing's media is written in one transaction by the
    # owner service, never concurrently for the same parent.
    op.execute(
        f"""
        CREATE FUNCTION {_TRIGGER_FN}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            existing integer;
        BEGIN
            IF NEW.kind <> 'panorama' THEN
                RETURN NEW;
            END IF;
            -- The parent column differs per table, so it is read by name.
            EXECUTE format(
                'SELECT count(*) FROM %I WHERE %I = $1 AND kind = ''panorama'' AND id <> $2',
                TG_TABLE_NAME, TG_ARGV[0]
            ) INTO existing USING (to_jsonb(NEW) ->> TG_ARGV[0])::uuid, NEW.id;
            IF existing >= {_MAX_PANORAMAS} THEN
                RAISE EXCEPTION 'A listing may have at most {_MAX_PANORAMAS} 360 panoramas'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_property_submission_media_max_panoramas
        BEFORE INSERT OR UPDATE OF kind, submission_uuid ON property_submission_media
        FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FN}('submission_uuid')
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_property_media_max_panoramas
        BEFORE INSERT OR UPDATE OF kind, property_uuid ON property_media
        FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FN}('property_uuid')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM property_submission_media
                WHERE content_type = 'image/avif'
                   OR (kind = 'panorama' AND content_type = 'image/png')
                   OR position > 12
            ) OR EXISTS (
                SELECT 1 FROM property_media
                WHERE content_type = 'image/avif'
                   OR (kind = 'panorama' AND content_type = 'image/png')
                   OR position > 10
            ) OR EXISTS (
                SELECT 1 FROM property_submission_media WHERE kind = 'panorama'
                GROUP BY submission_uuid HAVING count(*) > 1
            ) OR EXISTS (
                SELECT 1 FROM property_media WHERE kind = 'panorama'
                GROUP BY property_uuid HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Listing media uses AVIF/PNG panoramas, extra panoramas or positions the '
                    'previous schema cannot hold; archive them before downgrading';
            END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_property_media_max_panoramas ON property_media")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_property_submission_media_max_panoramas "
        "ON property_submission_media"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FN}()")
    op.create_index(
        "uq_property_media_one_panorama",
        "property_media",
        ["property_uuid"],
        unique=True,
        postgresql_where=sa.text("kind = 'panorama'"),
    )
    op.create_index(
        "uq_property_submission_media_one_panorama",
        "property_submission_media",
        ["submission_uuid"],
        unique=True,
        postgresql_where=sa.text("kind = 'panorama'"),
    )
    _set_positions(12, 10)
    _set_media_types("'image/jpeg','image/png','image/webp'", "'image/jpeg','image/webp'")
