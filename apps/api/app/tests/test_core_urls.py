"""Shared link checks for campaign content (app/core/urls.py). Pure functions."""

from __future__ import annotations

import pytest

from app.core.urls import is_safe_https_url, is_safe_link_destination


@pytest.mark.parametrize(
    "value",
    ["https://partner.example/redeem", "https://youtu.be/dQw4w9WgXcQ", "HTTPS://Example.com"],
)
def test_https_url_accepts_plain_https_links(value: str) -> None:
    assert is_safe_https_url(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "http://partner.example",
        "javascript:alert(1)",
        "https://u:p@partner.example",
        "https://user@partner.example",
        "https://@partner.example",
        "https:/partner.example",
        "//partner.example",
    ],
)
def test_https_url_rejects_everything_else(value: str | None) -> None:
    assert not is_safe_https_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "/loans",
        "/real-estate?city=hyderabad#top",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com:8443/path",
    ],
)
def test_link_destination_accepts_site_paths_and_https(value: str) -> None:
    assert is_safe_link_destination(value)


@pytest.mark.parametrize(
    "value",
    [
        "loans",
        "//evil.example",
        "/\\evil.example",
        "/%2F%2Fevil.example",
        "http://example.com",
        "javascript:alert(1)",
        "data:text/html,hi",
        "https://u:p@example.com",
        "https://example.com:99999/",
        "https://example.com:port/",
        "https://exa mple.com",
        " https://example.com",
        "https://example.com/\n",
        "https://example.com/\tpath",
        "https://example.com/\x7f",
    ],
)
def test_link_destination_rejects_unsafe_values(value: str) -> None:
    assert not is_safe_link_destination(value)
