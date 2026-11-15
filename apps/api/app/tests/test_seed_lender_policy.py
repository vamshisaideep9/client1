"""Development lender-policy catalogue replacement (app.scripts.seed_lender_policy)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.loan import Bank, FinancialProductProviderOffer, LoanApplication, LoanType
from app.models.profile import ClientProfile, ProfileStatus
from app.models.user import User, UserStatus
from app.schemas.financial_catalog import ProviderType
from app.scripts.seed_lender_policy import (
    DATA_FILE,
    POLICY_VERIFIED_AT,
    eligibility_summary,
    load_policy,
    parse_amount_range,
    parse_rate_range,
    parse_tenure_months,
    processing_fee_text,
    replace_catalogue,
)
from conftest import unique_email, unique_mobile

L = Decimal(1_00_000)
CR = Decimal(1_00_00_000)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("50K to 40L", (Decimal(50_000), 40 * L)),
        ("1lL to 50L", (L, 50 * L)),
        ("1.5k TO 5L", (Decimal(1_500), 5 * L)),
        ("Up to ₹75 Lakh", (None, 75 * L)),
        ("1 lakh to ₹10+ crore", (L, 10 * CR)),
        ("3L  to 1 Crore", (3 * L, CR)),
        ("50K to 7.50L", (Decimal(50_000), Decimal(7_50_000))),
        ("min 5L to--", (5 * L, None)),
        ("8 L to ----", (8 * L, None)),
        ("2L to 75K", (2 * L, None)),  # self-contradictory maximum is dropped
        ("case-to-case", None),
        ("na", None),
        (None, None),
    ],
)
def test_parse_amount_range(raw, expected) -> None:
    assert parse_amount_range(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12M to 84M", (12, 84)),
        ("1Y to 30Y", (12, 360)),
        ("12 m up to 10 y", (12, 120)),
        ("Up to 60 m", (None, 60)),
        ("up to 48", (None, 48)),
        ("12M to 120M", (12, 120)),
        ("case-to-case", None),
    ],
)
def test_parse_tenure_months(raw, expected) -> None:
    assert parse_tenure_months(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9.99.% TO 21%", (Decimal("9.990"), Decimal("21.000"))),
        ("11% 36%", (Decimal("11.000"), Decimal("36.000"))),
        ("15.50% to 26.00% (44.90%)", (Decimal("15.500"), Decimal("26.000"))),
        ("From 16% p.a.", (Decimal("16.000"), None)),
        ("7.15% to ----", (Decimal("7.150"), None)),
        ("70% to 80%", None),  # an LTV typed into the ROI row is not a rate
        ("case-to-case", None),
    ],
)
def test_parse_rate_range(raw, expected) -> None:
    assert parse_rate_range(raw) == expected


def test_term_text_normalisation() -> None:
    assert processing_fee_text("up to 2.5%") == "Up to 2.5%"
    assert processing_fee_text("na") is None
    assert (
        eligibility_summary(
            {
                "age": "21Y TO 65Y",
                "min_net_income": "3 Lacks",
                "min_turnover": "40 L",
                "business_vintage": "3 years.",
                "cibil": "700+",
            }
        )
        == "Age 21–65 · Min net income ₹3 L · Min turnover ₹40 L · "
        "Business vintage 3 years · CIBIL 700+"
    )
    assert eligibility_summary({"cibil": "nill"}) is None


def test_policy_file_loads_every_sheet_with_valid_providers() -> None:
    policy = load_policy(DATA_FILE)

    assert policy.products == {
        "personal-loan",
        "business-loan",
        "home-loan",
        "loan-against-property",
        "car-loan",
        "vehicle-loan",
        "education-loan",
        "school-funding",
        "equipment-financing",
        "od-and-dod",
        "travel-insurance",
        "health-insurance",
        "property-insurance",
    }
    assert len(policy.offers) == 303
    assert sorted(policy.duplicates_skipped) == ["BL: MAS FINANCIALS", "EL: EMPOWER"]
    assert len({offer.key for offer in policy.offers}) == len(policy.offers)
    assert {offer.provider for offer in policy.offers} == set(policy.providers)
    assert all(ProviderType(value) for value in policy.providers.values())
    assert all(len(offer.summary) <= 500 for offer in policy.offers)
    # An implausible ROI cell must never surface as public copy.
    assert not any("70%" in offer.summary for offer in policy.offers)


async def _loan_application_for(db, bank: Bank) -> LoanApplication:
    user = User(
        first_name="Policy",
        last_name="Client",
        mobile=unique_mobile(),
        email=unique_email(),
        password_hash="unused",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.flush()
    client = ClientProfile(
        auth_user_uuid=user.id,
        business_line="loans",
        customer_code=f"CL-T{uuid.uuid4().hex[:8].upper()}",
        status=ProfileStatus.ACTIVE,
    )
    db.add(client)
    await db.flush()
    lead = Lead(
        client_profile_uuid=client.id,
        business_line="loans",
        origin=LeadOrigin.DIRECT,
        name="Policy Client",
        mobile=user.mobile,
        requirement={"product": "Personal Loan"},
        detail_ownership={},
        status=LeadStatus.CLOSED,
    )
    db.add(lead)
    await db.flush()
    personal = await db.scalar(select(LoanType).where(LoanType.name == "personal-loan"))
    application = LoanApplication(
        lead_uuid=lead.id,
        client_profile_uuid=client.id,
        business_line="loans",
        loan_type_id=personal.id,
        bank_id=bank.id,
    )
    db.add(application)
    await db.flush()
    return application


@pytest.mark.asyncio
async def test_replace_catalogue_swaps_loan_offers_and_preserves_references() -> None:
    from app.db.session import AsyncSessionLocal

    policy = load_policy(DATA_FILE)
    async with AsyncSessionLocal() as db:
        try:
            products = {
                product.name: product for product in (await db.scalars(select(LoanType))).all()
            }
            suffix = uuid.uuid4().hex[:8]
            legacy = Bank(name=f"Legacy Lender {suffix}", provider_type="bank")
            referenced = Bank(name=f"Referenced Lender {suffix}", provider_type="nbfc")
            card_issuer = Bank(name=f"Card Issuer {suffix}", provider_type="other")
            existing_hdfc = await db.scalar(
                select(Bank).where(func.lower(Bank.name) == "hdfc bank")
            )
            if existing_hdfc is None:
                existing_hdfc = Bank(name="HDFC Bank", provider_type="bank", active=False)
                db.add(existing_hdfc)
            db.add_all([legacy, referenced, card_issuer])
            await db.flush()
            for bank, product in (
                (legacy, "personal-loan"),
                (referenced, "home-loan"),
                (card_issuer, "credit-cards"),
            ):
                db.add(
                    FinancialProductProviderOffer(
                        loan_type_id=products[product].id,
                        bank_id=bank.id,
                        offer_name=f"{bank.name} offer",
                    )
                )
            await db.flush()
            application = await _loan_application_for(db, referenced)

            result = await replace_catalogue(db, policy)

            assert result["created_offers"] == len(policy.offers)
            assert result["duplicate_rows_skipped"] == 2
            # The unreferenced legacy lender is gone; the referenced one survives
            # deactivated so the application keeps its provider.
            assert await db.get(Bank, legacy.id) is None
            await db.refresh(referenced)
            assert referenced.active is False
            await db.refresh(application)
            assert application.bank_id == referenced.id
            # Non-loan products outside the workbook keep their offers and providers.
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(FinancialProductProviderOffer)
                    .where(FinancialProductProviderOffer.bank_id == card_issuer.id)
                )
                == 1
            )
            # Existing providers are reused by name, not duplicated.
            await db.refresh(existing_hdfc)
            assert existing_hdfc.active is True
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Bank)
                    .where(func.lower(Bank.name) == "hdfc bank")
                )
                == 1
            )
            personal_offers = (
                await db.scalars(
                    select(FinancialProductProviderOffer).where(
                        FinancialProductProviderOffer.loan_type_id == products["personal-loan"].id
                    )
                )
            ).all()
            expected = [o for o in policy.offers if o.product == "personal-loan"]
            assert len(personal_offers) == len(expected)
            assert all(
                o.published and o.last_verified_at == POLICY_VERIFIED_AT for o in personal_offers
            )
            axis = next(o for o in personal_offers if o.offer_name == "Axis Bank Personal Loan")
            assert (axis.min_amount, axis.max_amount) == (
                Decimal("50000.00"),
                Decimal("4000000.00"),
            )
            assert (axis.min_tenure_months, axis.max_tenure_months) == (12, 84)

            # A rerun converges on the same catalogue.
            ids_before = {o.id for o in personal_offers}
            again = await replace_catalogue(db, policy)
            assert again["created_providers"] == 0
            assert again["deleted_offers"] >= len(policy.offers)
            ids_after = set(
                (
                    await db.scalars(
                        select(FinancialProductProviderOffer.id).where(
                            FinancialProductProviderOffer.loan_type_id
                            == products["personal-loan"].id
                        )
                    )
                ).all()
            )
            assert ids_after == ids_before
        finally:
            await db.rollback()
