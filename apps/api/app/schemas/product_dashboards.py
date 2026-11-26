"""Product specialist dashboards (2026-11-26).

Shapes for the specialist's own home counts, the Admin product-staffing index,
the Team Manager's product index and the per-product dashboard. Every count is
computed on the server inside the caller's own scope; no shape carries
contact details, amounts or another person's private fields.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProductCategoryLiteral = Literal["loan", "credit_card", "insurance"]
StaffLineLiteral = Literal["loans", "real_estate", "both"]
SpecialistRoleLiteral = Literal["telecaller", "employee"]
CoverageLiteral = Literal["full", "no_telecaller", "no_officer", "none"]


class ProductRef(BaseModel):
    """One catalogue product as staff see it."""

    product_id: UUID
    label: str
    category: ProductCategoryLiteral
    active: bool = True


class ProductLeadCount(BaseModel):
    """The caller's own Loans leads for one product (null: no product recorded).

    ``open``: assigned or working. ``overdue``: open with the latest call's
    follow-up due. ``converted_30d``: converted in the last 30 days.
    """

    product_id: UUID | None = None
    label: str | None = None
    category: ProductCategoryLiteral | None = None
    open: int = 0
    overdue: int = 0
    converted_30d: int = 0


class ProductTaskCount(BaseModel):
    """The caller's own Loans field tasks for one product (null: no product recorded).

    ``open``: assigned, in progress or blocked. ``overdue``: open and past its
    due time. ``completed_30d``: completed in the last 30 days.
    """

    product_id: UUID | None = None
    label: str | None = None
    category: ProductCategoryLiteral | None = None
    open: int = 0
    overdue: int = 0
    completed_30d: int = 0


# ---------------------------------------------------------------------------
# Admin product staffing
# ---------------------------------------------------------------------------


class ProductStaffPerson(BaseModel):
    """A Telecaller or Officer as Admin sees them in the staffing index."""

    staff_profile_uuid: UUID
    auth_user_uuid: UUID
    first_name: str
    last_name: str
    staff_code: str
    role: SpecialistRoleLiteral
    business_line: StaffLineLiteral
    # ``active`` people receive work; ``inactive`` or ``suspended`` do not.
    status: Literal["active", "inactive", "suspended"]


class ProductStaffingRow(ProductRef):
    telecallers: list[ProductStaffPerson] = Field(default_factory=list)
    officers: list[ProductStaffPerson] = Field(default_factory=list)
    # Leads recorded for this product that are not converted or closed.
    open_leads: int = 0
    # Of those, new or released leads that no Telecaller holds yet.
    unassigned_leads: int = 0
    # Open field tasks (unassigned, assigned, in progress or blocked) on its leads.
    open_tasks: int = 0
    # From active specialists only: both roles, one role missing, or neither.
    coverage: CoverageLiteral = "none"


class UnspecialisedCount(BaseModel):
    business_line: StaffLineLiteral
    telecallers: int = 0
    officers: int = 0


class ProductStaffingSummary(BaseModel):
    products: int = 0
    active_products: int = 0
    fully_covered: int = 0
    open_leads: int = 0
    unassigned_leads: int = 0
    open_tasks: int = 0
    # Active staff without a specialty, by their line(s).
    unspecialised: list[UnspecialisedCount] = Field(default_factory=list)


class ProductStaffingResponse(BaseModel):
    products: list[ProductStaffingRow]
    summary: ProductStaffingSummary
    # Active Loans or dual-line Telecallers and Officers without a specialty,
    # the people an Admin can assign to a product.
    available: list[ProductStaffPerson] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Team Manager product index
# ---------------------------------------------------------------------------


class ManagerProductRow(ProductRef):
    # Members of the caller's Loans teams who specialise in this product.
    specialists: int = 0
    # The members' open leads and open tasks recorded for this product.
    open_leads: int = 0
    open_tasks: int = 0


class ManagerProductsResponse(BaseModel):
    products: list[ManagerProductRow]


# ---------------------------------------------------------------------------
# Per-product dashboard
# ---------------------------------------------------------------------------


class ProductLeadKpis(BaseModel):
    # Leads recorded for the product and created in the period.
    captured: int = 0
    # Leads currently open (not converted or closed), whatever their age.
    open: int = 0
    # Leads converted in the period.
    converted: int = 0
    # Share of the period's captured leads that are now converted (percent).
    conversion_rate: float | None = None
    # Period leads held by a Telecaller who does not specialise in the product.
    served_by_fallback: int = 0
    # Open leads no Telecaller holds yet (platform scope only; 0 for a team).
    unassigned: int = 0


class ProductTaskKpis(BaseModel):
    # Field tasks on the product's leads that are open now.
    open: int = 0
    # Tasks completed in the period.
    completed: int = 0
    # Of the period's completed tasks with a due time, the share done on time.
    on_time_rate: float | None = None


class ProductStageCount(BaseModel):
    status: str
    count: int


class ProductTrendPoint(BaseModel):
    # First IST day of the week (Monday, or the period start).
    week_start: date
    captured: int = 0
    converted: int = 0


class ProductStaffRow(BaseModel):
    staff_profile_uuid: UUID
    first_name: str
    last_name: str
    staff_code: str
    role: SpecialistRoleLiteral
    # True when the person specialises in this product; false for a fallback
    # handler who received its work through the unspecialised or line pool.
    specialist: bool
    # Telecallers: the product's leads they hold, those they called in the
    # period, and those converted in the period. Zero for Officers.
    assigned: int = 0
    contacted: int = 0
    converted: int = 0
    # Officers: their open tasks and tasks completed in the period on the
    # product's leads. Zero for Telecallers.
    open_tasks: int = 0
    completed_tasks: int = 0


class ProductDashboardResponse(BaseModel):
    product: ProductRef
    # ``platform``: every lead and person. ``team``: only the caller's own
    # active Loans teams' members and their work.
    scope: Literal["platform", "team"]
    date_from: date
    date_to: date
    range_days: int
    leads: ProductLeadKpis
    tasks: ProductTaskKpis
    # Loan applications (loan products) or enquiries (cards and insurance)
    # opened in the period, by status.
    requests_kind: Literal["applications", "enquiries"]
    requests_by_status: list[ProductStageCount] = Field(default_factory=list)
    trend: list[ProductTrendPoint] = Field(default_factory=list)
    staff: list[ProductStaffRow] = Field(default_factory=list)
