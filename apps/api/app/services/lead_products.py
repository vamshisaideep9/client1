"""Read helpers for a lead's stored product (``leads.product_id``).

Labels come from the ``loan_types`` catalogue, which every signed-in role may
read. Lead rows are read through the caller's own ``leads`` RLS, so a lead
outside the caller's reach simply has no entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.loan import LoanType


@dataclass(frozen=True)
class LeadProduct:
    product_id: UUID | None = None
    label: str | None = None


NO_PRODUCT = LeadProduct()


async def product_labels(db: AsyncSession, product_ids: Iterable[UUID | None]) -> dict[UUID, str]:
    ids = {product_id for product_id in product_ids if product_id is not None}
    if not ids:
        return {}
    rows = await db.execute(select(LoanType.id, LoanType.label).where(LoanType.id.in_(ids)))
    return {product_id: label for product_id, label in rows.all()}


async def lead_products(db: AsyncSession, leads: Iterable[Lead]) -> dict[UUID, LeadProduct]:
    """Products of already-loaded leads, keyed by lead id."""
    rows = list(leads)
    labels = await product_labels(db, (lead.product_id for lead in rows))
    return {
        lead.id: LeadProduct(lead.product_id, labels.get(lead.product_id))
        if lead.product_id is not None
        else NO_PRODUCT
        for lead in rows
    }


async def lead_products_for_ids(
    db: AsyncSession, lead_ids: Iterable[UUID]
) -> dict[UUID, LeadProduct]:
    """Products of the leads the caller can read, keyed by lead id."""
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(Lead.id, Lead.product_id, LoanType.label)
        .outerjoin(LoanType, LoanType.id == Lead.product_id)
        .where(Lead.id.in_(ids))
    )
    return {lead_id: LeadProduct(product_id, label) for lead_id, product_id, label in rows.all()}
