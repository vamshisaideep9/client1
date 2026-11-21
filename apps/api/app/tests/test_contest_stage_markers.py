"""CS-027 loan / deal stage markers stamped by the progress services."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.loan import LoanApplication, LoanStatus
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.services.loan_applications import _stamp_stages as stamp_loan
from app.services.property_deals import _stamp_stages as stamp_deal


def _loan(status: LoanStatus, **fields) -> LoanApplication:
    return LoanApplication(status=status, **fields)


def test_forward_jump_stamps_every_loan_stage_it_passed() -> None:
    loan = _loan(LoanStatus.SANCTIONED)
    stamp_loan(loan)
    assert loan.submitted_at is not None
    assert loan.sanctioned_at is not None


def test_loan_stamps_are_set_once() -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    loan = _loan(LoanStatus.DISBURSED, submitted_at=earlier, sanctioned_at=earlier)
    stamp_loan(loan)
    assert loan.submitted_at == earlier
    assert loan.sanctioned_at == earlier


def test_closed_and_side_branches_do_not_stamp_loans() -> None:
    for status in (
        LoanStatus.CLOSED,
        LoanStatus.REJECTED,
        LoanStatus.ON_HOLD,
        LoanStatus.CONTACTED,
    ):
        loan = _loan(status)
        stamp_loan(loan)
        assert loan.submitted_at is None and loan.sanctioned_at is None, status
    loan = _loan(LoanStatus.UNDER_REVIEW)
    stamp_loan(loan)
    assert loan.submitted_at is not None and loan.sanctioned_at is None


def test_closing_a_deal_stamps_every_stage() -> None:
    deal = PropertyDeal(status=PropertyDealStatus.CLOSED)
    stamp_deal(deal)
    assert deal.site_visit_done_at and deal.booked_at and deal.agreement_signed_at


def test_deal_side_branches_and_early_stages() -> None:
    deal = PropertyDeal(status=PropertyDealStatus.NEGOTIATION)
    stamp_deal(deal)
    assert deal.site_visit_done_at is not None
    assert deal.booked_at is None and deal.agreement_signed_at is None
    rejected = PropertyDeal(status=PropertyDealStatus.REJECTED)
    stamp_deal(rejected)
    assert rejected.site_visit_done_at is None
