"""Deterministic plan for the bulk development dataset (``seed_bulk``).

Pure data only -- no database, storage or network access -- so the whole plan
is unit tested: unique identities, full enum coverage, and listing facts that
pass the same ``SubmissionFacts`` validation real property submissions do.

Every value is synthetic. Mobiles live in the reserved ``+91 92000 xxxxx``
block (disjoint from ``seed_demo`` ``+91 90000 0xxxx`` and ``seed_dev_roster``
``+91 91000 001xx``); emails use ``example.com``; UUIDs are UUIDv5 in
``BULK_NAMESPACE``. The shared password is a published development fixture,
not a secret; the writer refuses to run unless ``ENV=development``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache
from uuid import UUID, uuid5

from app.db import base as _model_registry  # noqa: F401  # load all ORM models first
from app.models.lead import LeadStatus
from app.models.loan import LoanStatus
from app.models.profile import ProfileStatus
from app.models.property import (
    ConstructionStatus,
    Furnishing,
    ListingIntent,
    PropertyCategory,
    PropertySubtype,
    ReraApplicability,
)
from app.models.property_deal import PropertyDealStatus
from app.models.user import UserStatus
from app.scripts.demo_catalog import DEMO_PASSWORD

BULK_DATASET_VERSION = 1
BULK_PASSWORD = DEMO_PASSWORD
BULK_NAMESPACE = UUID("8f3b6c2e-4d1a-4e7b-9c5a-2b7e1d0f6a39")
MOBILE_PREFIX = "+9192000"


def bulk_uuid(key: str) -> UUID:
    return uuid5(BULK_NAMESPACE, f"v{BULK_DATASET_VERSION}:{key}")


def bulk_mobile(number: int) -> str:
    if not 0 < number < 100_000:
        raise ValueError("Bulk mobile suffix must be 1-99999.")
    return f"{MOBILE_PREFIX}{number:05d}"


# Mobile blocks inside +91 92000 xxxxx.
STAFF_MOBILE_BASE = 100  # admins, sub admins, telecallers, employees, agents
CLIENT_MOBILE_BASE = 10_000  # registered clients
PROSPECT_MOBILE_BASE = 50_000  # leads without an account
REFERRED_MOBILE_BASE = 60_000  # referred people who never registered
APPLICANT_MOBILE_BASE = 70_000  # agent applicants

FIRST_NAMES = (
    "Aarav", "Aditi", "Akhil", "Ananya", "Arjun", "Bhavana", "Chaitanya", "Deepika",
    "Dhruv", "Divya", "Gautam", "Harini", "Ishaan", "Jahnavi", "Karthik", "Kavya",
    "Lakshman", "Madhuri", "Manoj", "Meghana", "Nikhil", "Nandini", "Omkar", "Pallavi",
    "Pranav", "Pooja", "Rahul", "Rashmi", "Sai", "Sahithi", "Srinivas", "Swathi",
    "Tarun", "Tejaswini", "Uday", "Varsha", "Vikram", "Yamini", "Zubair", "Farah",
)  # fmt: skip
LAST_NAMES = (
    "Reddy", "Rao", "Sharma", "Naidu", "Varma", "Iyer", "Kulkarni", "Patel",
    "Chowdary", "Goud", "Menon", "Pillai", "Shetty", "Joshi", "Desai", "Kapoor",
    "Nair", "Bhat", "Mishra", "Khan", "Das", "Gupta", "Yadav", "Prasad",
)  # fmt: skip


def person_name(index: int) -> tuple[str, str]:
    return FIRST_NAMES[index % len(FIRST_NAMES)], LAST_NAMES[(index * 7 + 3) % len(LAST_NAMES)]


@dataclass(frozen=True, slots=True)
class BulkAccount:
    key: str
    role: str  # admin | sub_admin | telecaller | employee | agent | client
    first_name: str
    last_name: str
    mobile: str
    # Staff/agent: their single operational line (None for platform staff).
    # Clients: the lines they are enrolled in.
    business_line: str | None
    client_lines: tuple[str, ...] = ()
    code: str = ""
    user_status: UserStatus = UserStatus.ACTIVE
    profile_status: ProfileStatus = ProfileStatus.ACTIVE
    payout_grant: bool = False
    rera_code: str | None = None

    @property
    def email(self) -> str:
        return f"{self.first_name}.{self.last_name}.{self.key}@example.com".lower()

    @property
    def label(self) -> str:
        line = {"loans": "Loans", "real_estate": "Real Estate"}
        if self.role == "client":
            scope = " + ".join(line[value] for value in self.client_lines)
        else:
            scope = line.get(self.business_line or "", "Platform")
        return f"{self.role.replace('_', ' ').title()} ({scope})"


@dataclass(frozen=True, slots=True)
class BulkTeam:
    key: str
    name: str
    business_line: str
    member_role: str
    manager_key: str
    member_keys: tuple[str, ...]


def _staff(
    role: str, count: int, *, prefix: str, start: int, name_offset: int
) -> list[BulkAccount]:
    accounts: list[BulkAccount] = []
    loans_count = (count + 1) // 2
    for number in range(1, count + 1):
        first, last = person_name(name_offset + number)
        line = None
        if role in {"telecaller", "employee", "agent"}:
            line = "loans" if number <= loans_count else "real_estate"
        line_code = {"loans": "LN", "real_estate": "RE", None: ""}[line]
        accounts.append(
            BulkAccount(
                key=f"{prefix}-{number:02d}",
                role=role,
                first_name=first,
                last_name=last,
                mobile=bulk_mobile(start + number),
                business_line=line,
                code=f"{_CODE_PREFIX[role]}-{line_code}BK{number:03d}",
            )
        )
    return accounts


_CODE_PREFIX = {
    "admin": "AD",
    "sub_admin": "SA",
    "telecaller": "TC",
    "employee": "EM",
    "agent": "AG",
    "client": "CL",
}


def _with(account: BulkAccount, **changes: object) -> BulkAccount:
    values = {name: getattr(account, name) for name in account.__dataclass_fields__}
    values.update(changes)
    return BulkAccount(**values)  # type: ignore[arg-type]


@cache
def staff_accounts() -> tuple[BulkAccount, ...]:
    admins = _staff("admin", 2, prefix="admin", start=STAFF_MOBILE_BASE, name_offset=0)
    sub_admins = _staff(
        "sub_admin", 9, prefix="subadmin", start=STAFF_MOBILE_BASE + 10, name_offset=3
    )
    telecallers = _staff(
        "telecaller", 15, prefix="telecaller", start=STAFF_MOBILE_BASE + 30, name_offset=13
    )
    employees = _staff(
        "employee", 15, prefix="employee", start=STAFF_MOBILE_BASE + 50, name_offset=29
    )
    agents = _staff("agent", 15, prefix="agent", start=STAFF_MOBILE_BASE + 70, name_offset=45)

    # Sub Admins 06-07 may prepare payout requests (maker side).
    sub_admins = [
        _with(account, payout_grant=account.key in {"subadmin-06", "subadmin-07"})
        for account in sub_admins
    ]
    # One suspended Telecaller and one inactive Employee for account-state UIs.
    telecallers = [
        _with(account, profile_status=ProfileStatus.SUSPENDED)
        if account.key == "telecaller-08"
        else account
        for account in telecallers
    ]
    employees = [
        _with(account, profile_status=ProfileStatus.INACTIVE)
        if account.key == "employee-15"
        else account
        for account in employees
    ]
    agents = [
        _with(
            account,
            rera_code=(
                f"RERA/TS/BULK/AG/{account.key[-2:]}"
                if account.business_line == "real_estate"
                else None
            ),
            profile_status=(
                ProfileStatus.SUSPENDED if account.key == "agent-15" else ProfileStatus.ACTIVE
            ),
        )
        for account in agents
    ]
    return tuple([*admins, *sub_admins, *telecallers, *employees, *agents])


CLIENT_COUNT = 195
LOANS_ONLY = range(0, 85)
REAL_ESTATE_ONLY = range(85, 170)
BOTH_LINES = range(170, 195)


def _client_lines(index: int) -> tuple[str, ...]:
    if index in LOANS_ONLY:
        return ("loans",)
    if index in REAL_ESTATE_ONLY:
        return ("real_estate",)
    return ("loans", "real_estate")


@cache
def client_accounts() -> tuple[BulkAccount, ...]:
    accounts: list[BulkAccount] = []
    for index in range(CLIENT_COUNT):
        first, last = person_name(100 + index)
        user_status = UserStatus.ACTIVE
        if index % 40 == 7:
            user_status = UserStatus.PENDING_PASSWORD_RESET
        elif index % 45 == 11:
            user_status = UserStatus.SUSPENDED
        accounts.append(
            BulkAccount(
                key=f"client-{index + 1:03d}",
                role="client",
                first_name=first,
                last_name=last,
                mobile=bulk_mobile(CLIENT_MOBILE_BASE + index + 1),
                business_line=None,
                client_lines=_client_lines(index),
                code=f"BK{index + 1:03d}",
                user_status=user_status,
            )
        )
    return tuple(accounts)


def all_accounts() -> tuple[BulkAccount, ...]:
    return (*staff_accounts(), *client_accounts())


def account(key: str) -> BulkAccount:
    for candidate in all_accounts():
        if candidate.key == key:
            return candidate
    raise KeyError(key)


def accounts_by_role(role: str, line: str | None = None) -> tuple[BulkAccount, ...]:
    return tuple(
        candidate
        for candidate in staff_accounts()
        if candidate.role == role and (line is None or candidate.business_line == line)
    )


def _keys(prefix: str, numbers: range | tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}-{number:02d}" for number in numbers)


TEAMS: tuple[BulkTeam, ...] = (
    BulkTeam(
        "loans-callers-a",
        "Bulk Loans callers A",
        "loans",
        "telecaller",
        "subadmin-01",
        _keys("telecaller", range(1, 5)),
    ),
    BulkTeam(
        "loans-callers-b",
        "Bulk Loans callers B",
        "loans",
        "telecaller",
        "subadmin-02",
        _keys("telecaller", (5, 6, 8)),
    ),
    BulkTeam(
        "re-callers",
        "Bulk Real Estate callers",
        "real_estate",
        "telecaller",
        "subadmin-03",
        _keys("telecaller", range(9, 15)),
    ),
    BulkTeam(
        "loans-field",
        "Bulk Loans field team",
        "loans",
        "employee",
        "subadmin-04",
        _keys("employee", range(1, 8)),
    ),
    BulkTeam(
        "re-field",
        "Bulk Real Estate field team",
        "real_estate",
        "employee",
        "subadmin-05",
        _keys("employee", range(9, 16)),
    ),
)


# ---------------------------------------------------------------------------
# Client journeys
# ---------------------------------------------------------------------------

# Active (non-terminal) loan journeys; a client profile may hold one at a time.
ACTIVE_LOAN_STATUSES: tuple[LoanStatus, ...] = tuple(
    status for status in LoanStatus if status not in {LoanStatus.CLOSED, LoanStatus.REJECTED}
)
LEAD_ONLY_STATUSES = (
    LeadStatus.NEW,
    LeadStatus.ASSIGNED,
    LeadStatus.WORKING,
    LeadStatus.RELEASED,
    LeadStatus.CLOSED,
)
# Profile-level states for account-state UIs (applied to a few profiles).
PROFILE_STATE_CYCLE = (
    ProfileStatus.PENDING,
    ProfileStatus.SUSPENDED,
    ProfileStatus.INACTIVE,
)
EMPTY_PROFILES_PER_LINE = 5


@dataclass(frozen=True, slots=True)
class ClientJourney:
    """What one client profile (one person on one line) has done."""

    account_key: str
    line: str
    ordinal: int  # 0-based position among this line's profiles
    profile_status: ProfileStatus
    lead_status: LeadStatus | None  # None = no activity at all (empty state)
    agent_key: str | None
    telecaller_key: str | None
    current_loan_status: LoanStatus | None = None
    closed_loan: bool = False
    rejected_loan: bool = False
    loan_product_index: int = 0
    bookmarks: int = 0
    enquiry: bool = False
    site_visit: bool = False
    deal_status: PropertyDealStatus | None = None
    card_enquiry: bool = False

    @property
    def key(self) -> str:
        return f"{self.account_key}:{self.line}"


def _line_profiles(line: str) -> list[BulkAccount]:
    return [client for client in client_accounts() if line in client.client_lines]


def _active_line_staff(role: str, line: str) -> list[BulkAccount]:
    return [
        candidate
        for candidate in accounts_by_role(role, line)
        if candidate.profile_status == ProfileStatus.ACTIVE
    ]


@cache
def client_journeys() -> tuple[ClientJourney, ...]:
    journeys: list[ClientJourney] = []
    for line in ("loans", "real_estate"):
        telecallers = _active_line_staff("telecaller", line)
        agents = _active_line_staff("agent", line)
        profiles = _line_profiles(line)
        for ordinal, client in enumerate(profiles):
            dual = len(client.client_lines) == 2
            profile_status = ProfileStatus.ACTIVE
            if ordinal % 23 == 13:
                profile_status = PROFILE_STATE_CYCLE[(ordinal // 23) % len(PROFILE_STATE_CYCLE)]
            if ordinal >= len(profiles) - EMPTY_PROFILES_PER_LINE:
                journeys.append(
                    ClientJourney(client.key, line, ordinal, profile_status, None, None, None)
                )
                continue
            # A mobile may hold only one live Agent-protected lead across lines,
            # so a dual-line client is only Agent-introduced on Loans.
            agent_key = (
                agents[ordinal % len(agents)].key
                if ordinal % 3 == 0 and (not dual or line == "loans")
                else None
            )
            if line == "loans":
                has_application = ordinal % 5 != 4
                current = (
                    ACTIVE_LOAN_STATUSES[ordinal % len(ACTIVE_LOAN_STATUSES)]
                    if has_application
                    else None
                )
                if has_application:
                    lead_status = (
                        LeadStatus.WORKING
                        if current in {LoanStatus.NEW, LoanStatus.ASSIGNED, LoanStatus.CONTACTED}
                        else LeadStatus.CONVERTED
                    )
                else:
                    lead_status = LEAD_ONLY_STATUSES[(ordinal // 5) % len(LEAD_ONLY_STATUSES)]
                journeys.append(
                    ClientJourney(
                        client.key,
                        line,
                        ordinal,
                        profile_status,
                        lead_status,
                        agent_key,
                        None
                        if lead_status == LeadStatus.NEW
                        else telecallers[ordinal % len(telecallers)].key,
                        current_loan_status=current,
                        closed_loan=ordinal % 3 == 0,
                        rejected_loan=ordinal % 4 == 1,
                        loan_product_index=ordinal,
                        card_enquiry=ordinal % 9 == 2,
                    )
                )
            else:
                deal_status = (
                    tuple(PropertyDealStatus)[ordinal % len(PropertyDealStatus)]
                    if ordinal % 4 != 3
                    else None
                )
                if deal_status is not None:
                    lead_status = (
                        LeadStatus.CLOSED
                        if deal_status in {PropertyDealStatus.CLOSED, PropertyDealStatus.REJECTED}
                        else LeadStatus.CONVERTED
                    )
                else:
                    lead_status = LEAD_ONLY_STATUSES[(ordinal // 4) % len(LEAD_ONLY_STATUSES)]
                journeys.append(
                    ClientJourney(
                        client.key,
                        line,
                        ordinal,
                        profile_status,
                        lead_status,
                        agent_key,
                        None
                        if lead_status == LeadStatus.NEW
                        else telecallers[ordinal % len(telecallers)].key,
                        bookmarks=2 if ordinal % 2 == 0 else 0,
                        enquiry=ordinal % 3 == 0,
                        site_visit=ordinal % 2 == 1 or deal_status is not None,
                        deal_status=deal_status,
                    )
                )
    return tuple(journeys)


PROSPECTS_PER_LINE = 40


@dataclass(frozen=True, slots=True)
class Prospect:
    """A lead with no registered account (Telecaller/Agent pipelines)."""

    key: str
    line: str
    name: str
    mobile: str
    status: LeadStatus
    agent_key: str | None
    telecaller_key: str | None
    agent_expired: bool = False


@cache
def prospects() -> tuple[Prospect, ...]:
    rows: list[Prospect] = []
    for line_index, line in enumerate(("loans", "real_estate")):
        telecallers = _active_line_staff("telecaller", line)
        agents = _active_line_staff("agent", line)
        for number in range(PROSPECTS_PER_LINE):
            status = tuple(LeadStatus)[number % len(LeadStatus)]
            first, last = person_name(400 + line_index * 50 + number)
            agent_key = agents[number % len(agents)].key if number % 4 == 1 else None
            rows.append(
                Prospect(
                    key=f"prospect-{line}-{number + 1:02d}",
                    line=line,
                    name=f"{first} {last}",
                    mobile=bulk_mobile(PROSPECT_MOBILE_BASE + line_index * 1000 + number + 1),
                    status=status,
                    agent_key=agent_key,
                    telecaller_key=None
                    if status in {LeadStatus.NEW, LeadStatus.RELEASED}
                    else telecallers[number % len(telecallers)].key,
                    agent_expired=agent_key is not None and number % 8 == 1,
                )
            )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Real-estate catalogue
# ---------------------------------------------------------------------------

LOCALITIES: tuple[tuple[str, str], ...] = (
    ("Gachibowli", "500032"), ("Kondapur", "500084"), ("Kokapet", "500075"),
    ("Madhapur", "500081"), ("Kukatpally", "500072"), ("Miyapur", "500049"),
    ("Banjara Hills", "500034"), ("Jubilee Hills", "500033"), ("Manikonda", "500089"),
    ("Narsingi", "500089"), ("Tellapur", "502032"), ("Kompally", "500014"),
    ("Uppal", "500039"), ("LB Nagar", "500074"), ("Shamshabad", "501218"),
    ("Mokila", "501203"), ("Shankarpally", "501203"), ("Bachupally", "500090"),
)  # fmt: skip

LISTING_COUNT = 110
SUBMISSION_COUNT = 24
SUBTYPES: tuple[PropertySubtype, ...] = tuple(PropertySubtype)
RENTABLE = {
    PropertySubtype.INDIVIDUAL_HOUSE,
    PropertySubtype.STANDALONE_APARTMENT,
    PropertySubtype.GATED_COMMUNITY_APARTMENT,
    PropertySubtype.VILLA,
    PropertySubtype.LOCKED_SPACE,
    PropertySubtype.UNLOCKED_SPACE,
}
_TYPE_LABEL = {
    PropertySubtype.INDIVIDUAL_HOUSE: "House",
    PropertySubtype.STANDALONE_APARTMENT: "Apartment",
    PropertySubtype.GATED_COMMUNITY_APARTMENT: "Apartment",
    PropertySubtype.VILLA: "Villa",
    PropertySubtype.LOCKED_SPACE: "Office",
    PropertySubtype.UNLOCKED_SPACE: "Retail",
    PropertySubtype.PLOT: "Plot",
    PropertySubtype.FARMLAND: "Farmland",
    PropertySubtype.AGRILAND: "Agri land",
}
_IMAGE_STEM = {
    PropertyCategory.HOUSES: "villa",
    PropertyCategory.APARTMENTS: "apartment",
    PropertyCategory.VILLAS: "villa",
    PropertyCategory.COMMERCIAL: "commercial",
    PropertyCategory.PLOTS: "plot",
}
_PROJECT_PREFIX = (
    "Aurora", "Banyan", "Cedar", "Deccan", "Emerald", "Falcon", "Golden", "Harbor",
    "Indigo", "Jasmine", "Kestrel", "Lotus", "Meadow", "Nimbus", "Orchid", "Pinnacle",
)  # fmt: skip
_AMENITIES = (
    "Parking", "Security", "Power Backup", "Lift", "Clubhouse", "Gym",
    "Swimming Pool", "Children's Play Area", "Rainwater Harvesting", "CCTV",
)  # fmt: skip
_BHK_CONFIG = {1: "1_bhk", 2: "2_bhk", 3: "3_bhk", 4: "4_bhk", 5: "5_plus_bhk"}
_RERA_CYCLE = (
    ReraApplicability.APPLICABLE,
    ReraApplicability.APPLICABLE,
    ReraApplicability.EXEMPTION_CLAIMED,
    ReraApplicability.UNSURE,
)


def _price(subtype: PropertySubtype, intent: ListingIntent, index: int) -> int:
    """Price in paise: monthly rent for rentals, ticket size for sales."""
    if intent == ListingIntent.RENT:
        base_rupees = {
            PropertySubtype.LOCKED_SPACE: 85_000,
            PropertySubtype.UNLOCKED_SPACE: 120_000,
            PropertySubtype.VILLA: 95_000,
            PropertySubtype.INDIVIDUAL_HOUSE: 45_000,
        }.get(subtype, 28_000)
        return (base_rupees + (index % 7) * 2_500) * 100
    base_lakhs = {
        PropertySubtype.INDIVIDUAL_HOUSE: 140,
        PropertySubtype.STANDALONE_APARTMENT: 72,
        PropertySubtype.GATED_COMMUNITY_APARTMENT: 115,
        PropertySubtype.VILLA: 260,
        PropertySubtype.LOCKED_SPACE: 180,
        PropertySubtype.UNLOCKED_SPACE: 210,
        PropertySubtype.PLOT: 58,
        PropertySubtype.FARMLAND: 95,
        PropertySubtype.AGRILAND: 45,
    }[subtype]
    return (base_lakhs + (index % 11) * 6) * 100_000 * 100


def _about(subject: str, locality: str, words: int = 40) -> str:
    sentence = (
        f"Synthetic test listing for {subject} in {locality}. It exists only for "
        "development testing and does not describe a real property. Nearby schools, "
        "markets and transport are illustrative. "
    )
    text = sentence * (1 + words // len(sentence.split()))
    return " ".join(text.split()[:words])


def listing_facts(index: int) -> dict[str, object]:
    """Return ``SubmissionFacts``-shaped data for one synthetic listing."""
    subtype = SUBTYPES[index % len(SUBTYPES)]
    category = {
        PropertySubtype.INDIVIDUAL_HOUSE: PropertyCategory.HOUSES,
        PropertySubtype.STANDALONE_APARTMENT: PropertyCategory.APARTMENTS,
        PropertySubtype.GATED_COMMUNITY_APARTMENT: PropertyCategory.APARTMENTS,
        PropertySubtype.VILLA: PropertyCategory.VILLAS,
        PropertySubtype.LOCKED_SPACE: PropertyCategory.COMMERCIAL,
        PropertySubtype.UNLOCKED_SPACE: PropertyCategory.COMMERCIAL,
    }.get(subtype, PropertyCategory.PLOTS)
    intent = (
        ListingIntent.RENT if subtype in RENTABLE and (index // 9) % 3 == 1 else ListingIntent.SALE
    )
    locality, pincode = LOCALITIES[(index * 5) % len(LOCALITIES)]
    suffix = ("Heights", "Greens", "Enclave", "Square")[index % 4]
    project = f"{_PROJECT_PREFIX[index % len(_PROJECT_PREFIX)]} {suffix}"
    sale_type = ("new_sale", "resale")[index % 2] if intent == ListingIntent.SALE else None
    bhk = 0
    area_sqft = 0
    furnishing: Furnishing | None = None
    construction: ConstructionStatus | None = None
    details: dict[str, object]
    title_noun = _TYPE_LABEL[subtype]

    if subtype in {
        PropertySubtype.STANDALONE_APARTMENT,
        PropertySubtype.GATED_COMMUNITY_APARTMENT,
        PropertySubtype.VILLA,
    }:
        bhk = 4 + index % 2 if subtype == PropertySubtype.VILLA else 1 + index % 4
        area_sqft = 650 + bhk * 450 + (index % 5) * 40
        furnishing = tuple(Furnishing)[index % 3]
        construction = (
            ConstructionStatus.UNDER_CONSTRUCTION if index % 3 == 2 else ConstructionStatus.READY
        )
        configurations = [_BHK_CONFIG[bhk]]
        if index % 4 == 0:
            configurations.append("2_5_bhk" if bhk != 3 else "3_5_bhk")
        details = {
            "kind": "project_residence",
            "project_name": project,
            "project_area_acres": round(2.5 + index % 9 * 1.5, 1),
            "number_of_towers": 1 + index % 6,
            "total_units": 80 + index * 7,
            "configurations": configurations,
            "unit_or_plot_area_sqft": area_sqft,
            "unit_or_plot_area_max_sqft": area_sqft + 250 if index % 2 else None,
            "uds_area_from": 30 + index % 20 if index % 3 == 0 else None,
            "uds_area_unit": "sqyd" if index % 3 == 0 else None,
            "price_per_sqft_paise": 6_500_00 + (index % 9) * 250_00,
            "sale_type": sale_type,
            "expected_handover_date": (
                date(2028, 1 + index % 12, 1).isoformat()
                if construction == ConstructionStatus.UNDER_CONSTRUCTION
                else None
            ),
            "plot_facing": ("east", "west", "north", "south")[index % 4],
            "entrance_facing": ("north", "east", "south", "west")[index % 4],
            "local_approval": {"authority": "HMDA", "reference_number": f"BULK/{index:04d}"}
            if index % 2 == 0
            else None,
            "amenities_description": _about("the amenities", locality, 25),
            "about_project": _about(f"{project}", locality, 60),
        }
        title_noun = f"{bhk} BHK {title_noun}"
    elif subtype == PropertySubtype.INDIVIDUAL_HOUSE:
        bhk = 2 + index % 3
        area_sqft = 1400 + (index % 6) * 220
        details = {
            "kind": "individual_property",
            "property_use": ("residential", "residential_commercial")[index % 2],
            "total_land_area": 150 + (index % 5) * 30,
            "land_area_unit": "sqyd",
            "built_up_area_sqft": area_sqft,
            "number_of_floors": 1 + index % 3,
            "facing": ("east", "north", "west", "south")[index % 4],
            "monthly_rental_income_paise": 25_000_00 if index % 2 else None,
            "ongoing_loan_status": ("no", "yes", "unknown")[index % 3],
            "about_property": _about("an independent house", locality, 50),
            "other_information": "Synthetic record for testing only." if index % 2 else None,
        }
        title_noun = f"{bhk} BHK Independent House"
    elif subtype in {PropertySubtype.LOCKED_SPACE, PropertySubtype.UNLOCKED_SPACE}:
        area_sqft = 900 + (index % 8) * 300
        furnishing = tuple(Furnishing)[(index + 1) % 3]
        construction = (
            ConstructionStatus.UNDER_CONSTRUCTION if index % 4 == 1 else ConstructionStatus.READY
        )
        details = {
            "kind": "commercial_property",
            "ownership_type": ("individual", "entity")[index % 2],
            "total_area_sqft": area_sqft * 12,
            "unit_area_sqft": area_sqft,
            "facing": ("north", "east", "west", "south")[index % 4],
            "sale_type": sale_type,
            "rental_income_start": ("immediate", "from_handover", "not_applicable")[index % 3],
            "monthly_rental_income_paise": 60_000_00 if index % 3 == 0 else None,
            "local_approval": {"authority": "GHMC"} if index % 2 else None,
            "amenities_description": _about("the commercial amenities", locality, 20),
            "about_property": _about("a commercial space", locality, 45),
        }
    elif subtype == PropertySubtype.PLOT:
        plot_sqyd = 150 + (index % 7) * 50
        area_sqft = plot_sqyd * 9
        details = {
            "kind": "plot",
            "project_name": f"{project} Layout",
            "local_approval": {"authority": "DTCP", "reference_number": f"LP-BULK-{index:03d}"},
            "total_project_area_acres": 10 + index % 30,
            "plot_size_sqyd": plot_sqyd,
            "total_plots": 120 + index % 200,
            "facing": ("east", "north", "west", "south")[index % 4],
            "price_per_sqyd_paise": 35_000_00 + (index % 5) * 2_000_00,
            "sale_type": sale_type,
            "project_status": ("completed", "under_development")[index % 2],
            "about_project": _about("a plotted layout", locality, 45),
        }
        title_noun = f"{plot_sqyd} sq yd Plot"
    else:
        details = {
            "kind": "agricultural_land",
            "land_area": 2 + index % 15,
            "land_area_unit": ("acres", "guntas")[index % 2],
            "title_details": "Synthetic title summary for development testing.",
            "facilities": ["Borewell", "Road access"] if index % 2 else ["Fencing"],
            "ongoing_loan_status": ("no", "unknown", "yes")[index % 3],
            "land_type": ("Red soil", "Black soil", "Mixed soil")[index % 3],
            "survey_number": f"SY-{100 + index}/BULK",
            "rythu_bandhu_status": ("yes", "no", "unknown")[index % 3],
            "registration_district": "Rangareddy",
            "sub_registrar_office": "Chevella",
        }

    rera = _RERA_CYCLE[index % len(_RERA_CYCLE)]
    facts: dict[str, object] = {
        "title": f"{title_noun} in {locality}"[:200],
        "type": _TYPE_LABEL[subtype],
        "location": f"{locality}, Hyderabad",
        "developer_name": f"{project} Developers" if index % 3 != 2 else None,
        "meta": (
            f"{bhk} bed · {area_sqft:,} sqft"
            if bhk
            else (f"{area_sqft:,} sqft" if area_sqft else None)
        ),
        "category": category,
        "property_subtype": subtype,
        "city": "Hyderabad",
        "locality": locality,
        "state": "Telangana",
        "pincode": pincode,
        "listing_intent": intent,
        "price_paise": _price(subtype, intent, index),
        "security_deposit_paise": _price(subtype, intent, index) * 3
        if intent == ListingIntent.RENT
        else None,
        "minimum_lease_months": 11 if intent == ListingIntent.RENT else None,
        "available_from": date(2026, 12, 1 + index % 28).isoformat()
        if intent == ListingIntent.RENT
        else None,
        "bhk": bhk,
        "area_sqft": area_sqft,
        "furnishing": furnishing,
        "construction_status": construction,
        "amenities": list(_AMENITIES[index % 4 : index % 4 + 3 + index % 4])
        if category != PropertyCategory.PLOTS or subtype == PropertySubtype.PLOT
        else [],
        "age_years": 0
        if construction == ConstructionStatus.UNDER_CONSTRUCTION
        else (index % 12 if bhk else 0),
        "rera_applicability": rera,
        "rera_number": f"P0240{index:05d}" if rera == ReraApplicability.APPLICABLE else None,
        "structured_details": {key: value for key, value in details.items() if value is not None},
    }
    return facts


def listing_image(category: PropertyCategory, index: int) -> str:
    return f"/illustrations/properties/{_IMAGE_STEM[category]}-{1 + index % 3}.svg"


def photo_count(index: int) -> int:
    """Gallery photos per published listing: 3-6."""
    return 3 + index % 4


def has_panorama(index: int) -> bool:
    return index % 3 == 0


@dataclass(frozen=True, slots=True)
class SubmissionPlan:
    key: str
    index: int  # listing_facts index (offset past the catalogue)
    submitter_key: str
    status: str  # pending | approved | rejected
    rera_status: str  # not_reviewed | verified | mismatch | exemption_verified
    approved_listing: int | None = None  # bulk listing ordinal it produced


@cache
def submission_plans() -> tuple[SubmissionPlan, ...]:
    submitters = [
        *(a.key for a in accounts_by_role("agent", "real_estate")),
        "subadmin-08",
        "subadmin-09",
    ]
    plans: list[SubmissionPlan] = []
    for number in range(SUBMISSION_COUNT):
        status = ("pending", "pending", "rejected", "approved")[number % 4]
        if status == "pending":
            rera_status = ("not_reviewed", "mismatch", "verified")[number % 3]
        elif status == "approved":
            rera_status = "verified"
        else:
            rera_status = "not_reviewed"
        # An approved submission is the origin of a catalogue listing, so it
        # carries that listing's facts. Approval needs a cleared RERA review,
        # so it points at a listing whose applicability is "applicable".
        approved_listing = number - 3 if status == "approved" else None
        plans.append(
            SubmissionPlan(
                key=f"submission-{number + 1:02d}",
                index=approved_listing if approved_listing is not None else LISTING_COUNT + number,
                submitter_key=submitters[number % len(submitters)],
                status=status,
                rera_status=rera_status,
                approved_listing=approved_listing,
            )
        )
    return tuple(plans)


# ---------------------------------------------------------------------------
# Supporting rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentApplicationPlan:
    key: str
    first_name: str
    last_name: str
    mobile: str
    line: str
    status: str  # pending | rejected
    rera_code: str | None = None


@cache
def agent_application_plans() -> tuple[AgentApplicationPlan, ...]:
    plans = []
    for number in range(8):
        first, last = person_name(600 + number)
        line = ("loans", "real_estate")[number % 2]
        plans.append(
            AgentApplicationPlan(
                key=f"agent-application-{number + 1:02d}",
                first_name=first,
                last_name=last,
                mobile=bulk_mobile(APPLICANT_MOBILE_BASE + number + 1),
                line=line,
                status="rejected" if number % 3 == 2 else "pending",
                rera_code=f"RERA/TS/BULK/APP/{number + 1:02d}" if line == "real_estate" else None,
            )
        )
    return tuple(plans)


def credentials_table() -> str:
    """Staff roster plus a sample of clients; every account shares one password."""
    lines = [
        f"All bulk accounts use password: {BULK_PASSWORD}",
        "",
        "| Key | Role | Mobile | Notes |",
        "| --- | --- | --- | --- |",
    ]
    managers = {team.manager_key: team.name for team in TEAMS}
    for candidate in staff_accounts():
        notes = []
        if candidate.key in managers:
            notes.append(f"manages {managers[candidate.key]}")
        if candidate.payout_grant:
            notes.append("payout requests")
        if candidate.profile_status != ProfileStatus.ACTIVE:
            notes.append(candidate.profile_status.value)
        lines.append(
            f"| {candidate.key} | {candidate.label} | `{candidate.mobile}` | {', '.join(notes)} |"
        )
    lines.append(
        f"| client-001 ... client-{CLIENT_COUNT:03d} | Clients | "
        f"`{client_accounts()[0].mobile}` ... `{client_accounts()[-1].mobile}` | "
        "001-085 Loans, 086-170 Real Estate, 171-195 both lines |"
    )
    return "\n".join(lines)
