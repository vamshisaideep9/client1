"""Regression coverage for development-only synthetic seed values."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.security import validate_password_policy
from app.models.property import (
    PROPERTY_CATEGORY_BY_SUBTYPE,
    ListingIntent,
    PropertyCategory,
    PropertySubtype,
    ReraApplicability,
    ReraVerificationStatus,
)
from app.models.property_submission import PropertySubmission, SubmissionStatus
from app.scripts.demo_catalog import (
    DEMO_ACCOUNT_BY_KEY,
    DEMO_ACCOUNTS,
    DEMO_PASSWORD,
    credentials_table,
    demo_uuid,
)
from app.scripts.seed_demo import (
    _assert_demo_api_data,
    _property_submission_rows,
    _require_development,
)
from app.scripts.seed_helpers import dev_indian_mobile, dev_seed_email


def _demo_identities() -> tuple[dict[str, Any], dict[str, Any]]:
    users = {
        key: SimpleNamespace(id=demo_uuid(f"user:{key}"))
        for key in ("admin", "agent_real_estate", "sub_admin")
    }
    properties = {
        key: SimpleNamespace(id=demo_uuid(f"property:{key}"), title=title)
        for key, title in (
            ("villa", "Demo Lakeview Villa"),
            ("apartment", "Demo Metro Apartment"),
            ("plot", "Demo Gated Community Plot"),
        )
    }
    return users, properties


def test_dev_indian_mobile_has_ten_digit_indian_local_number() -> None:
    numbers = [dev_indian_mobile() for _ in range(20)]

    assert all(re.fullmatch(r"\+91[6-9]\d{9}", number) for number in numbers)


def test_dev_seed_email_normalizes_valid_address() -> None:
    assert dev_seed_email("Admin@EXAMPLE.com") == "Admin@example.com"


def test_dev_seed_email_rejects_reserved_domain() -> None:
    with pytest.raises(ValueError, match="non-reserved"):
        dev_seed_email("admin.local@example.test")


def test_demo_credentials_are_complete_synthetic_and_policy_valid() -> None:
    expected_keys = {
        "admin",
        "admin_checker",
        "sub_admin",
        "client",
        "client_referred",
        "agent_loans",
        "agent_real_estate",
        "telecaller_loans",
        "telecaller_real_estate",
        "employee_loans",
        "employee_real_estate",
    }

    assert set(DEMO_ACCOUNT_BY_KEY) == expected_keys
    assert len({account.mobile for account in DEMO_ACCOUNTS}) == len(DEMO_ACCOUNTS)
    assert len({account.email for account in DEMO_ACCOUNTS}) == len(DEMO_ACCOUNTS)
    assert all(account.mobile.startswith("+919000001") for account in DEMO_ACCOUNTS)
    assert all(account.email.endswith(".demo@example.com") for account in DEMO_ACCOUNTS)
    for account in DEMO_ACCOUNTS:
        validate_password_policy(DEMO_PASSWORD, account.mobile)


def test_demo_ids_and_credential_output_are_deterministic() -> None:
    assert demo_uuid("user:admin") == demo_uuid("user:admin")
    assert demo_uuid("user:admin") != demo_uuid("user:sub_admin")
    output = credentials_table()
    assert output.count(DEMO_PASSWORD) == len(DEMO_ACCOUNTS)
    assert all(account.mobile in output for account in DEMO_ACCOUNTS)


def test_demo_seed_refuses_non_development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scripts.seed_demo.settings.ENV", "staging")

    with pytest.raises(SystemExit, match="development-only"):
        _require_development()


@pytest.mark.parametrize(
    ("account_key", "endpoint", "payload"),
    [
        ("admin", "/api/v1/admin/home", {"pending_review": [], "open_count": 0}),
        ("sub_admin", "/api/v1/sub-admin/home", {"pending_approval": []}),
        ("client", "/api/v1/loans/applications", {"applications": []}),
        ("client", "/api/v1/site-visits", {"visits": []}),
        ("agent_loans", "/api/v1/agent/home", {"counts_by_status": {}}),
        ("telecaller_loans", "/api/v1/telecaller/home", {"counts_by_status": {}}),
        ("employee_loans", "/api/v1/employee/home", {"counts_by_status": {}}),
    ],
)
def test_demo_api_verification_rejects_empty_role_data(
    account_key: str, endpoint: str, payload: dict[str, object]
) -> None:
    with pytest.raises(RuntimeError, match="no representative data"):
        _assert_demo_api_data(account_key, endpoint, payload)


def test_demo_api_verification_accepts_populated_role_data() -> None:
    examples = (
        ("admin", "/api/v1/admin/home", {"pending_banners_count": 1}),
        ("sub_admin", "/api/v1/sub-admin/home", {"pending_approval": [{"id": "demo"}]}),
        ("client", "/api/v1/loans/applications", {"applications": [{"id": "demo"}]}),
        ("client", "/api/v1/site-visits", {"visits": [{"id": "demo"}]}),
        ("agent_loans", "/api/v1/agent/home", {"counts_by_status": {"working": 1}}),
        (
            "telecaller_loans",
            "/api/v1/telecaller/home",
            {"counts_by_status": {"assigned": 1}},
        ),
        (
            "employee_loans",
            "/api/v1/employee/home",
            {"counts_by_status": {"in_progress": 1}},
        ),
    )

    for account_key, endpoint, payload in examples:
        _assert_demo_api_data(account_key, endpoint, payload)


def test_demo_sub_admin_listings_cover_every_listing_filter() -> None:
    users, properties = _demo_identities()
    rows = _property_submission_rows(users, properties, datetime.now(UTC))
    assert len({row.id for row in rows}) == len(rows)

    mine = [row for row in rows if row.submitter_uuid == users["sub_admin"].id]
    assert len(mine) == 11
    assert Counter(row.status for row in mine) == {
        SubmissionStatus.PENDING: 5,
        SubmissionStatus.APPROVED: 2,
        SubmissionStatus.REJECTED: 2,
        SubmissionStatus.WITHDRAWN: 2,
    }
    assert {row.listing_intent for row in mine} == set(ListingIntent)
    assert {row.category for row in mine} == set(PropertyCategory)
    assert {row.property_subtype for row in mine} == set(PropertySubtype)
    assert {row.rera_verification_status for row in mine} == set(ReraVerificationStatus)
    assert {row.rera_applicability for row in mine} == set(ReraApplicability)
    assert len({row.city for row in mine}) == 3
    assert len({row.bhk for row in mine}) >= 4
    assert len({row.furnishing for row in mine}) == 4  # three levels plus none
    for row in mine:
        assert PROPERTY_CATEGORY_BY_SUBTYPE[row.property_subtype] == row.category
        assert row.location == f"{row.locality}, {row.city}"
        if row.listing_intent == ListingIntent.RENT:
            assert row.security_deposit_paise and row.minimum_lease_months
        else:
            assert row.security_deposit_paise is None
        if row.status == SubmissionStatus.REJECTED:
            assert row.review_note and row.reviewed_by_uuid == users["admin"].id
        elif row.status != SubmissionStatus.APPROVED:
            assert row.reviewed_by_uuid is None and row.reviewed_at is None


def test_demo_approved_listings_link_distinct_unclaimed_properties() -> None:
    users, properties = _demo_identities()
    rows = _property_submission_rows(users, properties, datetime.now(UTC))
    links = [row.approved_property_id for row in rows if row.status == SubmissionStatus.APPROVED]
    assert all(links) and len(links) == len(set(links)) == len(properties)
    for row in rows:
        assert (row.approved_property_id is not None) == (row.status == SubmissionStatus.APPROVED)
        if row.approved_property_id is not None:
            origin = next(p for p in properties.values() if p.id == row.approved_property_id)
            assert row.title == origin.title
            assert row.rera_verification_status == ReraVerificationStatus.VERIFIED


def test_original_demo_submissions_keep_their_identity_and_facts() -> None:
    users, properties = _demo_identities()
    now = datetime.now(UTC)
    by_id = {row.id: row for row in _property_submission_rows(users, properties, now)}
    for key in ("agent-pending", "agent-approved", "agent-rejected", "sub-admin-pending"):
        row = by_id[demo_uuid(f"property-submission:{key}")]
        assert (row.location, row.price_paise, row.bhk, row.area_sqft, row.meta) == (
            "Kondapur, Hyderabad",
            1_20_00_00_000,
            3,
            1750,
            "3 bed · 1,750 sqft",
        )
        assert row.listing_intent == ListingIntent.SALE
        assert row.rera_number == "RERA/TS/DEMO/SUB01"
    rejected = by_id[demo_uuid("property-submission:agent-rejected")]
    assert rejected.review_note == "Synthetic rejection: clarify the ownership narrative."
    assert rejected.rera_verification_status == ReraVerificationStatus.NOT_REVIEWED


@pytest.mark.asyncio
async def test_demo_submission_seed_writes_valid_rows_and_reruns_add_nothing() -> None:
    """Run the demo phases against the real schema, then roll everything back."""
    from app.db.session import AsyncSessionLocal
    from app.scripts import seed_demo

    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        try:
            users = await seed_demo._seed_accounts(db, now)
            properties = await seed_demo._seed_properties(db, users, now)
            mine = select(func.count()).where(
                PropertySubmission.submitter_uuid == users["sub_admin"].id
            )
            await seed_demo._seed_property_submissions(db, users, properties, now)
            await db.flush()
            assert await db.scalar(mine) == 11

            await seed_demo._seed_property_submissions(db, users, properties, now)
            await db.flush()
            assert await db.scalar(mine) == 11
            assert (
                await db.scalar(
                    select(
                        func.count(func.distinct(PropertySubmission.approved_property_id))
                    ).where(
                        PropertySubmission.approved_property_id.in_(
                            [prop.id for prop in properties.values()]
                        )
                    )
                )
                == 3
            )
        finally:
            await db.rollback()
