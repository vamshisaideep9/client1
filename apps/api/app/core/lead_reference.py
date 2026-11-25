"""Human-readable lead reference: ``LD-`` plus the lead number, e.g. ``LD-00000123``.

``leads.lead_number`` is assigned by the ``leads_lead_number_seq`` database
default on every insert path and is immutable afterwards. The UUID stays the
primary key and every foreign-key target; the reference is for display and
search only.

The reference is formatted here and nowhere else. It is shown only on
authenticated staff and Agent surfaces, for leads the caller can already read.
Public and client-facing responses never carry it, because sequential numbers
reveal lead volume.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import HTTPException, Query, status
from pydantic import Field

LEAD_REF_PREFIX = "LD-"
# A minimum width only: LD-123456789 simply grows past eight digits.
LEAD_REF_MIN_DIGITS = 8
# Longest accepted search input; anything longer cannot be a reference.
LEAD_REF_MAX_INPUT = 32
# 18 significant digits always fit a PostgreSQL bigint.
_SEARCH_PATTERN = re.compile(r"(?:LD[\s-]?)?0*(\d{1,18})", re.IGNORECASE)

LeadRef = Annotated[
    str,
    Field(
        pattern=r"^LD-\d{8,}$",
        description="Read-only, human-readable lead reference.",
        examples=["LD-00000123"],
    ),
]


def format_lead_ref(lead_number: int) -> str:
    """``123`` -> ``LD-00000123``; ``123456789`` -> ``LD-123456789``."""
    return f"{LEAD_REF_PREFIX}{lead_number:0{LEAD_REF_MIN_DIGITS}d}"


def format_optional_lead_ref(lead_number: int | None) -> str | None:
    return None if lead_number is None else format_lead_ref(lead_number)


def parse_lead_ref(value: str) -> int | None:
    """The lead number a search term names, or None when it names none.

    Tolerant forms: ``LD-00000123``, ``ld-123``, ``LD 123``, ``LD123`` and a
    bare ``123``. Leading zeros are ignored. Zero, negative numbers, other
    prefixes and anything outside bigint range are not references.
    """
    text = value.strip()
    if not text or len(text) > LEAD_REF_MAX_INPUT:
        return None
    match = _SEARCH_PATTERN.fullmatch(text)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def lead_number_filter(
    lead_ref: str | None = Query(
        default=None,
        max_length=LEAD_REF_MAX_INPUT,
        description=(
            "Exact lead reference, e.g. LD-00000123, ld-123 or 123. "
            "It narrows the caller's existing scope and never widens it."
        ),
    ),
) -> int | None:
    """Query dependency for list endpoints: the lead number to match, if any."""
    if lead_ref is None or not lead_ref.strip():
        return None
    number = parse_lead_ref(lead_ref)
    if number is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Enter a lead reference such as LD-00000123.",
        )
    return number
