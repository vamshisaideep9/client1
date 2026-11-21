"""Lead and referral eligibility (CS-024): the one place for codes and labels.

Every panel reads eligibility as one of three outcomes:

* **Eligible** — an accepted Agent lead whose attribution window has not
  expired, or a referral that can still earn (or has earned) its bonus;
* **Not eligible** — an accepted row a rule excludes (the Agent's 30-day
  window ended; a referral voided or refused a bonus), or an attempt turned
  away by a rule;
* **Duplicate** — an attempt turned away because the number is already
  registered, already linked to an enquiry, or already referred.

Accepted rows derive their outcome here from their own columns; rejected
attempts are stored in ``lead_intake_attempts`` with one of the attempt
reasons below. Labels are written for the owner of the row and never say
whose the existing record is: an Agent learns no more than the existing 409
("already linked to an existing enquiry") already tells them.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Literal

from app.models.lead_intake_attempt import IntakeOutcome
from app.models.referral import ReferralStatus

RowEligibility = Literal["eligible", "not_eligible"]


class EligibilityReason(enum.StrEnum):
    # Recorded attempts: Agent introducing a lead.
    ALREADY_LINKED = "already_linked"
    OWN_LEAD_WINDOW_ENDED = "own_lead_window_ended"
    # Recorded attempts: someone signing up with a Client's referral code.
    ALREADY_REFERRED = "already_referred"
    SELF_REFERRAL = "self_referral"
    # Derived on accepted Agent leads.
    ATTRIBUTION_EXPIRED = "attribution_expired"
    # Derived on referrals (``referrals.accrual_reason`` / ``void``).
    REFERRER_NOT_CLIENT = "referrer_not_client"
    BELOW_MIN_CONVERSION = "below_min_conversion"
    CAP_REACHED = "cap_reached"
    VOIDED = "voided"


REASON_LABEL: dict[EligibilityReason, str] = {
    EligibilityReason.ALREADY_LINKED: "Already registered or linked to an existing enquiry",
    EligibilityReason.OWN_LEAD_WINDOW_ENDED: "Your earlier lead for this number expired",
    EligibilityReason.ALREADY_REFERRED: "This person was already referred",
    EligibilityReason.SELF_REFERRAL: "Your own number cannot use your code",
    EligibilityReason.ATTRIBUTION_EXPIRED: "Your 30-day window ended",
    EligibilityReason.REFERRER_NOT_CLIENT: "You were not an active client when they converted",
    EligibilityReason.BELOW_MIN_CONVERSION: "Below the minimum conversions for a bonus",
    EligibilityReason.CAP_REACHED: "Bonus limit reached",
    EligibilityReason.VOIDED: "Not eligible for a bonus",
}

# The outcome each recorded-attempt reason is stored with.
ATTEMPT_OUTCOME: dict[EligibilityReason, IntakeOutcome] = {
    EligibilityReason.ALREADY_LINKED: IntakeOutcome.DUPLICATE,
    EligibilityReason.OWN_LEAD_WINDOW_ENDED: IntakeOutcome.NOT_ELIGIBLE,
    EligibilityReason.ALREADY_REFERRED: IntakeOutcome.DUPLICATE,
    EligibilityReason.SELF_REFERRAL: IntakeOutcome.NOT_ELIGIBLE,
}

# accrual_reason values that keep a referral from earning its bonus. Two of
# them void the referral; below_min_conversion and cap_reached leave it
# "converted" without a bonus. All four read as Not eligible.
_REFERRAL_NOT_ELIGIBLE: dict[str, EligibilityReason] = {
    "self_referral": EligibilityReason.SELF_REFERRAL,
    "referrer_not_client": EligibilityReason.REFERRER_NOT_CLIENT,
    "below_min_conversion": EligibilityReason.BELOW_MIN_CONVERSION,
    "cap_reached": EligibilityReason.CAP_REACHED,
}


def reason_label(reason: EligibilityReason | str | None) -> str | None:
    if reason is None:
        return None
    try:
        return REASON_LABEL[EligibilityReason(reason)]
    except ValueError:
        return None


def agent_lead_eligibility(
    agent_expired_at: datetime | None,
) -> tuple[RowEligibility, EligibilityReason | None]:
    """An accepted Agent lead is eligible until its attribution window expires.

    ``agent_expired_at`` is the permanent expiry marker the scheduler writes
    (``jobs/expire_agent_leads.py``) and the same signal the list shows as
    the "expired" status, so the badge and the status never disagree. A
    resubmission clears it and the lead is eligible again.
    """
    if agent_expired_at is not None:
        return "not_eligible", EligibilityReason.ATTRIBUTION_EXPIRED
    return "eligible", None


def referral_eligibility(
    conversion_status: ReferralStatus | str, accrual_reason: str | None
) -> tuple[RowEligibility, EligibilityReason | None]:
    """A referral is eligible unless a rule refused its bonus or voided it."""
    if accrual_reason in _REFERRAL_NOT_ELIGIBLE:
        return "not_eligible", _REFERRAL_NOT_ELIGIBLE[accrual_reason]
    if ReferralStatus(conversion_status) == ReferralStatus.VOID:
        return "not_eligible", EligibilityReason.VOIDED
    return "eligible", None
