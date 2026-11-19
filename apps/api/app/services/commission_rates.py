"""Per-loan-product commission rates with maker-checker (CS-028).

Maker commands run on the caller's request session under RLS, like contest
authoring (``services/contests.py``): only a Sub Admin inserts a proposal,
and only that maker withdraws it (the ``product_commission_rates_*`` policies
and the column grant enforce the same). Checker moves (approve, reject), the
supersession of the previous approved rate and a platform Admin's own
immediately-approved entry run on the bypass session with row locks, after
this module's own checks; the maker can never approve their own entry
(checked here and by ``ck_product_commission_rates_checker_not_maker``).

Every command for one product takes the same transaction-scoped advisory
lock first, so concurrent proposals and approvals on a product serialise;
the partial unique indexes (one approved, one pending per product) are the
final guard.

Only loan-category products carry a rate: commissions are paid on disbursed
loan applications, and card / insurance enquiries never become one.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.session as db_session
from app.models.audit_log import AuditAction
from app.models.commission_rate import (
    CommissionRateKind,
    CommissionRateStatus,
    ProductCommissionRate,
)
from app.models.loan import LoanType
from app.models.notification import NotificationType
from app.models.user import User
from app.schemas.commission_rates import (
    MAX_FIXED_COMMISSION_PAISE,
    AgentCommissionRateRead,
    CommissionRateInput,
    CommissionRateRead,
    ProductCommissionRates,
)
from app.services.admin_notify import notify_admins
from app.services.audit_log import record as record_audit
from app.services.notifications import emit_notification

logger = logging.getLogger(__name__)

_LOAN_CATEGORY = "loan"
_HISTORY_LIMIT = 20
_HREF = "/dashboard/commission-rates"

PENDING = CommissionRateStatus.PENDING_APPROVAL.value
APPROVED = CommissionRateStatus.APPROVED.value


class CommissionRateError(Exception):
    """Base for commission-rate service errors; the router maps subclasses."""


class ProductNotFound(CommissionRateError):
    pass


class RateNotFound(CommissionRateError):
    pass


class RateNotOwned(CommissionRateError):
    """Only the Sub Admin who proposed the rate may withdraw it."""


class RateStateError(CommissionRateError):
    """The command does not apply to the rate's current status."""


class RateMakerChecker(CommissionRateError):
    """The reviewer made the entry."""


class RateConflict(CommissionRateError):
    """Another Sub Admin's proposal for this product is awaiting approval."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lock_product(db: AsyncSession, loan_type_id: uuid.UUID) -> None:
    await db.scalar(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"product-commission-rate:{loan_type_id}", 0)
            )
        )
    )


async def _loan_product(db: AsyncSession, loan_type_id: uuid.UUID) -> LoanType:
    product = await db.scalar(
        select(LoanType).where(LoanType.id == loan_type_id, LoanType.category == _LOAN_CATEGORY)
    )
    if product is None:
        raise ProductNotFound("Loan product not found.")
    return product


def _terms(data: CommissionRateInput) -> dict:
    return {
        "kind": data.kind,
        "percent_bps": data.percent_bps if data.kind == CommissionRateKind.PERCENT else None,
        "amount_paise": data.amount_paise if data.kind == CommissionRateKind.FIXED else None,
        "note": data.note,
    }


def _audit_terms(rate: ProductCommissionRate) -> dict:
    return {
        "loan_type_id": str(rate.loan_type_id),
        "kind": rate.kind,
        "percent_bps": rate.percent_bps,
        "amount_paise": rate.amount_paise,
    }


async def _audit(
    db: AsyncSession,
    rate: ProductCommissionRate,
    action: AuditAction,
    *,
    actor_uuid: uuid.UUID,
    actor_role: str,
    detail: dict | None = None,
) -> None:
    await record_audit(
        db,
        action=action,
        entity_type="product_commission_rate",
        entity_uuid=rate.id,
        actor_uuid=actor_uuid,
        actor_role=actor_role,
        business_line="loans",
        detail={**_audit_terms(rate), "status": rate.status, **(detail or {})},
    )


async def _supersede_current(session: AsyncSession, loan_type_id: uuid.UUID) -> uuid.UUID | None:
    current = await session.scalar(
        select(ProductCommissionRate)
        .where(
            ProductCommissionRate.loan_type_id == loan_type_id,
            ProductCommissionRate.status == APPROVED,
        )
        .with_for_update()
    )
    if current is None:
        return None
    current.status = CommissionRateStatus.SUPERSEDED.value
    current.version += 1
    await session.flush()
    return current.id


async def _display_names(user_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """First and last name of the makers and checkers, on the bypass session
    (a Sub Admin cannot read another account under ``auth_users`` RLS)."""
    ids = {value for value in user_ids if value is not None}
    if not ids:
        return {}
    async with db_session.AsyncSessionLocal() as session:
        rows = await session.execute(
            select(User.id, User.first_name, User.last_name).where(User.id.in_(ids))
        )
        return {
            row.id: " ".join(part for part in (row.first_name, row.last_name) if part).strip()
            for row in rows
        }


def _to_read(
    rate: ProductCommissionRate, names: dict[uuid.UUID, str], viewer_uuid: uuid.UUID
) -> CommissionRateRead:
    return CommissionRateRead(
        id=rate.id,
        loan_type_id=rate.loan_type_id,
        kind=rate.kind,  # type: ignore[arg-type]
        percent_bps=rate.percent_bps,
        amount_paise=rate.amount_paise,
        note=rate.note,
        status=rate.status,  # type: ignore[arg-type]
        created_by_uuid=rate.created_by_uuid,
        created_by_name=names.get(rate.created_by_uuid) or None,
        created_by_role=rate.created_by_role,  # type: ignore[arg-type]
        is_mine=rate.created_by_uuid == viewer_uuid,
        checker_name=names.get(rate.checker_uuid) if rate.checker_uuid else None,
        reviewed_at=rate.reviewed_at,
        review_note=rate.review_note,
        version=rate.version,
        created_at=rate.created_at,
        updated_at=rate.updated_at,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def list_for_staff(
    db: AsyncSession, *, viewer_uuid: uuid.UUID, loan_type_id: uuid.UUID | None = None
) -> list[ProductCommissionRates]:
    """Every loan product with its current, pending and earlier rates (platform
    Admin and Sub Admin, request session)."""
    product_stmt = select(LoanType).where(LoanType.category == _LOAN_CATEGORY)
    rate_stmt = select(ProductCommissionRate)
    if loan_type_id is not None:
        product_stmt = product_stmt.where(LoanType.id == loan_type_id)
        rate_stmt = rate_stmt.where(ProductCommissionRate.loan_type_id == loan_type_id)
    products = list(
        (await db.scalars(product_stmt.order_by(LoanType.display_order, LoanType.label))).all()
    )
    rates = list(
        (
            await db.scalars(
                rate_stmt.order_by(
                    ProductCommissionRate.created_at.desc(), ProductCommissionRate.id
                )
            )
        ).all()
    )
    names = await _display_names(
        {rate.created_by_uuid for rate in rates} | {rate.checker_uuid for rate in rates}
    )
    by_product: dict[uuid.UUID, list[ProductCommissionRate]] = {}
    for rate in rates:
        by_product.setdefault(rate.loan_type_id, []).append(rate)

    groups: list[ProductCommissionRates] = []
    for product in products:
        rows = by_product.get(product.id, [])
        current = next((row for row in rows if row.status == APPROVED), None)
        pending = next((row for row in rows if row.status == PENDING), None)
        history = [row for row in rows if row.status not in (APPROVED, PENDING)]
        groups.append(
            ProductCommissionRates(
                loan_type_id=product.id,
                product_slug=product.name,
                product_label=product.label,
                product_active=product.active,
                current=_to_read(current, names, viewer_uuid) if current else None,
                pending=_to_read(pending, names, viewer_uuid) if pending else None,
                history=[_to_read(row, names, viewer_uuid) for row in history[:_HISTORY_LIMIT]],
            )
        )
    return groups


async def product_for_staff(
    db: AsyncSession, loan_type_id: uuid.UUID, *, viewer_uuid: uuid.UUID
) -> ProductCommissionRates:
    groups = await list_for_staff(db, viewer_uuid=viewer_uuid, loan_type_id=loan_type_id)
    if not groups:
        raise ProductNotFound("Loan product not found.")
    return groups[0]


async def approved_rates_for_agent(db: AsyncSession) -> dict[str, AgentCommissionRateRead]:
    """Approved rates of ACTIVE loan products, keyed by product slug, read on
    the Agent's request session (RLS returns approved rows to loans-line
    Agents only, so a real-estate Agent gets nothing)."""
    rows = await db.execute(
        select(ProductCommissionRate, LoanType)
        .join(LoanType, LoanType.id == ProductCommissionRate.loan_type_id)
        .where(
            ProductCommissionRate.status == APPROVED,
            LoanType.active.is_(True),
            LoanType.category == _LOAN_CATEGORY,
        )
        .order_by(LoanType.display_order, LoanType.label)
    )
    return {
        product.name: AgentCommissionRateRead(
            loan_type_id=product.id,
            product_label=product.label,
            kind=rate.kind,  # type: ignore[arg-type]
            percent_bps=rate.percent_bps,
            amount_paise=rate.amount_paise,
            note=rate.note,
            approved_at=rate.reviewed_at,
        )
        for rate, product in rows.all()
    }


# ---------------------------------------------------------------------------
# Maker commands (Sub Admin, request session, RLS)
# ---------------------------------------------------------------------------


async def propose(
    db: AsyncSession,
    loan_type_id: uuid.UUID,
    data: CommissionRateInput,
    *,
    actor_uuid: uuid.UUID,
) -> ProductCommissionRate:
    """A Sub Admin's proposal, awaiting a platform Admin. It replaces (withdraws)
    the same Sub Admin's earlier pending proposal for the product; another
    Sub Admin's pending proposal blocks it (409)."""
    await _lock_product(db, loan_type_id)
    product = await _loan_product(db, loan_type_id)
    pending = await db.scalar(
        select(ProductCommissionRate).where(
            ProductCommissionRate.loan_type_id == loan_type_id,
            ProductCommissionRate.status == PENDING,
        )
    )
    replaced: uuid.UUID | None = None
    if pending is not None:
        if pending.created_by_uuid != actor_uuid or pending.created_by_role != "sub_admin":
            raise RateConflict(
                "Another proposal for this product is awaiting approval. "
                "Wait for the Admin's decision."
            )
        locked = await db.scalar(
            select(ProductCommissionRate)
            .where(ProductCommissionRate.id == pending.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None or locked.status != PENDING:
            raise RateStateError("The earlier proposal changed. Reload and try again.")
        locked.status = CommissionRateStatus.WITHDRAWN.value
        locked.version += 1
        await db.flush()
        await _audit(
            db,
            locked,
            AuditAction.COMMISSION_RATE_WITHDRAWN,
            actor_uuid=actor_uuid,
            actor_role="sub_admin",
            detail={"replaced": True},
        )
        replaced = locked.id

    rate = ProductCommissionRate(
        loan_type_id=loan_type_id,
        **_terms(data),
        status=PENDING,
        created_by_uuid=actor_uuid,
        created_by_role="sub_admin",
    )
    db.add(rate)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise RateConflict("Another proposal for this product is awaiting approval.") from exc
    await _audit(
        db,
        rate,
        AuditAction.COMMISSION_RATE_PROPOSED,
        actor_uuid=actor_uuid,
        actor_role="sub_admin",
        detail={"replaced_rate_id": str(replaced) if replaced else None},
    )
    await db.commit()
    await notify_admins(
        notification_type=NotificationType.COMMISSION_RATE_SUBMITTED,
        title="Commission rate awaiting approval",
        body=f"A commission rate for {product.label} was proposed.",
        href=_HREF,
        exclude_user_uuid=actor_uuid,
    )
    return rate


async def withdraw(
    db: AsyncSession, rate_id: uuid.UUID, *, actor_uuid: uuid.UUID
) -> ProductCommissionRate:
    rate = await db.get(ProductCommissionRate, rate_id)
    if rate is None:
        raise RateNotFound("Commission rate not found.")
    if rate.created_by_uuid != actor_uuid or rate.created_by_role != "sub_admin":
        raise RateNotOwned("Only the Sub Admin who proposed this rate can withdraw it.")
    if rate.status != PENDING:
        raise RateStateError("Only a rate awaiting approval can be withdrawn.")
    await _lock_product(db, rate.loan_type_id)
    locked = await db.scalar(
        select(ProductCommissionRate)
        .where(ProductCommissionRate.id == rate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.status != PENDING:
        raise RateStateError("Only a rate awaiting approval can be withdrawn.")
    locked.status = CommissionRateStatus.WITHDRAWN.value
    locked.version += 1
    await db.flush()
    await _audit(
        db,
        locked,
        AuditAction.COMMISSION_RATE_WITHDRAWN,
        actor_uuid=actor_uuid,
        actor_role="sub_admin",
    )
    await db.commit()
    return locked


# ---------------------------------------------------------------------------
# Platform Admin commands (bypass session, row locks)
# ---------------------------------------------------------------------------


async def set_by_admin(
    loan_type_id: uuid.UUID,
    data: CommissionRateInput,
    *,
    admin_uuid: uuid.UUID,
    admin_role: str,
) -> ProductCommissionRate:
    """A platform Admin's own entry: approved at once (checker = themselves),
    the previous approved rate superseded. A pending Sub Admin proposal is
    left for the Admin to approve or reject."""
    async with db_session.AsyncSessionLocal() as session:
        await _lock_product(session, loan_type_id)
        await _loan_product(session, loan_type_id)
        superseded = await _supersede_current(session, loan_type_id)
        now = datetime.now(UTC)
        rate = ProductCommissionRate(
            loan_type_id=loan_type_id,
            **_terms(data),
            status=APPROVED,
            created_by_uuid=admin_uuid,
            created_by_role="admin",
            checker_uuid=admin_uuid,
            reviewed_at=now,
        )
        session.add(rate)
        await session.flush()
        await _audit(
            session,
            rate,
            AuditAction.COMMISSION_RATE_SET,
            actor_uuid=admin_uuid,
            actor_role=admin_role,
            detail={"superseded_rate_id": str(superseded) if superseded else None},
        )
        await session.commit()
        return rate


async def _locked_pending(
    session: AsyncSession, rate_id: uuid.UUID, reviewer_uuid: uuid.UUID
) -> ProductCommissionRate:
    loan_type_id = await session.scalar(
        select(ProductCommissionRate.loan_type_id).where(ProductCommissionRate.id == rate_id)
    )
    if loan_type_id is None:
        raise RateNotFound("Commission rate not found.")
    await _lock_product(session, loan_type_id)
    rate = await session.scalar(
        select(ProductCommissionRate).where(ProductCommissionRate.id == rate_id).with_for_update()
    )
    if rate is None:
        raise RateNotFound("Commission rate not found.")
    if rate.status != PENDING:
        raise RateStateError("This rate is not awaiting approval.")
    if rate.created_by_uuid == reviewer_uuid:
        raise RateMakerChecker("You cannot review a rate you proposed.")
    return rate


@dataclass(frozen=True)
class _Decision:
    rate: ProductCommissionRate
    product_label: str


async def _notify_maker(decision: _Decision, *, approved: bool) -> None:
    label = decision.product_label
    await emit_notification(
        user_uuid=decision.rate.created_by_uuid,
        notification_type=NotificationType.COMMISSION_RATE_REVIEWED,
        title="Commission rate approved" if approved else "Commission rate not approved",
        body=(
            f"Your commission rate for {label} was approved."
            if approved
            else f"Admin left feedback on your commission rate for {label}."
        ),
        href=_HREF,
    )


async def approve(
    rate_id: uuid.UUID,
    *,
    reviewer_uuid: uuid.UUID,
    reviewer_role: str,
    note: str | None,
) -> ProductCommissionRate:
    async with db_session.AsyncSessionLocal() as session:
        rate = await _locked_pending(session, rate_id, reviewer_uuid)
        product = await session.get(LoanType, rate.loan_type_id)
        superseded = await _supersede_current(session, rate.loan_type_id)
        rate.status = APPROVED
        rate.checker_uuid = reviewer_uuid
        rate.reviewed_at = datetime.now(UTC)
        rate.review_note = note
        rate.version += 1
        await session.flush()
        await _audit(
            session,
            rate,
            AuditAction.COMMISSION_RATE_APPROVED,
            actor_uuid=reviewer_uuid,
            actor_role=reviewer_role,
            detail={"superseded_rate_id": str(superseded) if superseded else None},
        )
        await session.commit()
    await _notify_maker(_Decision(rate, product.label if product else "a product"), approved=True)
    return rate


async def reject(
    rate_id: uuid.UUID,
    *,
    reviewer_uuid: uuid.UUID,
    reviewer_role: str,
    note: str,
) -> ProductCommissionRate:
    async with db_session.AsyncSessionLocal() as session:
        rate = await _locked_pending(session, rate_id, reviewer_uuid)
        product = await session.get(LoanType, rate.loan_type_id)
        rate.status = CommissionRateStatus.REJECTED.value
        rate.checker_uuid = reviewer_uuid
        rate.reviewed_at = datetime.now(UTC)
        rate.review_note = note
        rate.version += 1
        await session.flush()
        await _audit(
            session,
            rate,
            AuditAction.COMMISSION_RATE_REJECTED,
            actor_uuid=reviewer_uuid,
            actor_role=reviewer_role,
        )
        await session.commit()
    await _notify_maker(_Decision(rate, product.label if product else "a product"), approved=False)
    return rate


# ---------------------------------------------------------------------------
# Commission entry pre-fill
# ---------------------------------------------------------------------------

SuggestionBasis = Literal["sanctioned", "requested", "fixed"]


def _paise(amount_rupees: Decimal | float | None) -> int | None:
    if amount_rupees is None:
        return None
    value = (Decimal(str(amount_rupees)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(value) if value > 0 else None


def suggest_commission(
    *,
    kind: str,
    percent_bps: int | None,
    amount_paise: int | None,
    amount_sanctioned: Decimal | float | None,
    amount_requested: Decimal | float | None,
) -> tuple[int | None, SuggestionBasis | None, int | None]:
    """(suggested paise, basis, basis amount in paise) for one disbursed loan.

    A fixed rate suggests its amount. A percent rate applies to the
    sanctioned amount, or the requested amount when no sanction was recorded
    (the contest "true amount" rule); integer paise, rounded half up, capped
    at the per-commission ceiling. No usable amount means no suggestion.
    """
    if kind == CommissionRateKind.FIXED:
        return amount_paise, "fixed", None
    if percent_bps is None:
        return None, None, None
    basis: SuggestionBasis = "sanctioned"
    basis_paise = _paise(amount_sanctioned)
    if basis_paise is None:
        basis, basis_paise = "requested", _paise(amount_requested)
    if basis_paise is None:
        return None, None, None
    suggested = (basis_paise * percent_bps + 5_000) // 10_000
    if suggested < 1:
        return None, basis, basis_paise
    return min(suggested, MAX_FIXED_COMMISSION_PAISE), basis, basis_paise
