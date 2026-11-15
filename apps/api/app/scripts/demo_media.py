"""Deterministic synthetic media for the development demo dataset.

Everything here is generated locally (Pillow) except one committed MP4: a muted
8-second gradient loop encoded with the media runtime's own pinned FFmpeg and
the runtime's canonical settings (H.264, yuv420p, faststart, metadata
stripped). Nothing is downloaded, and every image says "SYNTHETIC DEMO" so it
can never be mistaken for a real listing or campaign.

Pure functions only -- no database or storage access -- so the shapes are unit
tested against the same validators real uploads must pass.
"""

from __future__ import annotations

import math
from functools import cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BANNER_VIDEO_FIXTURE = Path(__file__).parent / "data" / "demo-banner-loop.mp4"
BANNER_VIDEO_DURATION_SECONDS = 8

PANORAMA_SIZE = (4096, 2048)
PROPERTY_PHOTO_SIZE = (1600, 1000)

# Brand-adjacent palettes: (background, accent, ink).
PALETTES: dict[str, tuple[str, str, str]] = {
    "loans": ("#16324f", "#b46b3e", "#f6f0e4"),
    "real_estate": ("#2f4a3a", "#c9a24b", "#f6f0e4"),
    "neutral": ("#f6f0e4", "#b46b3e", "#2f2a25"),
}


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _jpeg(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
    return buffer.getvalue()


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    ca = Image.new("RGB", (1, 1), a).getpixel((0, 0))
    cb = Image.new("RGB", (1, 1), b).getpixel((0, 0))
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb, strict=True))  # type: ignore[return-value]


def campaign_artwork(width: int, height: int, *, title: str, line: str) -> bytes:
    """Banner/offer artwork sized for one campaign surface."""
    background, accent, ink = PALETTES[line]
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    # Soft diagonal bands keep the hero legible behind overlaid copy.
    for index in range(6):
        offset = int(width * (0.45 + index * 0.1))
        draw.polygon(
            [
                (offset, 0),
                (offset + width // 8, 0),
                (offset - height // 3, height),
                (offset - height // 3 - width // 8, height),
            ],
            fill=_mix(background, accent, 0.18 + index * 0.06),
        )
    margin = max(24, width // 24)
    draw.rectangle((margin, margin, width - margin, height - margin), outline=accent, width=6)
    draw.text((margin * 2, height // 2 - height // 10), title, fill=ink, font=_font(height // 12))
    draw.text(
        (margin * 2, height // 2 + height // 20),
        "SYNTHETIC DEMO ARTWORK",
        fill=accent,
        font=_font(height // 24),
    )
    return _jpeg(image)


def property_photo(*, label: str, line: str = "real_estate", variant: int = 0) -> bytes:
    """Gallery photo stand-in: simple facade silhouette, clearly labelled."""
    width, height = PROPERTY_PHOTO_SIZE
    background, accent, ink = PALETTES[line]
    sky_top, sky_bottom = ("#9cc3e4", "#e7f0f7") if variant % 2 == 0 else ("#f2c48d", "#f6e7d4")
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=_mix(sky_top, sky_bottom, y / height))
    ground = int(height * 0.78)
    draw.rectangle((0, ground, width, height), fill=background)
    left, right = int(width * (0.18 + variant * 0.05)), int(width * (0.72 + variant * 0.03))
    top = int(height * (0.32 - variant * 0.04))
    draw.rectangle((left, top, right, ground), fill=_mix(ink, accent, 0.25))
    draw.polygon(
        [(left - 30, top), ((left + right) // 2, top - 140), (right + 30, top)], fill=accent
    )
    for column in range(left + 60, right - 60, 140):
        for row in range(top + 60, ground - 80, 120):
            draw.rectangle((column, row, column + 70, row + 70), fill=_mix(sky_bottom, ink, 0.1))
    draw.text((48, 40), label, fill=background, font=_font(54))
    draw.text((48, 110), "SYNTHETIC DEMO PHOTO", fill=background, font=_font(30))
    return _jpeg(image)


def panorama(*, label: str) -> bytes:
    """2:1 equirectangular scene that wraps seamlessly at the left/right seam.

    Every horizontal feature is a function of longitude with period equal to
    the image width, so the 360 viewer shows no seam; compass labels mark
    N/E/S/W so a tester can confirm drag direction and field of view.
    """
    width, height = PANORAMA_SIZE
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    horizon = height // 2
    for y in range(horizon):
        draw.line([(0, y), (width, y)], fill=_mix("#5b8fc7", "#dcebf7", y / horizon))
    for y in range(horizon, height):
        draw.line([(0, y), (width, y)], fill=_mix("#b9a07a", "#6b5a42", (y - horizon) / horizon))
    # Periodic skyline: walls rise and fall with longitude.
    previous = None
    for x in range(0, width + 1, 8):
        longitude = 2 * math.pi * x / width
        wall = horizon - int(260 + 140 * math.sin(3 * longitude) + 60 * math.sin(7 * longitude))
        draw.rectangle((x, wall, x + 8, horizon), fill=_mix("#efe6d6", "#b46b3e", 0.15))
        if previous is not None:
            draw.line([(x - 8, previous), (x, wall)], fill="#2f2a25", width=4)
        previous = wall
    for index, heading in enumerate(("N", "E", "S", "W")):
        x = index * width // 4 + width // 8
        draw.rectangle((x - 3, horizon - 520, x + 3, horizon + 300), fill="#2f2a25")
        draw.text((x - 40, horizon - 640), heading, fill="#16324f", font=_font(110))
    draw.text(
        (width // 2 - 900, height - 260),
        f"{label} - SYNTHETIC 360 DEMO",
        fill="#f6f0e4",
        font=_font(90),
    )
    return _jpeg(image)


DOCUMENT_PAGE_SIZE = (1240, 1754)  # A4 at 150 dpi


def document_pdf(*, title: str, lines: tuple[str, ...] = ()) -> bytes:
    """One-page PDF stand-in for a collected document, clearly watermarked.

    A real single-page PDF (not an empty shell) so document viewers render it.
    """
    width, height = DOCUMENT_PAGE_SIZE
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, width - 60, height - 60), outline="#16324f", width=4)
    draw.text((110, 120), title, fill="#16324f", font=_font(48))
    draw.text(
        (110, 190), "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD", fill="#b46b3e", font=_font(28)
    )
    for row, text in enumerate(lines):
        draw.text((110, 300 + row * 56), text, fill="#2f2a25", font=_font(30))
    for row in range(8):
        top = 760 + row * 90
        draw.rectangle((110, top, width - 110, top + 36), fill=_mix("#ffffff", "#16324f", 0.08))
    draw.text(
        (110, height - 160),
        "Generated by seed_bulk for development only.",
        fill="#6b5a42",
        font=_font(26),
    )
    buffer = BytesIO()
    image.save(buffer, format="PDF", resolution=150.0)
    return buffer.getvalue()


@cache
def banner_video() -> bytes:
    return BANNER_VIDEO_FIXTURE.read_bytes()
