"""Database-independent checks for the banner YouTube link parser."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.youtube import extract_youtube_id
from app.schemas.banners import BannerCreate, BannerUpdate

_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    [
        _ID,
        f"https://www.youtube.com/watch?v={_ID}",
        f"https://youtube.com/watch?v={_ID}&t=42s&list=PL123",
        f"https://m.youtube.com/watch?v={_ID}",
        f"https://youtu.be/{_ID}?si=abc",
        f"https://www.youtube.com/shorts/{_ID}",
        f"https://www.youtube.com/embed/{_ID}",
        f"https://www.youtube-nocookie.com/embed/{_ID}",
        f"youtube.com/live/{_ID}",
    ],
)
def test_accepts_youtube_video_links(value: str) -> None:
    assert extract_youtube_id(value) == _ID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://www.youtube.com/",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@channel",
        f"https://youtube.com.evil.example/watch?v={_ID}",
        f"https://evil.example/watch?v={_ID}",
        f"javascript:alert(1)//youtube.com/watch?v={_ID}",
        f"https://user:pass@youtube.com/watch?v={_ID}",
        "https://youtu.be/short",
        f"https://www.youtube.com/watch?v={_ID}<script>",
    ],
)
def test_rejects_anything_else(value: str) -> None:
    with pytest.raises(ValueError):
        extract_youtube_id(value)


def _create(**extra: object) -> dict:
    return {
        "business_line": "loans",
        "placement": "homepage",
        "banner_type": "default",
        "title": "Video campaign",
        "media_asset_id": "00000000-0000-4000-8000-000000000001",
        **extra,
    }


def test_banner_create_rejects_two_video_sources() -> None:
    with pytest.raises(ValidationError):
        BannerCreate.model_validate(
            _create(
                youtube_url=f"https://youtu.be/{_ID}",
                video_media_asset_id="00000000-0000-4000-8000-000000000002",
            )
        )


def test_banner_create_rejects_invalid_youtube_link() -> None:
    with pytest.raises(ValidationError):
        BannerCreate.model_validate(_create(youtube_url="https://example.com/video"))


def test_banner_update_blank_youtube_link_clears_video() -> None:
    parsed = BannerUpdate.model_validate({"youtube_url": ""})
    assert "youtube_url" in parsed.model_fields_set
