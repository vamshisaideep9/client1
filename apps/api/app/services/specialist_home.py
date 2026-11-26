"""The specialist's own home: their specialty and per-product work counts.

Runs on the caller's request session. Every query also filters to the
caller's own staff profile (assigned leads, assigned tasks) on top of the
``leads`` / ``tasks`` / ``lead_activities`` RLS, so only their own work is
counted. Counts cover the Loans line, the only line with products; a lead or
task without a recorded product is grouped under a null product.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.lead_activity import LeadActivity
from app.models.loan import LoanType
from app.models.profile import StaffProfile
from app.models.task import Task, TaskStatus
from app.schemas.product_dashboards import ProductLeadCount, ProductRef, ProductTaskCount

RECENT_DAYS = 30
_OPEN_LEADS = (LeadStatus.ASSIGNED, LeadStatus.WORKING)
_OPEN_TASKS = (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


async def staff_specialty(db: AsyncSession, staff_profile_uuid: UUID) -> ProductRef | None:
    """The caller's own specialty, read from their own staff profile."""
    row = (
        await db.execute(
            select(LoanType.id, LoanType.label, LoanType.category, LoanType.active)
            .join(StaffProfile, StaffProfile.loan_specialty_id == LoanType.id)
            .where(StaffProfile.id == staff_profile_uuid)
        )
    ).first()
    if row is None:
        return None
    return ProductRef(product_id=row[0], label=row[1], category=row[2], active=row[3])


def _ordered[CountT: (ProductLeadCount, ProductTaskCount)](
    counts: list[CountT], specialty: ProductRef | None
) -> list[CountT]:
    """The specialty first, then busiest products, then products without a label."""
    specialty_id = specialty.product_id if specialty else None
    return sorted(
        counts,
        key=lambda item: (
            item.product_id != specialty_id or specialty_id is None,
            item.product_id is None,
            -item.open,
            (item.label or "").lower(),
        ),
    )


async def _labels(db: AsyncSession, product_ids: set[UUID]) -> dict[UUID, tuple[str, str]]:
    if not product_ids:
        return {}
    rows = await db.execute(
        select(LoanType.id, LoanType.label, LoanType.category).where(LoanType.id.in_(product_ids))
    )
    return {product_id: (label, category) for product_id, label, category in rows.all()}


async def telecaller_product_counts(
    db: AsyncSession,
    staff_profile_uuid: UUID,
    now: datetime,
    specialty: ProductRef | None = None,
) -> list[ProductLeadCount]:
    latest = (
        select(LeadActivity.follow_up_at)
        .where(LeadActivity.lead_uuid == Lead.id)
        .order_by(LeadActivity.created_at.desc())
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )
    is_open = Lead.status.in_(_OPEN_LEADS)
    rows = await db.execute(
        select(
            Lead.product_id,
            func.count().filter(is_open),
            func.count().filter(and_(is_open, latest <= now)),
            func.count().filter(
                and_(
                    Lead.status == LeadStatus.CONVERTED,
                    Lead.updated_at >= now - timedelta(days=RECENT_DAYS),
                )
            ),
        )
        .where(
            Lead.assigned_telecaller_profile_uuid == staff_profile_uuid,
            Lead.business_line == "loans",
        )
        .group_by(Lead.product_id)
    )
    raw = [tuple(row) for row in rows.all()]
    labels = await _labels(db, {row[0] for row in raw if row[0] is not None})
    counts = [
        ProductLeadCount(
            product_id=product_id,
            label=labels.get(product_id, (None, None))[0] if product_id else None,
            category=labels.get(product_id, (None, None))[1] if product_id else None,
            open=open_count,
            overdue=overdue,
            converted_30d=converted,
        )
        for product_id, open_count, overdue, converted in raw
        if open_count or overdue or converted
    ]
    return _ordered(counts, specialty)


async def officer_product_counts(
    db: AsyncSession,
    staff_profile_uuid: UUID,
    now: datetime,
    specialty: ProductRef | None = None,
) -> list[ProductTaskCount]:
    is_open = Task.status.in_(_OPEN_TASKS)
    rows = await db.execute(
        select(
            Lead.product_id,
            func.count().filter(is_open),
            func.count().filter(and_(is_open, Task.due_at.is_not(None), Task.due_at < now)),
            func.count().filter(
                and_(
                    Task.status == TaskStatus.COMPLETED,
                    Task.completed_at >= now - timedelta(days=RECENT_DAYS),
                )
            ),
        )
        .select_from(Task)
        .join(Lead, Lead.id == Task.lead_uuid)
        .where(
            Task.assigned_employee_profile_uuid == staff_profile_uuid,
            Task.business_line == "loans",
        )
        .group_by(Lead.product_id)
    )
    raw = [tuple(row) for row in rows.all()]
    labels = await _labels(db, {row[0] for row in raw if row[0] is not None})
    counts = [
        ProductTaskCount(
            product_id=product_id,
            label=labels.get(product_id, (None, None))[0] if product_id else None,
            category=labels.get(product_id, (None, None))[1] if product_id else None,
            open=open_count,
            overdue=overdue,
            completed_30d=completed,
        )
        for product_id, open_count, overdue, completed in raw
        if open_count or overdue or completed
    ]
    return _ordered(counts, specialty)
