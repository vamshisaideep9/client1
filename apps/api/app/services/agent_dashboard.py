"""Agent dashboard reads (CS-022): commission history, payout trail, lead history.

Every read goes through a confined SECURITY DEFINER database function
(migration ``e8b0d2f4a6c9``) that re-checks the Agent request context (role,
account, Agent profile, business line) and returns only projected columns.
New table policies were deliberately not added: they would also widen the
RLS-only routes that serve full loan applications and property deals to any
caller. This module runs on the request session, applies the filters and the
Admin's Agent field rules, and never touches the bypass session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_visibility import FieldVisibilityMode
from app.models.lead import Lead
from app.models.transaction import Transaction
from app.schemas.agent import (
    AgentHistoryApplication,
    AgentHistoryCall,
    AgentHistoryDeal,
    AgentHistoryEnquiry,
    AgentHistoryEvent,
    AgentHistoryServiceEnquiry,
    AgentHistorySiteVisit,
    AgentLeadHistoryRead,
)
from app.schemas.commissions import (
    AgentEarningsResponse,
    AgentEarningsRow,
    AgentEarningsTotals,
    AgentPayoutActor,
    AgentPayoutTrail,
    AgentTransactionDetail,
    AgentTransactionItem,
)

IST = ZoneInfo("Asia/Kolkata")

# Agent field rules (services/field_visibility.py CATALOGUE).
_LEAD_NAME = ("lead", "name")
_DEAL_AMOUNT = ("deal", "amount")
_CALL_NOTES = ("lead_history", "call_notes")
_HISTORY_STAFF = ("lead_history", "staff_names")
_PAYOUT_STAFF = ("payout", "staff_names")


def _utcnow() -> datetime:
    """Seam for tests; the month boundary is computed from this."""
    return datetime.now(UTC)


def previous_month(now: datetime) -> tuple[date, date, datetime, datetime]:
    """The previous calendar month in IST: (first day, last day, start, end).

    ``start``/``end`` are a half-open aware range: on 10 Nov 2026 IST this is
    1 Oct 00:00 IST (inclusive) to 1 Nov 00:00 IST (exclusive).
    """
    first_of_this_month = now.astimezone(IST).date().replace(day=1)
    last_day = first_of_this_month - timedelta(days=1)
    first_day = last_day.replace(day=1)
    return (
        first_day,
        last_day,
        datetime.combine(first_day, time.min, tzinfo=IST),
        datetime.combine(first_of_this_month, time.min, tzinfo=IST),
    )


def _visible(modes: Mapping[tuple[str, str], FieldVisibilityMode], key: tuple[str, str]) -> bool:
    return modes.get(key, FieldVisibilityMode.DENY) == FieldVisibilityMode.ALLOW


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _lead_status(status: str | None, agent_expired_at: object) -> str | None:
    if status is None:
        return None
    return "expired" if agent_expired_at is not None else status


def _as_mapping(raw: object) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------------------
# Commission history
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EarningsFilters:
    status: str | None = None
    deal_type: str | None = None
    product_id: UUID | None = None
    bank_id: UUID | None = None
    property_category: str | None = None
    amount_min_paise: int | None = None
    amount_max_paise: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = None


def _ist_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, ...]:
    start = datetime.combine(date_from, time.min, tzinfo=IST) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=IST) if date_to else None
    return start, end


def _matches(row: AgentEarningsRow, filters: EarningsFilters, name_visible: bool) -> bool:
    if filters.status and row.status != filters.status:
        return False
    if filters.deal_type and row.deal_type != filters.deal_type:
        return False
    if filters.product_id and row.product_uuid != filters.product_id:
        return False
    if filters.bank_id and row.bank_uuid != filters.bank_id:
        return False
    if filters.property_category and (row.property_category or "").casefold() != (
        filters.property_category.casefold()
    ):
        return False
    if filters.amount_min_paise is not None and row.agreed_amount_paise < filters.amount_min_paise:
        return False
    if filters.amount_max_paise is not None and row.agreed_amount_paise > filters.amount_max_paise:
        return False
    start, end = _ist_bounds(filters.date_from, filters.date_to)
    if start is not None and row.created_at < start:
        return False
    if end is not None and row.created_at >= end:
        return False
    if filters.q:
        needle = filters.q.strip().casefold()
        if needle:
            # A hidden client name is never searchable: matching on it would
            # reveal the value the Admin hid.
            texts = [row.product_label, row.bank_name, row.property_title]
            if name_visible:
                texts.append(row.client_name)
            ids = [str(row.id), str(row.lead_uuid) if row.lead_uuid else ""]
            if not any(needle in (value or "").casefold() for value in texts) and not any(
                value.startswith(needle) for value in ids if value
            ):
                return False
    return True


async def list_earnings(
    db: AsyncSession,
    *,
    filters: EarningsFilters,
    modes: Mapping[tuple[str, str], FieldVisibilityMode],
) -> AgentEarningsResponse:
    """The Agent's commission history on their line, newest first.

    Totals cover every commission (filters narrow the rows only), so the home
    card and the history page agree.
    """
    name_visible = _visible(modes, _LEAD_NAME)
    amount_visible = _visible(modes, _DEAL_AMOUNT)
    records = (await db.execute(text("SELECT * FROM agent_commission_ledger()"))).mappings().all()

    rows = [
        AgentEarningsRow(
            id=r["commission_uuid"],
            business_line=r["business_line"],
            deal_type=r["deal_type"],
            deal_uuid=r["deal_uuid"],
            agreed_amount_paise=r["agreed_amount_paise"],
            status=r["commission_status"],
            payout_txn_uuid=r["payout_txn_uuid"],
            created_at=r["created_at"],
            lead_uuid=r["lead_uuid"],
            lead_status=_lead_status(r["lead_status"], r["lead_agent_expired_at"]),
            client_name=r["lead_name"] if name_visible else None,
            product_uuid=r["product_uuid"],
            product_label=r["product_label"],
            bank_uuid=r["bank_uuid"],
            bank_name=r["bank_name"],
            property_uuid=r["property_uuid"],
            property_title=r["property_title"],
            property_category=r["property_category"],
            deal_status=r["deal_status"],
            deal_amount=_decimal(r["deal_amount"]) if amount_visible else None,
            paid_at=r["paid_at"],
        )
        for r in records
    ]

    first_day, last_day, start, end = previous_month(_utcnow())
    pending = sum(r.agreed_amount_paise for r in rows if r.status == "pending")
    paid = sum(r.agreed_amount_paise for r in rows if r.status == "paid")
    last_month_paid = sum(
        r.agreed_amount_paise
        for r in rows
        if r.status == "paid" and r.paid_at is not None and start <= r.paid_at < end
    )
    hidden = [
        key
        for key, visible in (("client_name", name_visible), ("deal_amount", amount_visible))
        if not visible
    ]
    return AgentEarningsResponse(
        rows=[row for row in rows if _matches(row, filters, name_visible)],
        totals=AgentEarningsTotals(
            pending_amount_paise=pending,
            paid_amount_paise=paid,
            total_amount_paise=pending + paid,
            last_month_paid_amount_paise=last_month_paid,
            last_month_start=first_day,
            last_month_end=last_day,
        ),
        hidden_fields=hidden,
    )


# ---------------------------------------------------------------------------
# Transaction detail
# ---------------------------------------------------------------------------


def _actor(raw: object, names_visible: bool) -> AgentPayoutActor | None:
    data = _as_mapping(raw)
    if data is None:
        return None
    return AgentPayoutActor(
        name=data.get("name") if names_visible else None,
        role=data.get("role"),
    )


async def transaction_detail(
    db: AsyncSession,
    *,
    transaction_id: UUID,
    owner_uuid: UUID,
    modes: Mapping[tuple[str, str], FieldVisibilityMode],
) -> AgentTransactionDetail | None:
    """One ledger row with the payout behind it and what it paid.

    Ownership is checked first on the request session (transactions RLS plus
    an explicit owner predicate); only then is the confined function asked for
    the payout trail. None means "not found" to the caller.
    """
    txn = await db.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_uuid == owner_uuid
        )
    )
    if txn is None:
        return None

    names_visible = _visible(modes, _PAYOUT_STAFF)
    name_visible = _visible(modes, _LEAD_NAME)
    amount_visible = _visible(modes, _DEAL_AMOUNT)
    detail = _as_mapping(
        await db.scalar(select(func.agent_transaction_detail(txn.id, type_=JSONB)))
    )

    payout: AgentPayoutTrail | None = None
    items: list[AgentTransactionItem] = []
    if detail is not None:
        raw_payout = _as_mapping(detail.get("payout"))
        if raw_payout is not None:
            approved_at = raw_payout.get("approved_at")
            checker = _actor(raw_payout.get("checker"), names_visible)
            payout = AgentPayoutTrail(
                status=raw_payout["status"],
                method=raw_payout["method"],
                provider=raw_payout["provider"],
                destination_hint=raw_payout["destination_hint"],
                requested_at=raw_payout["requested_at"],
                approved_at=approved_at,
                issued_at=raw_payout.get("issued_at"),
                paid_at=raw_payout.get("paid_at"),
                reversed_at=raw_payout.get("reversed_at"),
                requested_by=_actor(raw_payout.get("maker"), names_visible),
                approved_by=checker,
                approval_mode=(
                    "maker_checker"
                    if checker is not None
                    else ("standalone" if approved_at is not None else None)
                ),
            )
        for item in detail.get("items") or []:
            items.append(
                AgentTransactionItem(
                    commission_id=item["commission_id"],
                    amount_paise=item["amount_paise"],
                    status=item["status"],
                    deal_type=item["deal_type"],
                    deal_uuid=item["deal_uuid"],
                    lead_uuid=item["lead_uuid"],
                    client_name=item.get("lead_name") if name_visible else None,
                    product_label=item.get("product_label"),
                    bank_name=item.get("bank_name"),
                    property_title=item.get("property_title"),
                    deal_status=item.get("deal_status"),
                    deal_amount=_decimal(item.get("deal_amount")) if amount_visible else None,
                    entered_at=item["entered_at"],
                )
            )

    hidden = [
        key
        for key, visible in (
            ("client_name", name_visible),
            ("deal_amount", amount_visible),
            ("staff_names", names_visible),
        )
        if not visible
    ]
    return AgentTransactionDetail(
        id=txn.id,
        type=txn.type.value,
        status=txn.status.value,
        amount_paise=txn.amount_paise,
        currency=txn.currency,
        description=txn.description,
        created_at=txn.created_at,
        payout=payout,
        items=items,
        hidden_fields=hidden,
    )


# ---------------------------------------------------------------------------
# Lead history
# ---------------------------------------------------------------------------


def _section(raw: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    value = raw.get(key)
    return value if isinstance(value, list) else []


async def lead_history(
    db: AsyncSession,
    lead: Lead,
    modes: Mapping[tuple[str, str], FieldVisibilityMode],
) -> AgentLeadHistoryRead | None:
    """Everything that happened to a lead this Agent introduced.

    The caller has already loaded ``lead`` through the Agent's own RLS scope;
    the confined function re-checks the origin, account and line and answers
    None for anything else.
    """
    raw = _as_mapping(await db.scalar(select(func.agent_lead_history(lead.id, type_=JSONB))))
    if raw is None:
        return None

    notes_visible = _visible(modes, _CALL_NOTES)
    staff_visible = _visible(modes, _HISTORY_STAFF)
    amount_visible = _visible(modes, _DEAL_AMOUNT)

    def amount(value: object) -> Decimal | None:
        return _decimal(value) if amount_visible else None

    applications = [
        AgentHistoryApplication(
            id=a["id"],
            product_label=a.get("product_label"),
            bank_name=a.get("bank_name"),
            status=a["status"],
            amount_requested=amount(a.get("amount_requested")),
            amount_sanctioned=amount(a.get("amount_sanctioned")),
            opened_at=a["opened_at"],
            closed_at=a.get("closed_at"),
            disbursed_at=a.get("disbursed_at"),
        )
        for a in _section(raw, "applications")
    ]
    deals = [
        AgentHistoryDeal(
            id=d["id"],
            property_title=d.get("property_title"),
            property_category=d.get("property_category"),
            status=d["status"],
            price_quoted=amount(d.get("price_quoted")),
            booking_amount=amount(d.get("booking_amount")),
            opened_at=d["opened_at"],
            closed_at=d.get("closed_at"),
        )
        for d in _section(raw, "deals")
    ]
    calls = [
        AgentHistoryCall(
            id=c["id"],
            disposition=c["disposition"],
            interest_level=c.get("interest_level"),
            notes=c.get("notes") if notes_visible else None,
            follow_up_at=c.get("follow_up_at"),
            created_at=c["created_at"],
            staff_name=c.get("staff_name") if staff_visible else None,
        )
        for c in _section(raw, "calls")
    ]
    timeline = [
        AgentHistoryEvent(
            event="introduced",
            at=lead.created_at,
            request_id=None,
            from_status=None,
            to_status=None,
        ),
        *(
            AgentHistoryEvent(
                event=e["event"],
                at=e["at"],
                request_id=e.get("request_id"),
                from_status=e.get("from_status"),
                to_status=e.get("to_status"),
            )
            for e in _section(raw, "timeline")
        ),
    ]
    hidden = [
        key
        for key, visible in (
            ("call_notes", notes_visible),
            ("staff_names", staff_visible),
            ("deal_amount", amount_visible),
        )
        if not visible
    ]
    return AgentLeadHistoryRead(
        lead_id=lead.id,
        status=_lead_status(lead.status.value, lead.agent_expired_at) or lead.status.value,
        created_at=lead.created_at,
        applications=applications,
        service_enquiries=[
            AgentHistoryServiceEnquiry(
                id=s["id"],
                product_label=s.get("product_label"),
                product_category=s.get("product_category"),
                status=s["status"],
                submitted_at=s["submitted_at"],
            )
            for s in _section(raw, "service_enquiries")
        ],
        deals=deals,
        enquiries=[
            AgentHistoryEnquiry(
                id=q["id"],
                title=q["title"],
                locality=q.get("locality"),
                city=q.get("city"),
                status=q["status"],
                created_at=q["created_at"],
            )
            for q in _section(raw, "enquiries")
        ],
        site_visits=[
            AgentHistorySiteVisit(
                id=v["id"],
                title=v["title"],
                locality=v.get("locality"),
                city=v.get("city"),
                preferred_date=v["preferred_date"],
                preferred_time_slot=v["preferred_time_slot"],
                status=v["status"],
                created_at=v["created_at"],
            )
            for v in _section(raw, "site_visits")
        ],
        calls=calls,
        timeline=timeline,
        hidden_fields=hidden,
    )
