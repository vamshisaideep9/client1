"""Effective-dated monthly leave balances, represented in half-day units."""

from collections import Counter
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceEmployment, AttendancePolicy, AttendanceRequest
from app.models.profile import StaffProfile
from app.schemas.attendance import AttendanceBalance, AttendanceMonthlyLeaveRule
from app.services import attendance as clock


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def rule_for(policy: AttendancePolicy, kind: str) -> AttendanceMonthlyLeaveRule | None:
    rule = policy.monthly_leave_rules.get(kind)
    return AttendanceMonthlyLeaveRule.model_validate(rule) if rule else None


async def month_balances(
    db: AsyncSession,
    staff_id: UUID,
    month: date,
    *,
    kind: str | None = None,
    additional: dict[str, int] | None = None,
) -> list[AttendanceBalance]:
    """Walk the effective policy and approved charges from the first accrual month."""
    policies = list(
        await db.scalars(
            select(AttendancePolicy).order_by(
                AttendancePolicy.effective_from, AttendancePolicy.version
            )
        )
    )
    first = next((policy.effective_from for policy in policies if policy.monthly_leave_rules), None)
    if first is None:
        return []
    assignment = await db.get(AttendanceEmployment, staff_id)
    if assignment:
        start, end = assignment.start_day, assignment.end_day
    else:
        created = await db.scalar(
            select(StaffProfile.created_at).where(StaffProfile.id == staff_id)
        )
        if created is None:
            return []
        start, end = clock.work_date(created), None

    charges: dict[str, Counter[date]] = {}
    rows = await db.execute(
        select(AttendanceRequest.leave_type, AttendanceRequest.monthly_charges).where(
            AttendanceRequest.staff_profile_id == staff_id,
            AttendanceRequest.kind == "leave",
            AttendanceRequest.status == "approved",
            AttendanceRequest.end_day >= first,
        )
    )
    for leave_type, days in rows:
        by_month = charges.setdefault(leave_type, Counter())
        for day, units in days.items():
            by_month[date.fromisoformat(day).replace(day=1)] += units
    until = month
    if additional is not None and kind is not None:
        by_month = charges.setdefault(kind, Counter())
        for day, units in additional.items():
            day_month = date.fromisoformat(day).replace(day=1)
            by_month[day_month] += units
        # An earlier approval can reduce what later approved leave carried forward.
        until = max(month, max(by_month, default=month))

    first_month = first.replace(day=1)
    day = min(month, max(first_month, start.replace(day=1)))
    policy_index = 0
    carry: dict[str, int] = {}
    balances: list[AttendanceBalance] = []
    while day <= until:
        while policy_index + 1 < len(policies) and policies[policy_index + 1].effective_from <= day:
            policy_index += 1
        policy = policies[policy_index]
        rules = policy.monthly_leave_rules if policy.effective_from <= day else {}
        remaining: dict[str, int] = {}
        active = start < next_month(day) and (end is None or end >= day)
        for leave_type, rule in sorted(rules.items()):
            if kind is not None and leave_type != kind:
                continue
            allocated = (
                (rule["accrual_units"] + min(carry.get(leave_type, 0), rule["carry_units"]))
                if active
                else 0
            )
            used = charges.get(leave_type, {}).get(day, 0)
            if additional is not None and used > allocated:
                raise clock.AttendanceError(
                    f"This request exceeds the monthly leave balance for {day:%B %Y}."
                )
            remaining[leave_type] = max(0, allocated - used)
            if day == month:
                balances.append(
                    AttendanceBalance(
                        leave_type=leave_type,
                        allocated_units=allocated,
                        used_units=used,
                        month=month,
                    )
                )
        carry = remaining
        day = next_month(day)
    return balances
