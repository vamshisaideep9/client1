"""Synthetic demo media must pass the same validators as real uploads, and the
seeded campaign rows must respect the placement/video rules the API and the
database enforce. Pure checks: no database or storage."""

from __future__ import annotations

import re
from io import BytesIO

import pytest
from PIL import Image

from app import campaign_artwork
from app.core.config import settings
from app.models.banner import BannerPlacement
from app.scripts import demo_media
from app.scripts.seed_demo import _DEMO_ARTWORK, _DEMO_LIVE_BANNERS
from app.services import storage
from app.services.media_processing import validate_panorama_bytes

# Mirrors the ck_banners_video_key check constraint.
_VIDEO_KEY_RE = re.compile(r"^public/campaign-media/[0-9a-f-]{36}/video\.mp4$")


def _open(content: bytes) -> Image.Image:
    image = Image.open(BytesIO(content))
    image.load()
    return image


@pytest.mark.parametrize(("key", "usage_type", "line", "title"), _DEMO_ARTWORK)
def test_campaign_artwork_matches_its_surface_spec(
    key: str, usage_type: str, line: str, title: str
) -> None:
    spec = campaign_artwork.spec_for(usage_type)
    assert spec is not None
    content = demo_media.campaign_artwork(
        spec.target_width, spec.target_height, title=title, line=line
    )
    image = _open(content)
    assert image.format == "JPEG"
    assert spec.accepts(*image.size)
    assert storage.sniff_content_type(content[:32]) == "image/jpeg"


def test_panorama_passes_the_360_validator_and_wraps_seamlessly() -> None:
    content = demo_media.panorama(label="Demo Lakeview Villa")
    validate_panorama_bytes(content, "image/jpeg")
    image = _open(content).convert("RGB")
    width, height = image.size
    assert (width, height) == demo_media.PANORAMA_SIZE
    # Left and right edges meet in the viewer: the skyline row must match.
    row = height // 2 - 200
    left = image.getpixel((0, row))
    right = image.getpixel((width - 1, row))
    assert sum(abs(a - b) for a, b in zip(left, right, strict=True)) < 60


def test_property_photo_is_a_jpeg_gallery_image() -> None:
    content = demo_media.property_photo(label="Demo Metro Apartment", variant=1)
    assert _open(content).size == demo_media.PROPERTY_PHOTO_SIZE
    assert storage.sniff_content_type(content[:32]) == "image/jpeg"


def test_banner_video_fixture_is_a_bounded_mp4() -> None:
    video = demo_media.banner_video()
    assert storage.sniff_content_type(video[:32]) == "video/mp4"
    assert 0 < len(video) <= settings.MEDIA_VIDEO_MAX_UPLOAD_BYTES
    assert demo_media.BANNER_VIDEO_DURATION_SECONDS <= settings.BANNER_VIDEO_MAX_DURATION_SECONDS


def test_live_banners_respect_placement_artwork_and_video_rules() -> None:
    usage_by_key = {key: usage for key, usage, _line, _title in _DEMO_ARTWORK}
    for _key, placement, _line, artwork_key, with_video, *_copy in _DEMO_LIVE_BANNERS:
        allowed = campaign_artwork.BANNER_USAGE_TYPES_BY_PLACEMENT[placement]
        assert usage_by_key[artwork_key] in allowed
        # ck_banners_video_public_only: never a video on the dashboard.
        assert not (with_video and placement == BannerPlacement.DASHBOARD)
    # The one-slot sponsor placement is deliberately left to testers.
    assert all(row[1] != BannerPlacement.HOMEPAGE_AD for row in _DEMO_LIVE_BANNERS)


def test_offer_artwork_is_an_allowed_offer_usage() -> None:
    usage_by_key = {key: usage for key, usage, _line, _title in _DEMO_ARTWORK}
    assert usage_by_key["offer"] in campaign_artwork.OFFER_USAGE_TYPES


def test_demo_video_key_satisfies_the_database_constraint() -> None:
    from app.scripts.demo_catalog import demo_uuid

    key = f"public/campaign-media/{demo_uuid('campaign-media:banner-video')}/video.mp4"
    assert _VIDEO_KEY_RE.fullmatch(key)
