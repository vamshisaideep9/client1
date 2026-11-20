"""Agent bulk lead submit (CS-028).

The browser parses the Agent's spreadsheet and posts at most 200 rows. Every
row is validated here (mobile normalised to E.164, name, optional email,
description as notes, and the requirement text mapped to an active loan
product or a property type on the Agent's own line). Later rows repeating a
mobile are ``duplicate_in_file``.

A dry run stops there: it never reads who else holds a number, creates
nothing and records no attempt, so it cannot be used to probe numbers.

A real submit sends each remaining row through ``introduce_lead_with_outcome``
— the single-submit path — one row at a time. Each capture runs in its own
transaction on its own session (``services/leads.capture_agent_lead``), so
eligibility, duplicate checks, attempt recording, automatic assignment and
notifications are exactly those of a single introduction, and one failing
row never rolls back another.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.masking import mask_mobile
from app.models.loan import LoanType
from app.schemas.agent import (
    LEAD_NOTES_MAX_LENGTH,
    PROPERTY_TYPE_LABELS,
    AgentLeadBulkFieldError,
    AgentLeadBulkFieldLiteral,
    AgentLeadBulkOutcomeLiteral,
    AgentLeadBulkRow,
    AgentLeadBulkRowResult,
    AgentLeadBulkTotals,
    AgentLeadCreate,
    normalise_lead_email,
)
from app.services.agent import (
    InvalidLeadInterest,
    LeadCaptureFailed,
    LeadCaptureUnavailable,
    introduce_lead_with_outcome,
)
from app.services.eligibility import EligibilityReason, reason_label

logger = logging.getLogger(__name__)

_NAME_MAX_LENGTH = 100
_SEPARATORS = re.compile(r"[\s\-().]")
_TEN_DIGITS = re.compile(r"[6-9][0-9]{9}")
_WORDS = re.compile(r"[\s_\-]+")

UNAVAILABLE_LABEL = "Lead capture is temporarily unavailable. Please try again."
DUPLICATE_IN_FILE_LABEL = "This number appears on an earlier row"


def normalise_indian_mobile(raw: str | int | None) -> str | None:
    """+91XXXXXXXXXX / 91XXXXXXXXXX / XXXXXXXXXX (an Indian mobile starting
    6-9; spaces, dashes, dots and brackets ignored) as E.164, else None."""
    if raw is None or isinstance(raw, bool):
        return None
    compact = _SEPARATORS.sub("", str(raw).strip())
    if compact.startswith("+91"):
        digits = compact[3:]
    elif len(compact) == 12 and compact.startswith("91"):
        digits = compact[2:]
    else:
        digits = compact
    if not _TEN_DIGITS.fullmatch(digits):
        return None
    return f"+91{digits}"


def _words(value: str) -> str:
    return _WORDS.sub(" ", value.strip().lower()).strip()


@dataclass(frozen=True)
class _Interest:
    requirement: dict[str, str]
    label: str


class RequirementCatalogue:
    """Maps free requirement text to the Agent's line's choices."""

    def __init__(self, business_line: str, products: list[LoanType]) -> None:
        self.business_line = business_line
        self._by_key: dict[str, list[_Interest]] = {}
        if business_line == "loans":
            for product in products:
                interest = _Interest({"product_slug": product.name}, product.label)
                for key in {product.name.lower(), _words(product.name), _words(product.label)}:
                    self._add(key, interest)
        else:
            for subtype, label in PROPERTY_TYPE_LABELS.items():
                interest = _Interest({"property_type": subtype.value}, label)
                for key in {subtype.value, _words(subtype.value), _words(label)}:
                    self._add(key, interest)

    def _add(self, key: str, interest: _Interest) -> None:
        bucket = self._by_key.setdefault(key, [])
        if interest not in bucket:
            bucket.append(interest)

    def match(self, text: str) -> _Interest:
        """The one choice ``text`` names; ValueError when none or several."""
        candidates = [text.strip().lower(), _words(text)]
        if self.business_line == "real_estate":
            # "Villas", "Plots", "Gated community apartments" name a type too.
            candidates += [key[:-1] for key in candidates if key.endswith("s")]
        for key in candidates:
            found = self._by_key.get(key)
            if found and len(found) == 1:
                return found[0]
            if found:
                raise ValueError("This matches more than one product. Use the product code.")
        if self.business_line == "loans":
            raise ValueError("Use the name of one of your active loan products.")
        raise ValueError("Use a property type, for example Villa or Plot.")


async def load_catalogue(db: AsyncSession, business_line: str) -> RequirementCatalogue:
    """Active products the Agent can see (request session), or the fixed
    property types. Only the Agent's own line is ever offered."""
    products: list[LoanType] = []
    if business_line == "loans":
        products = list(
            (
                await db.scalars(
                    select(LoanType)
                    .where(LoanType.active.is_(True))
                    .order_by(LoanType.display_order, LoanType.label)
                )
            ).all()
        )
    return RequirementCatalogue(business_line, products)


@dataclass
class _Plan:
    index: int
    sno: str | None
    errors: list[AgentLeadBulkFieldError] = field(default_factory=list)
    mobile: str | None = None
    payload: AgentLeadCreate | None = None
    requirement_label: str | None = None
    duplicate_of: int | None = None


def _error(field_name: AgentLeadBulkFieldLiteral, message: str) -> AgentLeadBulkFieldError:
    return AgentLeadBulkFieldError(field=field_name, message=message)


def _plan_row(index: int, row: AgentLeadBulkRow, catalogue: RequirementCatalogue) -> _Plan:
    plan = _Plan(index=index, sno=None if row.sno is None else str(row.sno).strip() or None)
    name = (row.name or "").strip()
    if not name:
        plan.errors.append(_error("name", "Enter the person's name."))
    elif len(name) > _NAME_MAX_LENGTH:
        plan.errors.append(_error("name", "Name must be at most 100 characters."))

    plan.mobile = normalise_indian_mobile(row.mobile)
    if plan.mobile is None:
        plan.errors.append(_error("mobile", "Enter a 10-digit Indian mobile number."))

    requirement: dict[str, Any] = {}
    try:
        email = normalise_lead_email(row.email)
    except ValueError:
        plan.errors.append(_error("email", "Enter a valid email address."))
    else:
        if email is not None:
            requirement["email"] = email

    description = (row.description or "").strip()
    if len(description) > LEAD_NOTES_MAX_LENGTH:
        plan.errors.append(_error("description", "Description must be at most 1000 characters."))
    elif description:
        requirement["notes"] = description

    if row.requirement is not None and row.requirement.strip():
        try:
            interest = catalogue.match(row.requirement)
        except ValueError as exc:
            plan.errors.append(_error("requirement", str(exc)))
        else:
            requirement.update(interest.requirement)
            plan.requirement_label = interest.label

    if not plan.errors and plan.mobile is not None:
        try:
            plan.payload = AgentLeadCreate(
                mobile=plan.mobile, name=name, requirement=requirement or None
            )
        except ValidationError:
            plan.errors.append(_error("requirement", "This row could not be read."))
    return plan


def plan_rows(rows: list[AgentLeadBulkRow], catalogue: RequirementCatalogue) -> list[_Plan]:
    plans = [_plan_row(index, row, catalogue) for index, row in enumerate(rows)]
    first_row_for: dict[str, int] = {}
    for plan in plans:
        if plan.mobile is None:
            continue
        if plan.mobile in first_row_for:
            plan.duplicate_of = first_row_for[plan.mobile]
        else:
            first_row_for[plan.mobile] = plan.index
    return plans


def _result(
    plan: _Plan, outcome: AgentLeadBulkOutcomeLiteral, **extra: Any
) -> AgentLeadBulkRowResult:
    return AgentLeadBulkRowResult(
        row_index=plan.index,
        sno=plan.sno,
        outcome=outcome,
        mobile=plan.mobile,
        requirement_label=plan.requirement_label,
        errors=plan.errors,
        **extra,
    )


def _settled(plan: _Plan) -> AgentLeadBulkRowResult | None:
    """The outcome decided by validation alone, if any."""
    if plan.duplicate_of is not None:
        return _result(
            plan,
            "duplicate_in_file",
            reason_label=DUPLICATE_IN_FILE_LABEL,
            duplicate_of_row_index=plan.duplicate_of,
        )
    if plan.errors or plan.payload is None:
        return _result(plan, "invalid")
    return None


async def _submit(
    db: AsyncSession,
    plan: _Plan,
    *,
    agent_profile_uuid: UUID,
    business_line: str,
) -> AgentLeadBulkRowResult:
    assert plan.payload is not None
    try:
        lead, outcome = await introduce_lead_with_outcome(
            db,
            agent_profile_uuid=agent_profile_uuid,
            business_line=business_line,
            payload=plan.payload,
        )
    except LeadCaptureFailed as exc:
        reason = exc.reason or EligibilityReason.ALREADY_LINKED
        return _result(
            plan,
            "not_eligible" if reason == EligibilityReason.OWN_LEAD_WINDOW_ENDED else "duplicate",
            reason=reason.value,
            reason_label=reason_label(reason),
        )
    except InvalidLeadInterest:
        # The product was withdrawn between validation and submit.
        plan.errors.append(
            _error("requirement", "Use the name of one of your active loan products.")
        )
        return _result(plan, "invalid")
    except LeadCaptureUnavailable:
        return _result(plan, "unavailable", reason_label=UNAVAILABLE_LABEL)
    except Exception:
        # A failure on the request session (the visibility re-read) must not
        # poison the rows after it.
        logger.warning(
            "agent_lead_bulk.row_failed row=%d mobile=%s",
            plan.index,
            mask_mobile(plan.mobile or ""),
            exc_info=True,
        )
        await db.rollback()
        return _result(plan, "unavailable", reason_label=UNAVAILABLE_LABEL)
    return _result(
        plan, "already_introduced" if outcome == "existing" else "created", lead_id=lead.id
    )


async def run_bulk(
    db: AsyncSession,
    rows: list[AgentLeadBulkRow],
    *,
    dry_run: bool,
    agent_profile_uuid: UUID,
    business_line: str,
) -> list[AgentLeadBulkRowResult]:
    catalogue = await load_catalogue(db, business_line)
    results: list[AgentLeadBulkRowResult] = []
    for plan in plan_rows(rows, catalogue):
        settled = _settled(plan)
        if settled is not None:
            results.append(settled)
        elif dry_run:
            results.append(_result(plan, "ready"))
        else:
            results.append(
                await _submit(
                    db,
                    plan,
                    agent_profile_uuid=agent_profile_uuid,
                    business_line=business_line,
                )
            )
    return results


def totals(results: list[AgentLeadBulkRowResult]) -> AgentLeadBulkTotals:
    counts = {
        outcome: 0
        for outcome in (
            "ready",
            "created",
            "already_introduced",
            "duplicate",
            "not_eligible",
            "duplicate_in_file",
            "invalid",
            "unavailable",
        )
    }
    for result in results:
        counts[result.outcome] += 1
    return AgentLeadBulkTotals(rows=len(results), **counts)
