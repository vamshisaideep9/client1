"""Lead and referral eligibility responses (CS-024).

Reason codes and their labels live in ``app/services/eligibility.py``; the
API sends both so the web app shows the server's wording.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

RowEligibilityLiteral = Literal["eligible", "not_eligible"]
AttemptOutcomeLiteral = Literal["duplicate", "not_eligible"]
EligibilityReasonLiteral = Literal[
    "already_linked",
    "own_lead_window_ended",
    "already_referred",
    "self_referral",
    "attribution_expired",
    "referrer_not_client",
    "below_min_conversion",
    "cap_reached",
    "voided",
]


class EligibilitySummary(BaseModel):
    """Counts for the three eligibility outcomes.

    ``eligible`` counts accepted rows. ``not_eligible`` counts accepted rows a
    rule excludes plus attempts turned away by a rule. ``duplicate`` counts
    attempts turned away as duplicates. ``not_accepted`` is every recorded
    attempt (the "Not accepted" list), recorded from release onward.
    """

    eligible: int
    not_eligible: int
    duplicate: int
    not_accepted: int


class IntakeAttemptRead(BaseModel):
    id: UUID
    outcome: AttemptOutcomeLiteral
    reason: EligibilityReasonLiteral
    reason_label: str
    # Last four digits only, e.g. "***3210" (same shape as
    # ``core/masking.py::mask_mobile``); the raw number is never stored.
    mobile_masked: str
    business_line: Literal["loans", "real_estate"] | None
    created_at: datetime


class IntakeAttemptListResponse(BaseModel):
    attempts: list[IntakeAttemptRead]
    total: int
