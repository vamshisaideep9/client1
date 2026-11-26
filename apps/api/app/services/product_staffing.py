"""Admin product staffing: who covers each catalogue product.

Platform Admin only (the route depends on ``require_platform_admin``); the
queries run on the Admin's own request session under the platform-Admin RLS
branch. Counts are a fixed number of grouped queries, whatever the catalogue
size. Only Telecallers and Officers appear; no contact field leaves here.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.loan import LoanType
from app.models.profile import ProfileStatus, StaffProfile, StaffRole
from app.models.task import Task, TaskStatus
from app.models.user import User, UserStatus
from app.schemas.product_dashboards import (
    ProductStaffingResponse,
    ProductStaffingRow,
    ProductStaffingSummary,
    ProductStaffPerson,
    UnspecialisedCount,
)

OPEN_LEADS = (LeadStatus.NEW, LeadStatus.ASSIGNED, LeadStatus.WORKING, LeadStatus.RELEASED)
UNASSIGNED_LEADS = (LeadStatus.NEW, LeadStatus.RELEASED)
OPEN_TASKS = (
    TaskStatus.UNASSIGNED,
    TaskStatus.ASSIGNED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.BLOCKED,
)
_SPECIALIST_ROLES = (StaffRole.TELECALLER, StaffRole.EMPLOYEE)


def _person(profile: StaffProfile, user: User) -> ProductStaffPerson:
    if user.status == UserStatus.SUSPENDED:
        status = "suspended"
    else:
        status = "active" if profile.status == ProfileStatus.ACTIVE else "inactive"
    return ProductStaffPerson(
        staff_profile_uuid=profile.id,
        auth_user_uuid=profile.auth_user_uuid,
        first_name=user.first_name,
        last_name=user.last_name,
        staff_code=profile.staff_code,
        role=profile.role.value,
        business_line=profile.business_line,
        status=status,
    )


def coverage(telecallers: list[ProductStaffPerson], officers: list[ProductStaffPerson]) -> str:
    """Coverage counts only people who currently receive work."""
    has_telecaller = any(person.status == "active" for person in telecallers)
    has_officer = any(person.status == "active" for person in officers)
    if has_telecaller and has_officer:
        return "full"
    if has_officer:
        return "no_telecaller"
    if has_telecaller:
        return "no_officer"
    return "none"


async def product_staffing(db: AsyncSession) -> ProductStaffingResponse:
    products = list(
        await db.scalars(select(LoanType).order_by(LoanType.display_order, LoanType.label))
    )

    staff_rows = (
        await db.execute(
            select(StaffProfile, User)
            .join(User, User.id == StaffProfile.auth_user_uuid)
            .where(
                StaffProfile.role.in_(_SPECIALIST_ROLES),
                StaffProfile.business_line.is_not(None),
                User.status != UserStatus.SOFT_DELETED,
            )
            .order_by(User.first_name, User.last_name, StaffProfile.staff_code)
        )
    ).all()
    specialists: dict[UUID, dict[str, list[ProductStaffPerson]]] = defaultdict(
        lambda: {"telecaller": [], "employee": []}
    )
    available: list[ProductStaffPerson] = []
    unspecialised: dict[str, UnspecialisedCount] = {}
    for profile, user in staff_rows:
        person = _person(profile, user)
        if profile.loan_specialty_id is not None:
            specialists[profile.loan_specialty_id][profile.role.value].append(person)
            continue
        if person.status != "active":
            continue
        count = unspecialised.setdefault(
            profile.business_line, UnspecialisedCount(business_line=profile.business_line)
        )
        if profile.role == StaffRole.TELECALLER:
            count.telecallers += 1
        else:
            count.officers += 1
        if profile.business_line in ("loans", "both"):
            available.append(person)

    is_open = Lead.status.in_(OPEN_LEADS)
    lead_counts = {
        product_id: (open_count, unassigned)
        for product_id, open_count, unassigned in (
            await db.execute(
                select(
                    Lead.product_id,
                    func.count().filter(is_open),
                    func.count().filter(
                        and_(
                            Lead.status.in_(UNASSIGNED_LEADS),
                            Lead.assigned_telecaller_profile_uuid.is_(None),
                        )
                    ),
                )
                .where(Lead.product_id.is_not(None), Lead.business_line == "loans")
                .group_by(Lead.product_id)
            )
        ).all()
    }
    task_counts = dict(
        (
            await db.execute(
                select(Lead.product_id, func.count())
                .select_from(Task)
                .join(Lead, Lead.id == Task.lead_uuid)
                .where(
                    Lead.product_id.is_not(None),
                    Task.business_line == "loans",
                    Task.status.in_(OPEN_TASKS),
                )
                .group_by(Lead.product_id)
            )
        ).all()
    )

    rows: list[ProductStaffingRow] = []
    for product in products:
        people = specialists.get(product.id, {"telecaller": [], "employee": []})
        open_leads, unassigned = lead_counts.get(product.id, (0, 0))
        rows.append(
            ProductStaffingRow(
                product_id=product.id,
                label=product.label,
                category=product.category,
                active=product.active,
                telecallers=people["telecaller"],
                officers=people["employee"],
                open_leads=open_leads,
                unassigned_leads=unassigned,
                open_tasks=task_counts.get(product.id, 0),
                coverage=coverage(people["telecaller"], people["employee"]),
            )
        )

    line_order = {"loans": 0, "both": 1, "real_estate": 2}
    summary = ProductStaffingSummary(
        products=len(rows),
        active_products=sum(1 for row in rows if row.active),
        fully_covered=sum(1 for row in rows if row.active and row.coverage == "full"),
        open_leads=sum(row.open_leads for row in rows),
        unassigned_leads=sum(row.unassigned_leads for row in rows),
        open_tasks=sum(row.open_tasks for row in rows),
        unspecialised=sorted(
            unspecialised.values(), key=lambda item: line_order.get(item.business_line, 3)
        ),
    )
    return ProductStaffingResponse(products=rows, summary=summary, available=available)
