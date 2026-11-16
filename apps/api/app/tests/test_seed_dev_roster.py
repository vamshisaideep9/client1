"""Development roster expansion (app.scripts.seed_dev_roster)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.property import Property
from app.models.referral import ReferralCode
from app.models.user import User, UserStatus
from app.scripts.seed_dev_roster import (
    LISTINGS,
    ROSTER,
    RosterSeedConflict,
    credentials_report,
    roster_uuid,
    seed_dev_roster,
)
from conftest import unique_email, unique_mobile


def test_roster_shape_is_two_per_role_and_line() -> None:
    counts: dict[tuple[str, str | None], int] = {}
    for account in ROSTER:
        counts[(account.role, account.business_line)] = (
            counts.get((account.role, account.business_line), 0) + 1
        )
    assert counts == {
        ("client", None): 2,
        ("agent", "loans"): 2,
        ("agent", "real_estate"): 2,
        ("telecaller", "loans"): 2,
        ("telecaller", "real_estate"): 2,
        ("employee", "loans"): 2,
        ("employee", "real_estate"): 2,
    }
    assert len({a.mobile for a in ROSTER}) == len(ROSTER)
    assert len({a.email for a in ROSTER}) == len(ROSTER)
    codes = [code for a in ROSTER for code in a.codes]
    assert len(set(codes)) == len(codes)
    assert all(
        a.rera_code for a in ROSTER if a.role == "agent" and a.business_line == "real_estate"
    )
    assert len(LISTINGS) == 10
    assert {listing.category for listing in LISTINGS} == {
        "apartments",
        "villas",
        "houses",
        "plots",
        "commercial",
    }


async def _ensure_primary_admin(db) -> None:
    existing = await db.scalar(
        select(StaffProfile).where(
            StaffProfile.is_primary_admin.is_(True),
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if existing is not None:
        return
    user = User(
        first_name="Primary",
        last_name="Admin",
        mobile=unique_mobile(),
        email=unique_email(),
        password_hash="unused",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.flush()
    db.add(
        StaffProfile(
            auth_user_uuid=user.id,
            role=StaffRole.ADMIN,
            scope=ProfileScope.PLATFORM,
            staff_code="AD-TEST0001",
            status=ProfileStatus.ACTIVE,
            is_primary_admin=True,
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_seed_dev_roster_creates_scoped_accounts_and_is_rerunnable() -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            await _ensure_primary_admin(db)
            results, listings = await seed_dev_roster(db)

            assert listings == len(LISTINGS)
            passwords = {account.key: password for account, password in results}
            assert all(passwords.values())
            assert len(set(passwords.values())) == len(ROSTER)

            for account in ROSTER:
                user = await db.scalar(select(User).where(User.mobile == account.mobile))
                assert user is not None and user.status == UserStatus.ACTIVE
                assert await verify_password(passwords[account.key], user.password_hash)
                if account.role == "client":
                    lines = set(
                        (
                            await db.scalars(
                                select(ClientProfile.business_line).where(
                                    ClientProfile.auth_user_uuid == user.id
                                )
                            )
                        ).all()
                    )
                    assert lines == {"loans", "real_estate"}
                    assert await db.get(ReferralCode, user.id) is not None
                elif account.role == "agent":
                    agent = await db.scalar(
                        select(AgentProfile).where(AgentProfile.auth_user_uuid == user.id)
                    )
                    assert agent.business_line == account.business_line
                    assert agent.status == ProfileStatus.ACTIVE
                else:
                    staff = await db.scalar(
                        select(StaffProfile).where(StaffProfile.auth_user_uuid == user.id)
                    )
                    assert staff.role == StaffRole(account.role)
                    assert staff.scope == ProfileScope.LINE
                    assert staff.business_line == account.business_line
                    assert staff.is_primary_admin is False

            for listing in LISTINGS:
                prop = await db.get(Property, roster_uuid(f"property:{listing.key}"))
                assert prop is not None and prop.active is True
                assert prop.business_line == "real_estate"

            again, listings_again = await seed_dev_roster(db)
            assert listings_again == 0
            assert all(password is None for _, password in again)
            assert "(existing account, unchanged)" in credentials_report(again)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_seed_dev_roster_refuses_a_foreign_account_on_a_roster_mobile() -> None:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            await _ensure_primary_admin(db)
            db.add(
                User(
                    first_name="Someone",
                    last_name="Else",
                    mobile=ROSTER[0].mobile,
                    email=unique_email(),
                    password_hash="unused",
                    status=UserStatus.ACTIVE,
                )
            )
            await db.flush()
            with pytest.raises(RosterSeedConflict, match="non-roster account"):
                await seed_dev_roster(db)
        finally:
            await db.rollback()
