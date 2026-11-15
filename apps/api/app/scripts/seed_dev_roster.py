"""Add extra role accounts and published listings to the development stack.

Run from the API container:

    uv run python -m app.scripts.seed_dev_roster

Adds, without touching any existing row:

* 2 Clients (enrolled in both business lines, each with a referral code);
* 2 Agents, 2 Telecallers and 2 Employees per business line;
* 10 published real-estate listings across every property category.

Each newly created account gets its own generated password, printed once in
the run output and never stored anywhere else. A rerun skips accounts and
listings that already exist (their passwords are left unchanged), and refuses
to continue if a roster mobile, email or profile code already belongs to a
different account.

Development-only: refuses to run unless ``ENV=development``. Inserts through
``AsyncSessionLocal`` as the database owner, like the other seeders.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_temp_password, hash_password, validate_password_policy
from app.db import base as _model_registry  # noqa: F401  # load all ORM models first
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.property import (
    ConstructionStatus,
    Furnishing,
    ListingIntent,
    Property,
    PropertyCategory,
    PropertySubtype,
    ReraApplicability,
    ReraVerificationStatus,
)
from app.models.user import User, UserStatus
from app.scripts.seed_helpers import dev_seed_email
from app.services import referrals

ROSTER_NAMESPACE = UUID("5a0c9e7d-2b41-4c8e-a6f3-91d7e0b4c2a8")


class RosterSeedConflict(RuntimeError):
    """A roster identity collides with a row this seeder does not own."""


def roster_uuid(key: str) -> UUID:
    return uuid5(ROSTER_NAMESPACE, f"v1:{key}")


@dataclass(frozen=True, slots=True)
class RosterAccount:
    key: str
    role: str  # client | agent | telecaller | employee
    business_line: str | None  # None for clients (enrolled in both lines)
    first_name: str
    last_name: str
    mobile: str
    codes: tuple[str, ...]  # one per profile created
    rera_code: str | None = None

    @property
    def email(self) -> str:
        return dev_seed_email(f"{self.first_name.lower()}.{self.last_name.lower()}.dev@example.com")

    @property
    def label(self) -> str:
        line = {"loans": "Loans", "real_estate": "Real Estate", None: "Loans + Real Estate"}
        return f"{self.role.title()} ({line[self.business_line]})"


ROSTER: tuple[RosterAccount, ...] = (
    RosterAccount(
        "client-2", "client", None, "Meera", "Joshi", "+919100000110", ("CL-LN0002", "CL-RE0002")
    ),
    RosterAccount(
        "client-3", "client", None, "Farhan", "Qureshi", "+919100000111", ("CL-LN0003", "CL-RE0003")
    ),
    RosterAccount(
        "agent-loans-2", "agent", "loans", "Suresh", "Babu", "+919100000112", ("AG-LN0002",)
    ),
    RosterAccount(
        "agent-loans-3", "agent", "loans", "Lakshmi", "Prasad", "+919100000113", ("AG-LN0003",)
    ),
    RosterAccount(
        "agent-re-2",
        "agent",
        "real_estate",
        "Naveen",
        "Goud",
        "+919100000114",
        ("AG-RE0002",),
        rera_code="RERA/DEV/AG/0002",
    ),
    RosterAccount(
        "agent-re-3",
        "agent",
        "real_estate",
        "Ananya",
        "Desai",
        "+919100000115",
        ("AG-RE0003",),
        rera_code="RERA/DEV/AG/0003",
    ),
    RosterAccount(
        "telecaller-loans-2",
        "telecaller",
        "loans",
        "Harini",
        "Varma",
        "+919100000116",
        ("TC-LN0002",),
    ),
    RosterAccount(
        "telecaller-loans-3",
        "telecaller",
        "loans",
        "Manoj",
        "Kumar",
        "+919100000117",
        ("TC-LN0003",),
    ),
    RosterAccount(
        "telecaller-re-2",
        "telecaller",
        "real_estate",
        "Swathi",
        "Reddy",
        "+919100000118",
        ("TC-RE0002",),
    ),
    RosterAccount(
        "telecaller-re-3",
        "telecaller",
        "real_estate",
        "Imran",
        "Shaikh",
        "+919100000119",
        ("TC-RE0003",),
    ),
    RosterAccount(
        "employee-loans-2", "employee", "loans", "Ravi", "Teja", "+919100000120", ("EM-LN0002",)
    ),
    RosterAccount(
        "employee-loans-3",
        "employee",
        "loans",
        "Bhavana",
        "Chowdary",
        "+919100000121",
        ("EM-LN0003",),
    ),
    RosterAccount(
        "employee-re-2",
        "employee",
        "real_estate",
        "Gopal",
        "Krishna",
        "+919100000122",
        ("EM-RE0002",),
    ),
    RosterAccount(
        "employee-re-3",
        "employee",
        "real_estate",
        "Nandini",
        "Pillai",
        "+919100000123",
        ("EM-RE0003",),
    ),
)


@dataclass(frozen=True, slots=True)
class RosterListing:
    key: str
    title: str
    type: str
    category: PropertyCategory
    subtype: PropertySubtype
    locality: str
    pincode: str
    price_display: str
    price_paise: int
    bhk: int
    area_sqft: int
    furnishing: Furnishing | None
    construction_status: ConstructionStatus
    amenities: tuple[str, ...]
    age_years: int
    image: str
    developer_name: str


LISTINGS: tuple[RosterListing, ...] = (
    RosterListing(
        "kohinoor-residency",
        "Kohinoor Residency",
        "Apartment",
        PropertyCategory.APARTMENTS,
        PropertySubtype.GATED_COMMUNITY_APARTMENT,
        "Narsingi",
        "500089",
        "₹1.12 Cr",
        1_12_00_000_00,
        3,
        1_780,
        Furnishing.SEMI,
        ConstructionStatus.READY,
        ("parking", "lift", "gym", "security", "power_backup"),
        2,
        "/illustrations/properties/apartment-1.svg",
        "Sreenivasa Homes",
    ),
    RosterListing(
        "brindavan-towers",
        "Brindavan Towers",
        "Apartment",
        PropertyCategory.APARTMENTS,
        PropertySubtype.STANDALONE_APARTMENT,
        "Ameerpet",
        "500016",
        "₹74 L",
        74_00_000_00,
        2,
        1_150,
        Furnishing.FURNISHED,
        ConstructionStatus.READY,
        ("parking", "lift", "security"),
        6,
        "/illustrations/properties/apartment-3.svg",
        "Vasundhara Infra",
    ),
    RosterListing(
        "cedar-grove-villas",
        "Cedar Grove Villas",
        "Villa",
        PropertyCategory.VILLAS,
        PropertySubtype.VILLA,
        "Tellapur",
        "502032",
        "₹2.65 Cr",
        2_65_00_000_00,
        4,
        3_600,
        Furnishing.SEMI,
        ConstructionStatus.UNDER_CONSTRUCTION,
        ("parking", "clubhouse", "swimming_pool", "garden", "security"),
        0,
        "/illustrations/properties/villa-3.svg",
        "Aadhya Constructions",
    ),
    RosterListing(
        "palm-springs-villa",
        "Palm Springs Villa",
        "Villa",
        PropertyCategory.VILLAS,
        PropertySubtype.VILLA,
        "Shamshabad",
        "501218",
        "₹1.95 Cr",
        1_95_00_000_00,
        4,
        3_050,
        Furnishing.UNFURNISHED,
        ConstructionStatus.READY,
        ("parking", "garden", "power_backup"),
        1,
        "/illustrations/properties/villa-1.svg",
        "Sreenivasa Homes",
    ),
    RosterListing(
        "jasmine-court-house",
        "Jasmine Court House",
        "House",
        PropertyCategory.HOUSES,
        PropertySubtype.INDIVIDUAL_HOUSE,
        "Kompally",
        "500100",
        "₹1.05 Cr",
        1_05_00_000_00,
        3,
        2_050,
        Furnishing.SEMI,
        ConstructionStatus.READY,
        ("parking", "security", "garden"),
        5,
        "/illustrations/properties/villa-2.svg",
        "Vasundhara Infra",
    ),
    RosterListing(
        "ashoka-duplex",
        "Ashoka Duplex Home",
        "House",
        PropertyCategory.HOUSES,
        PropertySubtype.INDIVIDUAL_HOUSE,
        "LB Nagar",
        "500074",
        "₹88 L",
        88_00_000_00,
        3,
        1_700,
        Furnishing.UNFURNISHED,
        ConstructionStatus.READY,
        ("parking", "power_backup"),
        3,
        "/illustrations/properties/villa-3.svg",
        "Aadhya Constructions",
    ),
    RosterListing(
        "silver-sands-plots",
        "Silver Sands Plots",
        "Plot",
        PropertyCategory.PLOTS,
        PropertySubtype.PLOT,
        "Adibatla",
        "501510",
        "₹42 L",
        42_00_000_00,
        0,
        2_000,
        None,
        ConstructionStatus.READY,
        ("security",),
        0,
        "/illustrations/properties/plot-1.svg",
        "Sreenivasa Homes",
    ),
    RosterListing(
        "mango-orchard-farmland",
        "Mango Orchard Farmland",
        "Farmland",
        PropertyCategory.PLOTS,
        PropertySubtype.FARMLAND,
        "Chevella",
        "501503",
        "₹65 L",
        65_00_000_00,
        0,
        21_780,
        None,
        ConstructionStatus.READY,
        (),
        0,
        "/illustrations/properties/plot-3.svg",
        "Aadhya Constructions",
    ),
    RosterListing(
        "cyber-gateway-offices",
        "Cyber Gateway Offices",
        "Office",
        PropertyCategory.COMMERCIAL,
        PropertySubtype.LOCKED_SPACE,
        "Madhapur",
        "500081",
        "₹3.40 Cr",
        3_40_00_000_00,
        0,
        4_100,
        Furnishing.FURNISHED,
        ConstructionStatus.READY,
        ("parking", "lift", "power_backup", "security"),
        3,
        "/illustrations/properties/commercial-2.svg",
        "Vasundhara Infra",
    ),
    RosterListing(
        "highway-retail-plaza",
        "Highway Retail Plaza",
        "Shop",
        PropertyCategory.COMMERCIAL,
        PropertySubtype.UNLOCKED_SPACE,
        "Kukatpally",
        "500072",
        "₹1.25 Cr",
        1_25_00_000_00,
        0,
        1_350,
        Furnishing.UNFURNISHED,
        ConstructionStatus.READY,
        ("parking", "security"),
        4,
        "/illustrations/properties/commercial-3.svg",
        "Sreenivasa Homes",
    ),
)


def _require_development() -> None:
    if settings.ENV != "development":
        raise SystemExit(
            f"seed_dev_roster is development-only; refusing to run with ENV={settings.ENV!r}."
        )


async def _primary_admin(db: AsyncSession) -> StaffProfile:
    admin = await db.scalar(
        select(StaffProfile).where(
            StaffProfile.is_primary_admin.is_(True),
            StaffProfile.status == ProfileStatus.ACTIVE,
        )
    )
    if admin is None:
        raise RosterSeedConflict("No active primary Admin; seed the Admin account first.")
    return admin


async def _assert_codes_free(db: AsyncSession, account: RosterAccount, user_id: UUID) -> None:
    for code in account.codes:
        for model, column in (
            (StaffProfile, StaffProfile.staff_code),
            (AgentProfile, AgentProfile.agent_code),
            (ClientProfile, ClientProfile.customer_code),
        ):
            owner = await db.scalar(select(model.auth_user_uuid).where(column == code))
            if owner is not None and owner != user_id:
                raise RosterSeedConflict(f"Profile code {code} belongs to another account.")


async def _ensure_user(
    db: AsyncSession, account: RosterAccount, now: datetime, created_by: UUID
) -> tuple[User, str | None]:
    user_id = roster_uuid(f"user:{account.key}")
    by_mobile = await db.scalar(select(User).where(User.mobile == account.mobile))
    by_email = await db.scalar(select(User).where(func.lower(User.email) == account.email.lower()))
    for existing, field_name in ((by_mobile, "mobile"), (by_email, "email")):
        if existing is not None and existing.id != user_id:
            raise RosterSeedConflict(
                f"Roster {field_name} for {account.key} belongs to a non-roster account."
            )
    if by_mobile is not None:
        return by_mobile, None

    password = generate_temp_password(account.mobile)
    validate_password_policy(password, account.mobile)
    user = User(
        id=user_id,
        first_name=account.first_name,
        last_name=account.last_name,
        mobile=account.mobile,
        email=account.email,
        location="Hyderabad",
        password_hash=await hash_password(password),
        status=UserStatus.ACTIVE,
        phone_verified_at=now,
        email_verified_at=now,
        created_by_auth_user_uuid=created_by,
    )
    db.add(user)
    await db.flush()
    return user, password


async def _ensure_profiles(
    db: AsyncSession, account: RosterAccount, user: User, admin: StaffProfile, now: datetime
) -> None:
    await _assert_codes_free(db, account, user.id)
    if account.role == "client":
        for line, code in zip(("loans", "real_estate"), account.codes, strict=True):
            profile_id = roster_uuid(f"client:{account.key}:{line}")
            if await db.get(ClientProfile, profile_id) is None:
                db.add(
                    ClientProfile(
                        id=profile_id,
                        auth_user_uuid=user.id,
                        business_line=line,
                        customer_code=code,
                        status=ProfileStatus.ACTIVE,
                    )
                )
        await db.flush()
        await referrals.issue_code_on_session(db, user.id, skip_eligibility=True)
        return

    if account.role == "agent":
        profile_id = roster_uuid(f"agent:{account.key}")
        if await db.get(AgentProfile, profile_id) is None:
            db.add(
                AgentProfile(
                    id=profile_id,
                    auth_user_uuid=user.id,
                    agent_code=account.codes[0],
                    business_line=account.business_line,
                    kyc_status="verified",
                    rera_code=account.rera_code,
                    status=ProfileStatus.ACTIVE,
                    approved_by_staff_profile_uuid=admin.id,
                    approved_at=now,
                )
            )
        return

    profile_id = roster_uuid(f"staff:{account.key}")
    if await db.get(StaffProfile, profile_id) is None:
        db.add(
            StaffProfile(
                id=profile_id,
                auth_user_uuid=user.id,
                role=StaffRole(account.role),
                scope=ProfileScope.LINE,
                business_line=account.business_line,
                staff_code=account.codes[0],
                status=ProfileStatus.ACTIVE,
                created_by_auth_user_uuid=admin.auth_user_uuid,
                is_primary_admin=False,
            )
        )


async def _seed_listings(db: AsyncSession, now: datetime) -> int:
    created = 0
    for index, listing in enumerate(LISTINGS):
        property_id = roster_uuid(f"property:{listing.key}")
        if await db.get(Property, property_id) is not None:
            continue
        meta = (
            f"{listing.bhk} bed · {listing.area_sqft:,} sqft"
            if listing.bhk
            else f"{listing.area_sqft:,} sqft"
        )
        db.add(
            Property(
                id=property_id,
                business_line="real_estate",
                active=True,
                listing_intent=ListingIntent.SALE,
                title=listing.title,
                type=listing.type,
                location=f"{listing.locality}, Hyderabad",
                developer_name=listing.developer_name,
                price_display=listing.price_display,
                meta=meta,
                image=listing.image,
                category=listing.category,
                property_subtype=listing.subtype,
                city="Hyderabad",
                locality=listing.locality,
                state="Telangana",
                pincode=listing.pincode,
                price_paise=listing.price_paise,
                bhk=listing.bhk,
                area_sqft=listing.area_sqft,
                furnishing=listing.furnishing,
                construction_status=listing.construction_status,
                amenities=list(listing.amenities),
                age_years=listing.age_years,
                rera_applicability=ReraApplicability.UNSURE,
                rera_verification_status=ReraVerificationStatus.NOT_REVIEWED,
                details={},
                created_at=now - timedelta(days=index),
            )
        )
        created += 1
    return created


async def seed_dev_roster(db: AsyncSession) -> tuple[list[tuple[RosterAccount, str | None]], int]:
    """Create missing roster rows inside the caller's transaction; never commits."""
    now = datetime.now(UTC)
    admin = await _primary_admin(db)
    results: list[tuple[RosterAccount, str | None]] = []
    for account in ROSTER:
        user, password = await _ensure_user(db, account, now, admin.auth_user_uuid)
        await _ensure_profiles(db, account, user, admin, now)
        results.append((account, password))
    await db.flush()
    listings = await _seed_listings(db, now)
    await db.flush()
    return results, listings


def credentials_report(results: list[tuple[RosterAccount, str | None]]) -> str:
    lines = ["Role | Name | Mobile | Password", "--- | --- | --- | ---"]
    for account, password in results:
        shown = password or "(existing account, unchanged)"
        lines.append(
            f"{account.label} | {account.first_name} {account.last_name} | "
            f"{account.mobile} | {shown}"
        )
    return "\n".join(lines)


async def _run() -> tuple[list[tuple[RosterAccount, str | None]], int]:
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        results, listings = await seed_dev_roster(db)
        await db.commit()
    return results, listings


def main() -> None:
    _require_development()
    results, listings = asyncio.run(_run())
    created = sum(1 for _, password in results if password)
    print(f"[seed_dev_roster] Accounts created: {created}; listings created: {listings}")
    print(credentials_report(results))


if __name__ == "__main__":
    main()
