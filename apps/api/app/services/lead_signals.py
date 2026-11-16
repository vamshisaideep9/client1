"""Lead context shown beside Telecaller leads and Employee tasks.

For a page of leads this gathers, in three queries regardless of page size:

* the client referral code and latest call outcome / interest level, through
  the confined ``lead_list_signals`` SECURITY DEFINER function (migration
  ``f3a5c7e9b1d2``). The function re-checks the caller's role, staff profile,
  business line and assignment, so a lead outside the caller's scope simply
  yields no row;
* the introducing Agent's ``agent_code``, through ordinary ``agent_profiles``
  RLS (same-line Telecallers and Employees may read it);
* the lead's loan application statuses, through ordinary
  ``loan_applications`` RLS.

Only identifiers and enum values leave this module: never the referrer's
name, mobile, reward state or call notes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadOrigin
from app.models.loan import LoanApplication
from app.models.profile import AgentProfile
from app.schemas.telecaller import LeadReferrerRead

# Matches the function's own bound; larger pages are split into chunks.
_CHUNK = 1000

_SIGNALS_SQL = text(
    "SELECT lead_uuid, client_referral_code, last_disposition, last_interest_level "
    "FROM lead_list_signals(:lead_uuids)"
).bindparams(bindparam("lead_uuids", type_=ARRAY(PG_UUID(as_uuid=True))))


@dataclass(frozen=True)
class LeadSignals:
    referrer: LeadReferrerRead | None = None
    last_disposition: str | None = None
    last_interest_level: str | None = None
    loan_statuses: list[str] = field(default_factory=list)


EMPTY_SIGNALS = LeadSignals()


async def lead_signals(db: AsyncSession, leads: Iterable[Lead]) -> dict[UUID, LeadSignals]:
    """Return signals keyed by lead id; leads outside the caller's scope get defaults."""
    by_id = {lead.id: lead for lead in leads}
    if not by_id:
        return {}
    lead_ids = list(by_id)

    referral_codes: dict[UUID, str] = {}
    calls: dict[UUID, tuple[str | None, str | None]] = {}
    for start in range(0, len(lead_ids), _CHUNK):
        rows = await db.execute(_SIGNALS_SQL, {"lead_uuids": lead_ids[start : start + _CHUNK]})
        for lead_uuid, code, disposition, interest in rows:
            if code:
                referral_codes[lead_uuid] = code
            calls[lead_uuid] = (disposition, interest)

    agent_ids = {
        lead.origin_agent_profile_uuid
        for lead in by_id.values()
        if lead.origin == LeadOrigin.AGENT and lead.origin_agent_profile_uuid is not None
    }
    agent_codes: dict[UUID, str] = {}
    if agent_ids:
        result = await db.execute(
            select(AgentProfile.id, AgentProfile.agent_code).where(AgentProfile.id.in_(agent_ids))
        )
        agent_codes = {agent_id: code for agent_id, code in result.all()}

    loan_statuses: dict[UUID, list[str]] = {}
    result = await db.execute(
        select(LoanApplication.lead_uuid, LoanApplication.status)
        .where(LoanApplication.lead_uuid.in_(lead_ids))
        .distinct()
    )
    for lead_uuid, loan_status in result.all():
        loan_statuses.setdefault(lead_uuid, []).append(str(loan_status.value))

    out: dict[UUID, LeadSignals] = {}
    for lead_id, lead in by_id.items():
        disposition, interest = calls.get(lead_id, (None, None))
        out[lead_id] = LeadSignals(
            referrer=_referrer(lead, agent_codes, referral_codes),
            last_disposition=disposition,
            last_interest_level=interest,
            loan_statuses=sorted(loan_statuses.get(lead_id, [])),
        )
    return out


async def lead_signals_for_ids(
    db: AsyncSession, lead_ids: Iterable[UUID]
) -> dict[UUID, LeadSignals]:
    """Same as ``lead_signals`` for callers holding only lead ids (Employee tasks).

    Leads the caller cannot read under ``leads`` RLS are skipped, and callers
    fall back to empty signals for them.
    """
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return {}
    leads = (await db.scalars(select(Lead).where(Lead.id.in_(ids)))).all()
    return await lead_signals(db, leads)


def _referrer(
    lead: Lead, agent_codes: dict[UUID, str], referral_codes: dict[UUID, str]
) -> LeadReferrerRead | None:
    # An Agent-introduced lead is attributed to the Agent even if the person
    # also signed up through a client's link: the Agent owns the introduction.
    if lead.origin == LeadOrigin.AGENT and lead.origin_agent_profile_uuid in agent_codes:
        return LeadReferrerRead(
            kind="agent", reference_id=agent_codes[lead.origin_agent_profile_uuid]
        )
    if lead.id in referral_codes:
        return LeadReferrerRead(kind="client", reference_id=referral_codes[lead.id])
    return None
