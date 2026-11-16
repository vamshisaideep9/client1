"""Replace the development provider catalogue with the lender policy workbook.

Run from the API container:

    uv run python -m app.scripts.seed_lender_policy            # dry run, rolls back
    uv run python -m app.scripts.seed_lender_policy --apply    # commit the replacement

The source is ``data/lender_policy_2026_08.json``: a verbatim transcription of
the user-supplied ``Bank loan policy.xlsx`` (last saved 2026-08-31) whose
provider identities are normalised explicitly in that file. Term cells are
parsed here, so a value the parser cannot read stays visible as text in the
offer summary instead of being guessed.

Replacement scope (one transaction):

* every provider offer for a loan-category product, plus every product the
  workbook covers (its insurance sheets included), is deleted. Loan
  applications and enquiries keep their immutable ``provider_offer_snapshot``;
  the database clears their optional offer link (``ON DELETE SET NULL``).
* offers for products the workbook does not cover and that are not loans
  (credit cards, life insurance) are left untouched.
* providers are reused by case-insensitive name, created when missing, and
  re-activated. A provider no longer referenced by any offer is deleted, unless
  a loan application still points at it, in which case it is deactivated.

Development-only: refuses to run unless ``ENV=development``. Inserts through
``AsyncSessionLocal`` as the database owner, like the other seeders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import base as _model_registry  # noqa: F401  # load all ORM models first
from app.models.loan import (
    Bank,
    BankLoanTypeAvailability,
    FinancialProductProviderOffer,
    LoanApplication,
    LoanType,
)
from app.schemas.financial_catalog import ProviderOfferCreate, ProviderType

DATA_FILE = Path(__file__).with_name("data") / "lender_policy_2026_08.json"
LENDER_POLICY_NAMESPACE = UUID("8f1b6c2e-4d3a-4f0e-9b7a-2c5d8e1f3a60")
IST = timezone(timedelta(hours=5, minutes=30))
# Workbook "last saved" timestamp; used as the honest verification date.
POLICY_VERIFIED_AT = datetime(2026, 8, 31, 8, 55, 42, tzinfo=IST)
# Interest above this is treated as a mislabelled cell (for example an LTV
# range typed into the ROI row), not as a lending rate.
MAX_PLAUSIBLE_RATE = Decimal("50")

_UNIT_MULTIPLIER = {"k": Decimal(1_000), "l": Decimal(1_00_000), "cr": Decimal(1_00_00_000)}
_AMOUNT_TOKEN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacks?|lacs?|l+|k)\b",
    re.IGNORECASE,
)
_TENURE_TOKEN = re.compile(r"(\d+)\s*(m|y)?\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NOT_AVAILABLE = {"", "na", "n/a", "nil", "nill", "-"}


class LenderPolicySeedError(RuntimeError):
    """The data file or target database cannot be reconciled safely."""


def _require_development() -> None:
    if settings.ENV != "development":
        raise SystemExit(
            f"seed_lender_policy is development-only; refusing to run with ENV={settings.ENV!r}."
        )


def policy_uuid(key: str) -> UUID:
    return uuid5(LENDER_POLICY_NAMESPACE, f"v1:{key}")


def _is_missing(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in _NOT_AVAILABLE


def _is_case_by_case(raw: str) -> bool:
    return "case" in raw.lower()


# --- term parsers -----------------------------------------------------------


def parse_amount_range(raw: str | None) -> tuple[Decimal | None, Decimal | None] | None:
    """Parse "50K to 40L" / "up to 5L" / "min 5L to--" into rupee bounds.

    Returns ``None`` when the cell cannot be read; a one-sided range keeps the
    missing side as ``None``. A maximum below its minimum keeps only the
    minimum, because the cell is self-contradictory.
    """
    if _is_missing(raw) or _is_case_by_case(raw or ""):
        return None
    text = (raw or "").replace("₹", "").replace(",", "").replace("+", " ")
    values: list[Decimal] = []
    for number, unit in _AMOUNT_TOKEN.findall(text):
        unit = unit.lower()
        key = "cr" if unit.startswith("cr") else "k" if unit == "k" else "l"
        values.append((Decimal(number) * _UNIT_MULTIPLIER[key]).quantize(Decimal(1)))
    if not values:
        return None
    lowered = text.lower()
    if len(values) == 1:
        if "up to" in lowered or "upto" in lowered:
            return None, values[0]
        return values[0], None
    low, high = values[0], values[1]
    if high < low:
        return low, None
    return low, high


def parse_tenure_months(raw: str | None) -> tuple[int | None, int | None] | None:
    """Parse "12M to 84M" / "1Y to 30Y" / "12 m up to 10 y" / "up to 48"."""
    if _is_missing(raw) or _is_case_by_case(raw or ""):
        return None
    tokens = _TENURE_TOKEN.findall(raw or "")
    if not tokens:
        return None
    default_unit = next((unit.lower() for _, unit in tokens if unit), "m")
    months = [
        int(value) * (12 if (unit or default_unit).lower() == "y" else 1) for value, unit in tokens
    ]
    months = [value for value in months if 1 <= value <= 600]
    if not months:
        return None
    lowered = (raw or "").lower()
    if len(months) == 1:
        if lowered.strip().startswith("up to") or lowered.strip().startswith("upto"):
            return None, months[0]
        return months[0], None
    low, high = months[0], months[1]
    if high < low:
        return low, None
    return low, high


def parse_rate_range(raw: str | None) -> tuple[Decimal | None, Decimal | None] | None:
    """Parse "9.99.% TO 21%" / "From 16% p.a." / "7.15% to ----"."""
    if _is_missing(raw) or _is_case_by_case(raw or ""):
        return None
    numbers = [Decimal(value) for value in _NUMBER.findall(raw or "")][:2]
    if not numbers or any(value > MAX_PLAUSIBLE_RATE for value in numbers):
        return None
    quantum = Decimal("0.001")
    numbers = [value.quantize(quantum) for value in numbers]
    if len(numbers) == 1:
        lowered = (raw or "").lower()
        if "up to" in lowered:
            return None, numbers[0]
        return numbers[0], None
    low, high = numbers
    if high < low:
        return low, None
    return low, high


def _tidy(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip().rstrip(".")
    text = re.sub(r"\b(lakhs?|lacks?|lacs?)\b", "L", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)\s*k\b", r"\1K", text)
    text = re.sub(r"(\d)\s*cr\b", r"\1 Cr", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcase-to-case\b", "case by case", text, flags=re.IGNORECASE)
    return text


def processing_fee_text(raw: str | None) -> str | None:
    if _is_missing(raw):
        return None
    text = _tidy(raw or "")
    text = re.sub(r"^up to\b", "Up to", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\+$", "+", text)
    return text[:240] or None


def _age_text(raw: str | None) -> str | None:
    if _is_missing(raw):
        return None
    numbers = re.findall(r"\d+", raw or "")
    if len(numbers) >= 2:
        return f"Age {numbers[0]}–{numbers[1]}"
    return None


def _cibil_text(raw: str | None) -> str | None:
    if _is_missing(raw):
        return None
    numbers = re.findall(r"\d+", raw or "")
    return f"CIBIL {numbers[0]}+" if numbers else None


def eligibility_summary(terms: dict[str, str]) -> str | None:
    parts: list[str] = []
    if age := _age_text(terms.get("age")):
        parts.append(age)
    salary = terms.get("min_net_monthly_salary")
    if not _is_missing(salary):
        parts.append(f"Min net monthly salary ₹{_tidy(salary or '')}")
    income = terms.get("min_net_income")
    if not _is_missing(income):
        parts.append(f"Min net income ₹{_tidy(income or '')}")
    turnover = terms.get("min_turnover")
    if not _is_missing(turnover):
        parts.append(f"Min turnover ₹{_tidy(turnover or '')}")
    vintage = terms.get("business_vintage")
    if not _is_missing(vintage):
        parts.append(f"Business vintage {_tidy(vintage or '').lower()}")
    if cibil := _cibil_text(terms.get("cibil")):
        parts.append(cibil)
    return " · ".join(parts)[:500] or None


# --- offer construction -----------------------------------------------------


@dataclass(frozen=True)
class OfferSpec:
    product: str
    provider: str
    variant: str | None
    display_order: int
    offer_name_suffix: str
    summary: str
    min_amount: Decimal | None
    max_amount: Decimal | None
    min_interest_rate: Decimal | None
    max_interest_rate: Decimal | None
    min_tenure_months: int | None
    max_tenure_months: int | None
    processing_fee_text: str | None
    eligibility_summary: str | None

    @property
    def key(self) -> str:
        return f"{self.product}|{self.provider.lower()}|{(self.variant or '').lower()}"


@dataclass
class PolicyData:
    providers: dict[str, str]
    offers: list[OfferSpec]
    duplicates_skipped: list[str] = field(default_factory=list)

    @property
    def products(self) -> set[str]:
        return {offer.product for offer in self.offers}


def _summary(provider: str, terms: dict[str, str], unread: list[str]) -> str:
    if not terms:
        text = (
            f"{provider} is an available partner for this product. Terms are shared "
            "after an assessment of your profile."
        )
    else:
        text = (
            "Indicative terms from the partner policy sheet. Final eligibility, rate, "
            f"amount and fees are decided by {provider} after assessment."
        )
    secured = terms.get("secured_amount")
    if not _is_missing(secured):
        text += f" Secured option: {_tidy(secured or '')}."
    if unread:
        text += " " + " ".join(unread)
    return text[:500]


def build_offer_spec(product: str, entry: dict[str, Any], display_order: int) -> OfferSpec:
    provider = entry["provider"]
    variant = entry.get("variant")
    terms: dict[str, str] = {key: str(value) for key, value in entry.get("terms", {}).items()}
    unread: list[str] = []

    # Only an explicit "case to case" cell is surfaced as text. Any other cell
    # the parser cannot read (for example an LTV range typed into the ROI row)
    # is dropped rather than published as a misleading term.
    for key, label in (
        ("amount", "Loan amount"),
        ("tenure", "Tenure"),
        ("interest_rate", "Interest"),
    ):
        value = terms.get(key)
        if not _is_missing(value) and _is_case_by_case(value or ""):
            unread.append(f"{label}: case by case.")
    amount = parse_amount_range(terms.get("amount"))
    tenure = parse_tenure_months(terms.get("tenure"))
    rate = parse_rate_range(terms.get("interest_rate"))

    return OfferSpec(
        product=product,
        provider=provider,
        variant=variant,
        display_order=display_order,
        offer_name_suffix=f" ({variant})" if variant else "",
        summary=_summary(provider, terms, unread),
        min_amount=amount[0] if amount else None,
        max_amount=amount[1] if amount else None,
        min_interest_rate=rate[0] if rate else None,
        max_interest_rate=rate[1] if rate else None,
        min_tenure_months=tenure[0] if tenure else None,
        max_tenure_months=tenure[1] if tenure else None,
        processing_fee_text=processing_fee_text(terms.get("processing_fee")),
        eligibility_summary=eligibility_summary(terms),
    )


def load_policy(path: Path = DATA_FILE) -> PolicyData:
    raw = json.loads(path.read_text(encoding="utf-8"))
    providers: dict[str, str] = {}
    for name, meta in raw["providers"].items():
        provider_type = ProviderType(meta["provider_type"])
        providers[name] = provider_type.value
    offers: list[OfferSpec] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for product in raw["products"]:
        for index, entry in enumerate(product["offers"], start=1):
            if entry["provider"] not in providers:
                raise LenderPolicySeedError(
                    f"Offer provider {entry['provider']!r} is missing from the providers table."
                )
            spec = build_offer_spec(product["product"], entry, display_order=index * 10)
            if spec.key in seen:
                duplicates.append(f"{product['sheet']}: {entry['source_name']}")
                continue
            seen.add(spec.key)
            offers.append(spec)
    return PolicyData(providers=providers, offers=offers, duplicates_skipped=duplicates)


# --- database replacement ---------------------------------------------------


async def replace_catalogue(
    db: AsyncSession, policy: PolicyData, *, verified_at: datetime = POLICY_VERIFIED_AT
) -> dict[str, int]:
    """Apply the replacement inside the caller's transaction; never commits."""
    products = {product.name: product for product in (await db.scalars(select(LoanType))).all()}
    missing = sorted(policy.products - products.keys())
    if missing:
        raise LenderPolicySeedError(
            f"Products missing from loan_types (run `alembic upgrade head`): {missing}"
        )
    cleared_ids = {
        product.id
        for product in products.values()
        if product.category == "loan" or product.name in policy.products
    }

    deleted_offers = (
        await db.execute(
            delete(FinancialProductProviderOffer).where(
                FinancialProductProviderOffer.loan_type_id.in_(cleared_ids)
            )
        )
    ).rowcount or 0
    await db.execute(
        delete(BankLoanTypeAvailability).where(
            BankLoanTypeAvailability.loan_type_id.in_(cleared_ids)
        )
    )

    existing_banks = (await db.scalars(select(Bank))).all()
    by_name: dict[str, Bank] = {}
    for bank in existing_banks:
        by_name.setdefault(bank.name.strip().lower(), bank)

    created_providers = 0
    reused_providers = 0
    banks: dict[str, Bank] = {}
    for name, provider_type in sorted(policy.providers.items()):
        bank = by_name.get(name.lower())
        if bank is None:
            bank = Bank(
                id=policy_uuid(f"provider:{name.lower()}"),
                name=name,
                provider_type=provider_type,
                active=True,
            )
            db.add(bank)
            created_providers += 1
        else:
            bank.provider_type = provider_type
            bank.active = True
            reused_providers += 1
        banks[name] = bank
    await db.flush()

    created_offers = 0
    for spec in policy.offers:
        product = products[spec.product]
        bank = banks[spec.provider]
        payload = ProviderOfferCreate(
            loan_type_id=product.id,
            bank_id=bank.id,
            offer_name=f"{spec.provider} {product.label}{spec.offer_name_suffix}"[:160],
            summary=spec.summary,
            published=True,
            display_order=spec.display_order,
            min_amount=spec.min_amount,
            max_amount=spec.max_amount,
            min_interest_rate=spec.min_interest_rate,
            max_interest_rate=spec.max_interest_rate,
            min_tenure_months=spec.min_tenure_months,
            max_tenure_months=spec.max_tenure_months,
            processing_fee_text=spec.processing_fee_text,
            eligibility_summary=spec.eligibility_summary,
            last_verified_at=verified_at,
        )
        db.add(
            FinancialProductProviderOffer(
                id=policy_uuid(f"offer:{spec.key}"),
                **payload.model_dump(),
            )
        )
        created_offers += 1
    await db.flush()

    in_use = select(FinancialProductProviderOffer.bank_id).distinct()
    referenced = select(LoanApplication.bank_id).where(LoanApplication.bank_id.is_not(None))
    keep = {bank.id for bank in banks.values()}
    orphans = (
        await db.scalars(select(Bank).where(Bank.id.not_in(in_use), Bank.id.not_in(keep)))
    ).all()
    referenced_ids = set((await db.scalars(referenced)).all())
    deleted_providers = 0
    deactivated_providers = 0
    for bank in orphans:
        if bank.id in referenced_ids:
            bank.active = False
            deactivated_providers += 1
        else:
            await db.delete(bank)
            deleted_providers += 1
    await db.flush()

    return {
        "deleted_offers": int(deleted_offers),
        "created_offers": created_offers,
        "created_providers": created_providers,
        "reused_providers": reused_providers,
        "deleted_providers": deleted_providers,
        "deactivated_providers": deactivated_providers,
        "duplicate_rows_skipped": len(policy.duplicates_skipped),
    }


async def _offer_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(FinancialProductProviderOffer)) or 0
    )


async def seed_lender_policy(*, apply: bool) -> dict[str, int]:
    _require_development()
    from app.db.session import AsyncSessionLocal

    policy = load_policy()
    async with AsyncSessionLocal() as db:
        result = await replace_catalogue(db, policy)
        result["total_offers_after"] = await _offer_count(db)
        if apply:
            await db.commit()
        else:
            await db.rollback()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the replacement. Without it the run is rolled back (dry run).",
    )
    args = parser.parse_args()
    _require_development()
    result = asyncio.run(seed_lender_policy(apply=args.apply))
    mode = "Applied" if args.apply else "Dry run (rolled back)"
    print(f"[seed_lender_policy] {mode}: {result}")


if __name__ == "__main__":
    main()
