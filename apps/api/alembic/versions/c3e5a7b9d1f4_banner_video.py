"""Let public banners carry a YouTube video or an uploaded MP4.

Revision ID: c3e5a7b9d1f4
Revises: b7d9f1a3c5e2

banners:
  - youtube_video_id: the 11-character id only (never the pasted URL), checked
    by pattern so no host, path or script can be stored or served.
  - video_media_asset_id: a Media Library asset of usage type `banner_video`,
    RESTRICT on delete like media_asset_id so an in-use video cannot vanish.
  - at most one video source per banner, and none on the authenticated
    dashboard placement (video is a public-campaign feature).

campaign_media_assets:
  - usage type `banner_video` is added to ck_campaign_media_usage_type.
    Uploaded videos are scanned and transcoded by the existing isolated media
    processor before the canonical public MP4 is written.

RLS: not touched. banners and campaign_media_assets policies are row-level
(Sub Admin authoring, draft/rejected-only updates, maker-checker approval), so
the new columns inherit them; a video change therefore goes through the same
review as artwork. GRANT: table-wide grants already cover new columns. No new
table, so no rls-exempt marker is needed.

Rollback: revert the app image first, then `alembic downgrade -1`. Downgrade
drops both columns (unlinking any videos) and narrows the usage-type check; it
fails while a `banner_video` asset row exists, which is intended -- archive or
delete those assets first rather than silently discarding uploaded media.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e5a7b9d1f4"
down_revision: str | None = "b7d9f1a3c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITH_VIDEO = (
    "usage_type IN ('homepage_banner', 'section_banner', 'sponsor', "
    "'dashboard_banner', 'dashboard_offer', 'campaign', 'public_banner', 'banner_video')"
)
_WITHOUT_VIDEO = (
    "usage_type IN ('homepage_banner', 'section_banner', 'sponsor', "
    "'dashboard_banner', 'dashboard_offer', 'campaign', 'public_banner')"
)


def upgrade() -> None:
    op.drop_constraint("ck_campaign_media_usage_type", "campaign_media_assets", type_="check")
    op.create_check_constraint("ck_campaign_media_usage_type", "campaign_media_assets", _WITH_VIDEO)

    op.add_column("banners", sa.Column("youtube_video_id", sa.Text(), nullable=True))
    op.add_column(
        "banners",
        sa.Column(
            "video_media_asset_id",
            sa.UUID(),
            sa.ForeignKey(
                "campaign_media_assets.id",
                name="fk_banners_video_media_asset_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
    )
    # Mirrors image_key: the chosen asset's canonical public object key, copied
    # at write time so serving needs no join. Only processed Media Library
    # output under public/campaign-media/ may be referenced.
    op.add_column("banners", sa.Column("video_key", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_banners_video_key",
        "banners",
        "video_key IS NULL OR video_key ~ '^public/campaign-media/[0-9a-f-]{36}/video\\.mp4$'",
    )
    op.create_check_constraint(
        "ck_banners_youtube_video_id",
        "banners",
        "youtube_video_id IS NULL OR youtube_video_id ~ '^[A-Za-z0-9_-]{11}$'",
    )
    op.create_check_constraint(
        "ck_banners_single_video_source",
        "banners",
        "youtube_video_id IS NULL OR video_media_asset_id IS NULL",
    )
    op.create_check_constraint(
        "ck_banners_video_public_only",
        "banners",
        "placement::text <> 'dashboard' "
        "OR (youtube_video_id IS NULL AND video_media_asset_id IS NULL)",
    )
    op.create_index(
        "ix_banners_video_media_asset_id",
        "banners",
        ["video_media_asset_id"],
        postgresql_where=sa.text("video_media_asset_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_banners_video_media_asset_id", table_name="banners")
    op.drop_constraint("ck_banners_video_public_only", "banners", type_="check")
    op.drop_constraint("ck_banners_single_video_source", "banners", type_="check")
    op.drop_constraint("ck_banners_youtube_video_id", "banners", type_="check")
    op.drop_constraint("ck_banners_video_key", "banners", type_="check")
    op.drop_column("banners", "video_key")
    op.drop_column("banners", "video_media_asset_id")
    op.drop_column("banners", "youtube_video_id")
    op.drop_constraint("ck_campaign_media_usage_type", "campaign_media_assets", type_="check")
    op.create_check_constraint(
        "ck_campaign_media_usage_type", "campaign_media_assets", _WITHOUT_VIDEO
    )
