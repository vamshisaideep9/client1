"""Reduce a pasted YouTube link to its 11-character video id.

Banners store and serve only the id, never the pasted URL: the web app builds
the privacy-enhanced embed (youtube-nocookie.com) and thumbnail (i.ytimg.com)
URLs itself from a value that cannot carry a host, path, query or script. Any
input that is not unambiguously a YouTube video is rejected.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_WATCH_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_PATH_PREFIXES = ("/embed/", "/shorts/", "/live/", "/v/")


def extract_youtube_id(value: str) -> str:
    """Return the video id from a YouTube URL (or a bare id).

    Raises ValueError for anything else, including playlists without a video,
    channel pages, and lookalike hosts such as ``youtube.com.evil.example``.
    """
    candidate = value.strip()
    if YOUTUBE_ID_RE.fullmatch(candidate):
        return candidate
    if len(candidate) > 300:
        raise ValueError("Enter a YouTube video link.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parts = urlsplit(candidate)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise ValueError("Enter a YouTube video link.")
    host = (parts.hostname or "").lower()
    video_id: str | None = None
    if host in _SHORT_HOSTS:
        video_id = parts.path.strip("/").split("/", 1)[0]
    elif host in _WATCH_HOSTS:
        if parts.path == "/watch":
            video_id = (parse_qs(parts.query).get("v") or [""])[0]
        else:
            for prefix in _PATH_PREFIXES:
                if parts.path.startswith(prefix):
                    video_id = parts.path[len(prefix) :].split("/", 1)[0]
                    break
    if video_id is None or not YOUTUBE_ID_RE.fullmatch(video_id):
        raise ValueError("Enter a YouTube video link.")
    return video_id
