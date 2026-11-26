"""Lead references behind payouts, for the payout list and its row actions.

A commission payout covers one or more commissions (``commission_payout_items``
keeps the original membership even after a released claim). A fee-cashback
payout covers one cashback while it stays linked. Referral and contest payouts
have no lead.

Runs on the caller's request session, so RLS decides what is visible: a
commission, cashback, loan application or lead the caller cannot read adds
nothing. The reference never widens the caller's reach.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.lead_reference import format_lead_ref
from app.models.commission import Commission, CommissionPayoutItem
from app.models.fee_cashback import FeeCashback
from app.models.lead import Lead
from app.models.loan import LoanApplication


async def payout_lead_refs(db: AsyncSession, payout_ids: Sequence[UUID]) -> dict[UUID, list[str]]:
    """``{payout_id: ["LD-00000007", ...]}`` in reference order, without repeats."""
    if not payout_ids:
        return {}
    ids = list(payout_ids)
    covered = (
        select(CommissionPayoutItem.payout_uuid.label("payout_uuid"), Lead.lead_number)
        .join(Commission, Commission.id == CommissionPayoutItem.commission_uuid)
        .join(Lead, Lead.id == Commission.lead_uuid)
        .where(CommissionPayoutItem.payout_uuid.in_(ids))
    )
    linked = (
        select(Commission.payout_uuid.label("payout_uuid"), Lead.lead_number)
        .join(Lead, Lead.id == Commission.lead_uuid)
        .where(Commission.payout_uuid.in_(ids))
    )
    cashbacks = (
        select(FeeCashback.payout_uuid.label("payout_uuid"), Lead.lead_number)
        .join(LoanApplication, LoanApplication.id == FeeCashback.loan_application_uuid)
        .join(Lead, Lead.id == LoanApplication.lead_uuid)
        .where(FeeCashback.payout_uuid.in_(ids))
    )
    rows = (await db.execute(union(covered, linked, cashbacks))).all()
    numbers: dict[UUID, set[int]] = {}
    for payout_id, lead_number in rows:
        numbers.setdefault(payout_id, set()).add(lead_number)
    return {
        payout_id: [format_lead_ref(number) for number in sorted(found)]
        for payout_id, found in numbers.items()
    }
