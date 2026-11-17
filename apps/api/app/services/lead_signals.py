"""Lead context shown beside lead lists and used by their filters.

For a page of leads this gathers, in a fixed number of queries regardless of
page size:

* through the confined ``lead_list_signals`` SECURITY DEFINER function
  (migrations ``f3a5c7e9b1d2`` and ``f1b3d5a7c9e2``): the client referral code,
  the latest call outcome / interest level, one entry per loan application
  (loan type, bank, status, requested amount) and per property deal (status,
  property category and subtype, quoted price), and — assigned Telecaller
  only — a summary of the loan transactions recorded on the lead. The function
  re-checks the caller's role, profile, business line and assignment (or, for
  an Agent, that they introduced the lead), so a lead outside the caller's
  scope yields no row;
* the introducing Agent's ``agent_code``, through ordinary ``agent_profiles``
  RLS (same-line Telecallers and Employees may read it).

``team_lead_signals_for_ids`` reads the same facts for a Sub Admin manager
through ``team_lead_signals`` (the manager's live team reach).

Only identifiers, enum values and the transaction summary leave this module
for a response (``facets`` / ``transaction_summary``): never the referrer's
name, mobile, reward state, call notes or the application and deal amounts,
which stay server-side for analytics filters. ``transaction_summary`` applies
the Admin's Telecaller field rules.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_visibility import FieldVisibilityMode
from app.models.lead import Lead, LeadOrigin
from app.models.profile import AgentProfile
from app.schemas.telecaller import (
    LeadDealFacet,
    LeadFacets,
    LeadLoanFacet,
    LeadReferrerRead,
    LeadTransactionItem,
    LeadTransactionSummary,
)

# Matches the functions' own bound; larger pages are split into chunks.
_CHUNK = 1000

_FACET_COLUMNS = (
    "last_disposition, last_interest_level, loan_items, deal_items, txn_count, "
    "txn_bank_names, txn_amount_min, txn_amount_max, txn_first_date, txn_last_date, txn_items"
)
_LEAD_SQL = text(
    f"SELECT lead_uuid, client_referral_code, NULL::text AS agent_code, {_FACET_COLUMNS} "
    "FROM lead_list_signals(:lead_uuids)"
).bindparams(bindparam("lead_uuids", type_=ARRAY(PG_UUID(as_uuid=True))))
_TEAM_SQL = text(
    f"SELECT lead_uuid, client_referral_code, agent_code, {_FACET_COLUMNS} "
    "FROM team_lead_signals(:lead_uuids)"
).bindparams(bindparam("lead_uuids", type_=ARRAY(PG_UUID(as_uuid=True))))


@dataclass(frozen=True)
class LoanItem:
    """One loan application on the lead (``amount`` = requested, server-side only)."""

    id: UUID
    loan_type_id: UUID
    loan_type_label: str | None
    bank_id: UUID | None
    bank_name: str | None
    status: str
    amount: Decimal | None


@dataclass(frozen=True)
class DealItem:
    """One property deal on the lead (``amount`` = quoted price, server-side only)."""

    id: UUID
    status: str
    category: str | None
    subtype: str | None
    amount: Decimal | None


@dataclass(frozen=True)
class TxnItem:
    txn_date: date | None
    bank_name: str | None
    amount: Decimal | None


@dataclass(frozen=True)
class TransactionSummary:
    """Loan transactions recorded on a lead (raw; apply field rules before use)."""

    count: int = 0
    bank_names: list[str] = field(default_factory=list)
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    first_date: date | None = None
    last_date: date | None = None
    # The latest transactions (bounded by the database function).
    items: tuple[TxnItem, ...] = ()


@dataclass(frozen=True)
class LeadSignals:
    referrer: LeadReferrerRead | None = None
    last_disposition: str | None = None
    last_interest_level: str | None = None
    loans: tuple[LoanItem, ...] = ()
    deals: tuple[DealItem, ...] = ()
    # None when the caller has no reach to the lead's loan transactions.
    transactions: TransactionSummary | None = None

    @property
    def loan_statuses(self) -> list[str]:
        """Distinct loan application statuses, sorted (the pre-CS-023 shape)."""
        return sorted({item.status for item in self.loans})


EMPTY_SIGNALS = LeadSignals()


@dataclass(frozen=True)
class _Row:
    client_code: str | None
    agent_code: str | None
    signals: LeadSignals


def _items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return list(value)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _uuid(value: Any) -> UUID | None:
    return None if value is None else UUID(str(value))


def _parse(row: Any) -> _Row:
    transactions = None
    if row["txn_count"] is not None:
        transactions = TransactionSummary(
            count=row["txn_count"],
            bank_names=list(row["txn_bank_names"] or []),
            amount_min=row["txn_amount_min"],
            amount_max=row["txn_amount_max"],
            first_date=row["txn_first_date"],
            last_date=row["txn_last_date"],
            items=tuple(
                TxnItem(
                    txn_date=(
                        date.fromisoformat(str(item["txn_date"])) if item.get("txn_date") else None
                    ),
                    bank_name=item.get("bank_name"),
                    amount=_decimal(item.get("amount")),
                )
                for item in _items(row["txn_items"])
            ),
        )
    loans = tuple(
        LoanItem(
            id=UUID(str(item["id"])),
            loan_type_id=UUID(str(item["loan_type_id"])),
            loan_type_label=item.get("loan_type_label"),
            bank_id=_uuid(item.get("bank_id")),
            bank_name=item.get("bank_name"),
            status=str(item["status"]),
            amount=_decimal(item.get("amount")),
        )
        for item in _items(row["loan_items"])
    )
    deals = tuple(
        DealItem(
            id=UUID(str(item["id"])),
            status=str(item["status"]),
            category=item.get("category"),
            subtype=item.get("subtype"),
            amount=_decimal(item.get("amount")),
        )
        for item in _items(row["deal_items"])
    )
    return _Row(
        client_code=row["client_referral_code"],
        agent_code=row["agent_code"],
        signals=LeadSignals(
            last_disposition=row["last_disposition"],
            last_interest_level=row["last_interest_level"],
            loans=loans,
            deals=deals,
            transactions=transactions,
        ),
    )


async def _read(db: AsyncSession, sql: Any, lead_ids: list[UUID]) -> dict[UUID, _Row]:
    out: dict[UUID, _Row] = {}
    for start in range(0, len(lead_ids), _CHUNK):
        rows = await db.execute(sql, {"lead_uuids": lead_ids[start : start + _CHUNK]})
        for row in rows.mappings():
            out[row["lead_uuid"]] = _parse(row)
    return out


async def lead_signals(db: AsyncSession, leads: Iterable[Lead]) -> dict[UUID, LeadSignals]:
    """Return signals keyed by lead id; leads outside the caller's scope get defaults."""
    by_id = {lead.id: lead for lead in leads}
    if not by_id:
        return {}
    rows = await _read(db, _LEAD_SQL, list(by_id))

    agent_ids = {
        lead.origin_agent_profile_uuid
        for lead in by_id.values()
        if lead.origin == LeadOrigin.AGENT and lead.origin_agent_profile_uuid is not None
    }
    agent_codes: dict[UUID, str] = {}
    if agent_ids:
        result = await db.execute(
            select(AgentProfile.id, AgentProfile.agent_code).where(AgentProfile.id.in_(agent_ids))
        )
        agent_codes = {agent_id: code for agent_id, code in result.all()}

    out: dict[UUID, LeadSignals] = {}
    for lead_id, lead in by_id.items():
        row = rows.get(lead_id)
        base = row.signals if row is not None else EMPTY_SIGNALS
        client_code = row.client_code if row is not None else None
        out[lead_id] = replace(base, referrer=_referrer(lead, agent_codes, client_code))
    return out


async def lead_signals_for_ids(
    db: AsyncSession, lead_ids: Iterable[UUID]
) -> dict[UUID, LeadSignals]:
    """Same as ``lead_signals`` for callers holding only lead ids (Employee tasks).

    Leads the caller cannot read under ``leads`` RLS are skipped, and callers
    fall back to empty signals for them.
    """
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return {}
    leads = (await db.scalars(select(Lead).where(Lead.id.in_(ids)))).all()
    return await lead_signals(db, leads)


async def team_lead_signals_for_ids(
    db: AsyncSession, lead_ids: Iterable[UUID]
) -> dict[UUID, LeadSignals]:
    """Signals for leads a Sub Admin manager reaches (``team_lead_signals``
    re-checks the live team reach); other leads are absent."""
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return {}
    out: dict[UUID, LeadSignals] = {}
    for lead_id, row in (await _read(db, _TEAM_SQL, ids)).items():
        referrer = None
        if row.agent_code:
            referrer = LeadReferrerRead(kind="agent", reference_id=row.agent_code)
        elif row.client_code:
            referrer = LeadReferrerRead(kind="client", reference_id=row.client_code)
        out[lead_id] = replace(row.signals, referrer=referrer)
    return out


def _referrer(
    lead: Lead, agent_codes: dict[UUID, str], client_code: str | None
) -> LeadReferrerRead | None:
    # An Agent-introduced lead is attributed to the Agent even if the person
    # also signed up through a client's link: the Agent owns the introduction.
    if lead.origin == LeadOrigin.AGENT and lead.origin_agent_profile_uuid in agent_codes:
        return LeadReferrerRead(
            kind="agent", reference_id=agent_codes[lead.origin_agent_profile_uuid]
        )
    if client_code:
        return LeadReferrerRead(kind="client", reference_id=client_code)
    return None


def facets(signals: LeadSignals) -> LeadFacets:
    """Ids and enums only: application and deal amounts never leave the server."""
    return LeadFacets(
        loans=[
            LeadLoanFacet(
                loan_type_id=item.loan_type_id,
                loan_type_label=item.loan_type_label,
                bank_id=item.bank_id,
                bank_name=item.bank_name,
                status=item.status,  # type: ignore[arg-type]
            )
            for item in signals.loans
        ],
        deals=[
            LeadDealFacet(
                status=item.status,  # type: ignore[arg-type]
                property_category=item.category,  # type: ignore[arg-type]
                property_subtype=item.subtype,  # type: ignore[arg-type]
            )
            for item in signals.deals
        ],
    )


# Admin field rules (Telecaller ``loan_transaction`` entity) per summary part.
_TXN_RULES = (("bank_name", "bank_names"), ("amount", "amount"), ("txn_date", "dates"))


def _money(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def transaction_summary(
    summary: TransactionSummary | None,
    modes: dict[tuple[str, str], FieldVisibilityMode],
    line: str,
) -> LeadTransactionSummary | None:
    """The summary as a response, with every part the Admin hides from
    Telecallers left out (null) and named in ``hidden_fields``. ``modes`` are
    the Telecaller field rules (a manager reads their Telecaller's rules).
    Loan transactions exist only on the loans line; other leads get null."""
    if summary is None or line != "loans":
        return None
    hidden = [
        part
        for rule, part in _TXN_RULES
        if modes.get(("loan_transaction", rule), FieldVisibilityMode.DENY)
        != FieldVisibilityMode.ALLOW
    ]
    banks_hidden = "bank_names" in hidden
    amount_hidden = "amount" in hidden
    dates_hidden = "dates" in hidden
    return LeadTransactionSummary(
        count=summary.count,
        bank_names=None if banks_hidden else summary.bank_names,
        amount_min=None if amount_hidden else _money(summary.amount_min),
        amount_max=None if amount_hidden else _money(summary.amount_max),
        first_date=None if dates_hidden else summary.first_date,
        last_date=None if dates_hidden else summary.last_date,
        items=[
            LeadTransactionItem(
                txn_date=None if dates_hidden else item.txn_date,
                bank_name=None if banks_hidden else item.bank_name,
                amount=None if amount_hidden else _money(item.amount),
            )
            for item in summary.items
        ],
        hidden_fields=hidden,  # type: ignore[arg-type]
    )
