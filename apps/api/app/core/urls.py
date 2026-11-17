"""Safe external link checks shared by campaign content.

Offers link to a partner's redemption and terms pages, and banners may point
their call to action at any external page. Both are author-supplied and later
rendered as links for clients or anonymous visitors, so only plain ``https``
URLs with a host and no embedded credentials are accepted. ``http:``,
``javascript:``, ``data:`` and protocol-relative values are rejected.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.navigation import is_safe_internal_path


def is_safe_https_url(value: str | None) -> bool:
    """Return whether *value* is an ``https`` URL with a host and no userinfo."""
    if not value:
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def is_safe_link_destination(value: str) -> bool:
    """Return whether *value* is a same-site path or a strict external https link.

    Same-site paths use the notification rule (no protocol-relative,
    backslash or encoded-authority forms). External links must be ``https``
    with a host, no userinfo, a valid port, and no whitespace or control
    characters, which ``urlsplit`` would otherwise silently strip.
    """
    if is_safe_internal_path(value):
        return True
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return False
    if not is_safe_https_url(value):
        return False
    try:
        urlsplit(value).port  # noqa: B018 -- raises ValueError for a malformed port
    except ValueError:
        return False
    return True
