"""Product-first candidate pools shared by lead and field-work routing.

Telecallers (leads) and Officers (tasks) are routed the same way on the loans
line: specialists in the work's product first, then unspecialised staff, then
everyone eligible. Each pool keeps its own durable cursor, named ``all``,
``unspecialised`` or ``product:<id>``; the database checks the names and that a
cursor only ever references a member of its pool. Real Estate work always uses
the line-wide ``all`` pool.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class _Specialised(Protocol):
    loan_specialty_id: UUID | None


ALL_POOL = "all"
UNSPECIALISED_POOL = "unspecialised"


def product_pool(product_id: UUID) -> str:
    return f"product:{product_id}"


def narrow_to_pool[StaffT: _Specialised](
    candidates: Sequence[StaffT], business_line: str, product_id: UUID | None
) -> tuple[list[StaffT], str]:
    """Return the first non-empty pool for this work and its cursor name.

    ``candidates`` are already the eligible, ordered staff for the line. Work
    without a known product, and all Real Estate work, uses every candidate.
    """
    staff = list(candidates)
    if business_line == "loans" and product_id is not None:
        specialists = [person for person in staff if person.loan_specialty_id == product_id]
        if specialists:
            return specialists, product_pool(product_id)
        unspecialised = [person for person in staff if person.loan_specialty_id is None]
        if unspecialised:
            return unspecialised, UNSPECIALISED_POOL
    return staff, ALL_POOL
