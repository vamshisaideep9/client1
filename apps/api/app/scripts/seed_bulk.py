"""Load the large, scenario-complete development dataset planned in ``bulk_catalog``.

Run from the API container:

    uv run python -m app.scripts.seed_bulk --verify

Adds 251 accounts (2 Admins, 9 Sub Admins of which 5 manage Telecaller/Employee
teams, 15 Telecallers, 15 Employees, 15 Agents and 195 Clients enrolled in
Loans, Real Estate or both), 110 published listings across every property
subtype, and leads, loans, deals, visits, tasks, payouts, referrals, tickets,
notifications and synthetic media in every workflow state.

Development-only: refuses to run unless ``ENV=development``. Writes as the
database owner (``AsyncSessionLocal``) like the other seeders. Every row has a
deterministic UUIDv5 id and is inserted only when missing, so reruns are safe
and resume a partial run. It never deletes or reassigns unrelated rows, stops
on any identity collision, calls no email/SMS/push/payment provider, and stores
no real KYC material. All accounts share the published development password.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db import base as _model_registry  # noqa: F401  # load all ORM models first
from app.models.audit_log import AuditAction, AuditLog
from app.models.bookmark import Bookmark
from app.models.commission import Commission, CommissionStatus
from app.models.enquiry import Enquiry, EnquiryStatus
from app.models.fee_cashback import FeeCashback, FeeCashbackStatus
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.lead_activity import CallDisposition, InterestLevel, LeadActivity
from app.models.loan import (
    FeeOutcome,
    FinancialServiceEnquiry,
    LoanApplication,
    LoanStatus,
    LoanTxnHistory,
    LoanType,
)
from app.models.notification import Notification, NotificationType
from app.models.payout import (
    Payout,
    PayoutDestination,
    PayoutProvider,
    PayoutStatus,
    PayoutType,
)
from app.models.profile import (
    AgentApplication,
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffFeatureGrant,
    StaffProfile,
    StaffRole,
)
from app.models.profile import SubmissionStatus as AgentSubmissionStatus
from app.models.property import (
    Property,
    ReraApplicability,
    ReraVerificationStatus,
)
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.property_submission import PropertySubmission, SubmissionStatus
from app.models.referral import Referral, ReferralStatus
from app.models.referral_bonus_config import ReferralBonusConfig
from app.models.site_visit import SiteVisit, SiteVisitStatus, SiteVisitTimeSlot
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.support_ticket import SupportCategory, SupportStatus, SupportTicket
from app.models.task import BgCheckOutcome, Task, TaskStatus, TaskType
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User, UserStatus
from app.models.vehicle_arrangement import VehicleArrangement, VehicleArrangementStatus
from app.schemas.financial_products import ProductFormDefinition, validate_form_answers
from app.schemas.property_submissions import SubmissionFacts
from app.scripts import bulk_catalog as catalog
from app.scripts.bulk_catalog import BulkAccount, ClientJourney, bulk_uuid
from app.scripts.seed_helpers import add_once, dev_seed_email, put_once, require_development

SCRIPT = "seed_bulk"


class BulkSeedConflict(RuntimeError):
    """A deterministic identity collides with a row this seeder does not own."""


def _days_ago(now: datetime, ordinal: int, *, spread: int = 330, floor: int = 3) -> datetime:
    """Spread creation times across roughly the last year for reporting views."""
    return now - timedelta(days=floor + (ordinal * 37) % spread, hours=ordinal % 9)


def _fingerprint(key: str) -> str:
    return hashlib.sha256(f"seed_bulk:{key}".encode()).hexdigest()


@dataclass
class Ctx:
    now: datetime
    users: dict[str, User] = field(default_factory=dict)
    staff: dict[str, StaffProfile] = field(default_factory=dict)
    agents: dict[str, AgentProfile] = field(default_factory=dict)
    clients: dict[str, ClientProfile] = field(default_factory=dict)  # journey.key
    properties: list[Property] = field(default_factory=list)
    leads: dict[str, Lead] = field(default_factory=dict)
    current_loans: dict[str, LoanApplication] = field(default_factory=dict)
    closed_loans: dict[str, LoanApplication] = field(default_factory=dict)
    deals: dict[str, PropertyDeal] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)

    def user(self, key: str) -> User:
        return self.users[key]

    def staff_of(self, key: str | None) -> StaffProfile | None:
        return self.staff.get(key) if key else None


# ---------------------------------------------------------------------------
# Accounts, profiles and teams
# ---------------------------------------------------------------------------


async def _seed_users(db: AsyncSession, ctx: Ctx) -> None:
    password_hash = await hash_password(catalog.BULK_PASSWORD)
    for account in catalog.all_accounts():
        user_id = bulk_uuid(f"user:{account.key}")
        email = dev_seed_email(account.email)
        by_mobile = await db.scalar(select(User).where(User.mobile == account.mobile))
        by_email = await db.scalar(select(User).where(User.email == email))
        for existing, kind in ((by_mobile, "mobile"), (by_email, "email")):
            if existing is not None and existing.id != user_id:
                raise BulkSeedConflict(f"Bulk {kind} for {account.key} belongs to another account.")
        user = await db.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                first_name=account.first_name,
                last_name=account.last_name,
                mobile=account.mobile,
                email=email,
                gender=("male", "female", "prefer_not_to_say")[len(account.key) % 3],
                occupation=f"Synthetic {account.label}",
                location="Hyderabad",
                password_hash=password_hash,
                status=account.user_status,
                phone_verified_at=ctx.now,
                email_verified_at=ctx.now,
            )
            db.add(user)
        elif user.mobile != account.mobile:
            raise BulkSeedConflict(f"UUID for {account.key} is owned by another mobile.")
        else:
            # Reruns restore the published password and planned state.
            user.password_hash = password_hash
            user.status = account.user_status
        ctx.users[account.key] = user
    await db.flush()


async def _assert_code_free(
    db: AsyncSession, model: Any, column: Any, code: str, owner: UUID
) -> None:
    row = await db.scalar(select(model).where(column == code))
    if row is not None and row.id != owner:
        raise BulkSeedConflict(f"Profile code {code} belongs to a non-bulk profile.")


async def _seed_profiles(db: AsyncSession, ctx: Ctx) -> None:
    for account in catalog.staff_accounts():
        if account.role == "agent":
            continue
        profile_id = bulk_uuid(f"staff:{account.key}")
        await _assert_code_free(db, StaffProfile, StaffProfile.staff_code, account.code, profile_id)
        profile = await db.get(StaffProfile, profile_id)
        platform = account.role in {"admin", "sub_admin"}
        if profile is None:
            profile = StaffProfile(
                id=profile_id,
                auth_user_uuid=ctx.user(account.key).id,
                role=StaffRole(account.role),
                scope=ProfileScope.PLATFORM if platform else ProfileScope.LINE,
                business_line=None if platform else account.business_line,
                staff_code=account.code,
                status=account.profile_status,
                created_by_auth_user_uuid=(
                    None if account.key == "admin-01" else ctx.user("admin-01").id
                ),
                # Never claim Main Admin: an environment's real owner keeps it.
                is_primary_admin=False,
            )
            db.add(profile)
        ctx.staff[account.key] = profile
    await db.flush()

    for account in catalog.staff_accounts():
        if account.payout_grant:
            grant_key = (ctx.staff[account.key].id, "payout_requests")
            if await db.get(StaffFeatureGrant, grant_key) is None:
                db.add(
                    StaffFeatureGrant(
                        staff_profile_uuid=ctx.staff[account.key].id,
                        feature="payout_requests",
                        granted_by_auth_user_uuid=ctx.user("admin-01").id,
                        created_at=ctx.now - timedelta(days=60),
                    )
                )

    approved_applications = {
        account.key: bulk_uuid(f"agent-application:approved:{account.key}")
        for account in catalog.accounts_by_role("agent")[:3]
    }
    for account in catalog.accounts_by_role("agent"):
        application_id = approved_applications.get(account.key)
        if application_id is not None:
            await add_once(
                db,
                AgentApplication(
                    id=application_id,
                    applicant_auth_user_uuid=ctx.user(account.key).id,
                    first_name=account.first_name,
                    last_name=account.last_name,
                    mobile=account.mobile,
                    email=account.email,
                    business_line=account.business_line,
                    rera_code=account.rera_code,
                    status=AgentSubmissionStatus.APPROVED,
                    reviewed_by_staff_profile_uuid=ctx.staff["admin-01"].id,
                    reviewed_at=ctx.now - timedelta(days=120),
                    created_at=ctx.now - timedelta(days=125),
                ),
            )
        profile_id = bulk_uuid(f"agent:{account.key}")
        await _assert_code_free(db, AgentProfile, AgentProfile.agent_code, account.code, profile_id)
        profile = await db.get(AgentProfile, profile_id)
        if profile is None:
            profile = AgentProfile(
                id=profile_id,
                auth_user_uuid=ctx.user(account.key).id,
                agent_code=account.code,
                business_line=account.business_line,
                application_uuid=application_id,
                kyc_status="verified",
                rera_code=account.rera_code,
                status=account.profile_status,
                approved_by_staff_profile_uuid=ctx.staff["admin-01"].id,
                approved_at=ctx.now - timedelta(days=120),
            )
            db.add(profile)
        ctx.agents[account.key] = profile

    for plan in catalog.agent_application_plans():
        rejected = plan.status == "rejected"
        await add_once(
            db,
            AgentApplication(
                id=bulk_uuid(f"agent-application:{plan.key}"),
                first_name=plan.first_name,
                last_name=plan.last_name,
                mobile=plan.mobile,
                email=f"{plan.first_name}.{plan.last_name}.{plan.key}@example.com".lower(),
                business_line=plan.line,
                rera_code=plan.rera_code,
                status=AgentSubmissionStatus.REJECTED
                if rejected
                else AgentSubmissionStatus.PENDING,
                review_note="Synthetic rejection: details could not be matched."
                if rejected
                else None,
                reviewed_by_staff_profile_uuid=ctx.staff["admin-02"].id if rejected else None,
                reviewed_at=ctx.now - timedelta(days=3) if rejected else None,
                created_at=ctx.now - timedelta(days=4 + len(plan.key) % 9),
            ),
        )

    for journey in catalog.client_journeys():
        account = catalog.account(journey.account_key)
        profile_id = bulk_uuid(f"client:{journey.key}")
        line_code = "LN" if journey.line == "loans" else "RE"
        code = f"CL-{line_code}{account.code}"
        await _assert_code_free(db, ClientProfile, ClientProfile.customer_code, code, profile_id)
        profile = await db.get(ClientProfile, profile_id)
        if profile is None:
            profile = ClientProfile(
                id=profile_id,
                auth_user_uuid=ctx.user(account.key).id,
                business_line=journey.line,
                customer_code=code,
                status=journey.profile_status,
                created_at=_days_ago(ctx.now, journey.ordinal, floor=20),
            )
            db.add(profile)
        ctx.clients[journey.key] = profile
    await db.flush()


async def _seed_teams(db: AsyncSession, ctx: Ctx) -> None:
    for team in catalog.TEAMS:
        team_id = bulk_uuid(f"team:{team.key}")
        if await db.get(StaffTeam, team_id) is None:
            db.add(
                StaffTeam(
                    id=team_id,
                    name=team.name,
                    business_line=team.business_line,
                    member_role=team.member_role,
                    manager_staff_profile_uuid=ctx.staff[team.manager_key].id,
                    created_by_auth_user_uuid=ctx.user("admin-01").id,
                )
            )
    await db.flush()
    for team in catalog.TEAMS:
        team_id = bulk_uuid(f"team:{team.key}")
        for member_key in team.member_keys:
            member = ctx.staff[member_key]
            if await db.get(StaffTeamMember, (team_id, member.id)) is None:
                db.add(
                    StaffTeamMember(
                        team_uuid=team_id,
                        staff_profile_uuid=member.id,
                        business_line=team.business_line,
                        added_by_auth_user_uuid=ctx.user("admin-01").id,
                    )
                )
    await db.flush()


async def _seed_referral_codes(db: AsyncSession, ctx: Ctx) -> None:
    from app.services import referrals

    for account in catalog.client_accounts():
        if account.user_status == UserStatus.ACTIVE:
            await referrals.issue_code_on_session(
                db, ctx.user(account.key).id, skip_eligibility=True
            )


# ---------------------------------------------------------------------------
# Real-estate catalogue and submissions
# ---------------------------------------------------------------------------


def _rera_review(
    applicability: ReraApplicability, verified: bool
) -> tuple[ReraVerificationStatus, bool]:
    if not verified or applicability == ReraApplicability.UNSURE:
        return ReraVerificationStatus.NOT_REVIEWED, False
    if applicability == ReraApplicability.EXEMPTION_CLAIMED:
        return ReraVerificationStatus.EXEMPTION_VERIFIED, True
    return ReraVerificationStatus.VERIFIED, True


def _submission_rera(applicability: ReraApplicability, wanted: str) -> ReraVerificationStatus:
    """Map a planned review outcome onto what the applicability allows."""
    if wanted == "mismatch":
        return ReraVerificationStatus.MISMATCH
    if wanted == "verified":
        if applicability == ReraApplicability.APPLICABLE:
            return ReraVerificationStatus.VERIFIED
        if applicability == ReraApplicability.EXEMPTION_CLAIMED:
            return ReraVerificationStatus.EXEMPTION_VERIFIED
    return ReraVerificationStatus.NOT_REVIEWED


def _listing_columns(index: int) -> dict[str, Any]:
    """Validate the planned facts exactly as a real submission, then flatten."""
    from app.services.property_submissions import format_inr_display

    facts = SubmissionFacts.model_validate(catalog.listing_facts(index))
    values = facts.model_dump(exclude={"structured_details", "listing_links"})
    values["structured_details"] = facts.structured_details.model_dump(mode="json")
    values["price_display"] = format_inr_display(facts.price_paise, facts.listing_intent)
    values["image"] = catalog.listing_image(facts.category, index)
    return values


async def _seed_properties(db: AsyncSession, ctx: Ctx) -> None:
    for index in range(catalog.LISTING_COUNT):
        property_id = bulk_uuid(f"property:{index}")
        prop = await db.get(Property, property_id)
        if prop is None:
            values = _listing_columns(index)
            status, reviewed = _rera_review(values["rera_applicability"], verified=True)
            prop = Property(
                id=property_id,
                business_line="real_estate",
                active=index % 37 != 36,  # a few unpublished listings for Admin filters
                details={},
                details_version=1,
                rera_verification_status=status,
                rera_verified_at=ctx.now - timedelta(days=10) if reviewed else None,
                rera_verified_by_uuid=ctx.user("admin-01").id if reviewed else None,
                created_at=_days_ago(ctx.now, index, spread=200),
                **values,
            )
            db.add(prop)
        ctx.properties.append(prop)
    await db.flush()

    for plan in catalog.submission_plans():
        submission_id = bulk_uuid(f"property-submission:{plan.key}")
        if await db.get(PropertySubmission, submission_id) is not None:
            continue
        values = _listing_columns(plan.index)
        values.pop("price_display")
        reviewed = plan.status != "pending"
        rera_status = _submission_rera(values["rera_applicability"], plan.rera_status)
        verified = rera_status != ReraVerificationStatus.NOT_REVIEWED
        db.add(
            PropertySubmission(
                id=submission_id,
                submitter_uuid=ctx.user(plan.submitter_key).id,
                business_line="real_estate",
                status=SubmissionStatus(plan.status),
                review_note=(
                    "Synthetic rejection: photos do not match the described unit."
                    if plan.status == "rejected"
                    else None
                ),
                reviewed_by_uuid=ctx.user("admin-02").id if reviewed else None,
                reviewed_at=ctx.now - timedelta(days=2) if reviewed else None,
                approved_property_id=(
                    ctx.properties[plan.approved_listing].id
                    if plan.approved_listing is not None
                    else None
                ),
                details={},
                details_version=1,
                rera_verification_status=rera_status,
                rera_verified_at=ctx.now - timedelta(days=2) if verified else None,
                rera_verified_by_uuid=ctx.user("admin-02").id if verified else None,
                created_at=ctx.now - timedelta(days=3 + int(plan.key[-2:])),
                **values,
            )
        )
    await db.flush()

    # The approved submission each remaining catalogue listing came from, so it
    # shows in the Admin "Published" view and its author's own listings.
    for index in catalog.listing_origin_indices():
        submission_id = bulk_uuid(f"property-submission:origin-{index}")
        if await db.get(PropertySubmission, submission_id) is not None:
            continue
        prop = ctx.properties[index]
        values = _listing_columns(index)
        values.pop("price_display")
        db.add(
            PropertySubmission(
                id=submission_id,
                submitter_uuid=ctx.user(catalog.listing_origin_author(index)).id,
                business_line="real_estate",
                status=SubmissionStatus.APPROVED,
                reviewed_by_uuid=ctx.user("admin-02").id,
                reviewed_at=prop.created_at,
                approved_property_id=prop.id,
                details={},
                details_version=1,
                rera_verification_status=prop.rera_verification_status,
                rera_verified_at=prop.rera_verified_at,
                rera_verified_by_uuid=prop.rera_verified_by_uuid,
                created_at=prop.created_at - timedelta(days=2),
                **values,
            )
        )
    await db.flush()


# ---------------------------------------------------------------------------
# Leads and telecaller activity
# ---------------------------------------------------------------------------


def _requirement(line: str, ordinal: int) -> dict[str, str]:
    if line == "loans":
        product = ("Home Loan", "Personal Loan", "Business Loan", "Car Loan", "Education Loan")
        return {
            "product": product[ordinal % len(product)],
            "location": "Hyderabad",
            "budget": f"Rs {5 + ordinal % 40} lakh",
            "note": "Synthetic test lead",
        }
    kind = ("2 BHK apartment", "3 BHK apartment", "Villa", "Open plot", "Office space")
    return {
        "property_type": kind[ordinal % len(kind)],
        "location": catalog.LOCALITIES[ordinal % len(catalog.LOCALITIES)][0],
        "budget": f"Rs {40 + ordinal % 160} lakh",
        "note": "Synthetic test lead",
    }


def _lead_row(
    *,
    key: str,
    ctx: Ctx,
    line: str,
    ordinal: int,
    name: str,
    mobile: str,
    status: LeadStatus,
    client: ClientProfile | None,
    agent_key: str | None,
    telecaller_key: str | None,
    agent_expired: bool = False,
) -> Lead:
    created = _days_ago(ctx.now, ordinal, spread=300, floor=2)
    agent = ctx.agents.get(agent_key) if agent_key else None
    live = status != LeadStatus.CLOSED
    expires_at = None
    expired_at = None
    if agent is not None:
        if agent_expired:
            expires_at = ctx.now - timedelta(days=3)
            expired_at = ctx.now - timedelta(days=2)
        elif live:
            expires_at = ctx.now + timedelta(days=4 + ordinal % 25)
    telecaller = ctx.staff_of(telecaller_key)
    return Lead(
        id=bulk_uuid(f"lead:{key}"),
        client_profile_uuid=client.id if client else None,
        business_line=line,
        origin=LeadOrigin.AGENT if agent else LeadOrigin.DIRECT,
        origin_agent_profile_uuid=agent.id if agent else None,
        assigned_telecaller_profile_uuid=telecaller.id if telecaller else None,
        name=name,
        mobile=mobile,
        requirement=_requirement(line, ordinal),
        detail_ownership={},
        status=status,
        released_at=ctx.now - timedelta(days=1 + ordinal % 6)
        if status == LeadStatus.RELEASED
        else None,
        release_reason="Synthetic release: not reachable after three attempts."
        if status == LeadStatus.RELEASED
        else None,
        expires_at=expires_at,
        agent_expired_at=expired_at,
        created_at=created,
    )


async def _seed_leads(db: AsyncSession, ctx: Ctx) -> None:
    for journey in catalog.client_journeys():
        if journey.lead_status is None:
            continue
        account = catalog.account(journey.account_key)
        row = _lead_row(
            key=journey.key,
            ctx=ctx,
            line=journey.line,
            ordinal=journey.ordinal,
            name=f"{account.first_name} {account.last_name}",
            mobile=account.mobile,
            status=journey.lead_status,
            client=ctx.clients[journey.key],
            agent_key=journey.agent_key,
            telecaller_key=journey.telecaller_key,
        )
        lead = await db.get(Lead, row.id)
        if lead is None:
            db.add(row)
            lead = row
        ctx.leads[journey.key] = lead

    for prospect in catalog.prospects():
        row = _lead_row(
            key=prospect.key,
            ctx=ctx,
            line=prospect.line,
            ordinal=int(prospect.key[-2:]) + (50 if prospect.line == "real_estate" else 0),
            name=prospect.name,
            mobile=prospect.mobile,
            status=prospect.status,
            client=None,
            agent_key=prospect.agent_key,
            telecaller_key=prospect.telecaller_key,
            agent_expired=prospect.agent_expired,
        )
        lead = await db.get(Lead, row.id)
        if lead is None:
            db.add(row)
            lead = row
        ctx.leads[prospect.key] = lead
    await db.flush()

    dispositions = tuple(CallDisposition)
    interests = tuple(InterestLevel)
    for position, (key, lead) in enumerate(sorted(ctx.leads.items())):
        if lead.assigned_telecaller_profile_uuid is None or lead.status in {
            LeadStatus.NEW,
            LeadStatus.RELEASED,
        }:
            continue
        open_lead = lead.status in {LeadStatus.ASSIGNED, LeadStatus.WORKING}
        for number in range(1 + position % 3):
            last = number == position % 3
            follow_up = None
            if open_lead and last:
                # Alternate overdue, due today and upcoming callbacks.
                follow_up = ctx.now + timedelta(hours=(-30, 2, 50)[position % 3])
            await add_once(
                db,
                LeadActivity(
                    id=bulk_uuid(f"lead-activity:{key}:{number}"),
                    lead_uuid=lead.id,
                    telecaller_staff_profile_uuid=lead.assigned_telecaller_profile_uuid,
                    business_line=lead.business_line,
                    disposition=dispositions[(position + number) % len(dispositions)],
                    interest_level=interests[(position + number) % len(interests)],
                    notes=f"Synthetic call note {number + 1}.",
                    follow_up_at=follow_up,
                    created_at=lead.created_at + timedelta(days=1 + number * 3),
                ),
            )
    await db.flush()


# ---------------------------------------------------------------------------
# Loans and other financial products
# ---------------------------------------------------------------------------


def _form_answers(
    product: LoanType, *, ordinal: int, amount: int, mobile: str, pincode: str
) -> dict[str, Any]:
    definition = ProductFormDefinition.model_validate(product.custom_fields)
    answers: dict[str, Any] = {}
    for field_def in definition.fields():
        if (
            field_def.condition is not None
            and answers.get(field_def.condition.field_key) != field_def.condition.equals
        ):
            continue
        kind = field_def.input_type.value
        options = [option.value for option in field_def.options]
        if field_def.key == "requested_amount":
            answers[field_def.key] = str(amount)
        elif kind == "select":
            answers[field_def.key] = options[ordinal % len(options)]
        elif kind == "multi_select":
            answers[field_def.key] = options[: 1 + ordinal % min(2, len(options))]
        elif kind == "date":
            answers[field_def.key] = (
                date(1975 + ordinal % 25, 1 + ordinal % 12, 1 + ordinal % 27).isoformat()
                if field_def.key.endswith("date_of_birth")
                else date(2027, 1 + ordinal % 12, 10).isoformat()
            )
        elif kind == "currency":
            answers[field_def.key] = str(40_000 + (ordinal % 20) * 5_000)
        elif kind == "integer":
            answers[field_def.key] = str(1 + ordinal % 9)
        elif kind == "pincode":
            answers[field_def.key] = pincode
        elif kind == "phone":
            answers[field_def.key] = mobile[-10:]
        elif kind == "textarea":
            answers[field_def.key] = "Synthetic answer for development testing."
        elif field_def.required:
            answers[field_def.key] = "Synthetic"
    return validate_form_answers(definition, answers)


_LOAN_AMOUNTS = {
    "home-loan": 4_500_000,
    "loan-against-property": 3_000_000,
    "business-loan": 1_500_000,
    "project-funding": 9_000_000,
    "car-loan": 900_000,
    "vehicle-loan": 650_000,
    "education-loan": 1_200_000,
    "equipment-financing": 2_000_000,
    "school-funding": 5_000_000,
}
_SANCTIONED_OR_LATER = {
    LoanStatus.SANCTIONED,
    LoanStatus.AGREEMENT_COLLECTED,
    LoanStatus.AGREEMENT_SUBMITTED_TO_BANK,
    LoanStatus.DISBURSED,
    LoanStatus.CLOSED,
}


def _loan_row(
    *,
    key: str,
    ctx: Ctx,
    journey: ClientJourney,
    product: LoanType,
    status: LoanStatus,
    opened: datetime,
) -> LoanApplication:
    account = catalog.account(journey.account_key)
    amount = _LOAN_AMOUNTS.get(product.name, 500_000) + (journey.ordinal % 10) * 50_000
    sanctioned = status in _SANCTIONED_OR_LATER
    fee = Decimal(amount) * Decimal("0.01") if sanctioned else None
    disbursed = status in {LoanStatus.DISBURSED, LoanStatus.CLOSED}
    pincode = catalog.LOCALITIES[journey.ordinal % len(catalog.LOCALITIES)][1]
    return LoanApplication(
        id=bulk_uuid(f"loan:{key}"),
        lead_uuid=ctx.leads[journey.key].id,
        client_profile_uuid=ctx.clients[journey.key].id,
        business_line="loans",
        loan_type_id=product.id,
        amount_requested=amount,
        amount_sanctioned=amount - (journey.ordinal % 4) * 25_000 if sanctioned else None,
        interest_rate=Decimal("8.40") + Decimal(journey.ordinal % 12) / 4 if sanctioned else None,
        processing_fee=fee.quantize(Decimal("0.01")) if fee is not None else None,
        fee_outcome=(
            (FeeOutcome.CASHBACK, FeeOutcome.WAIVED, FeeOutcome.NONE_)[journey.ordinal % 3]
            if sanctioned
            else None
        ),
        status=status,
        status_reason={
            LoanStatus.ON_HOLD: "Synthetic hold: awaiting updated bank statement.",
            LoanStatus.REJECTED: "Synthetic rejection: income below lender policy.",
        }.get(status),
        form_version=product.form_version,
        form_schema_snapshot=product.custom_fields,
        form_answers=_form_answers(
            product,
            ordinal=journey.ordinal,
            amount=amount,
            mobile=account.mobile,
            pincode=pincode,
        ),
        opened_at=opened,
        closed_at=opened + timedelta(days=40)
        if status in {LoanStatus.CLOSED, LoanStatus.REJECTED}
        else None,
        disbursed_at=opened + timedelta(days=25) if disbursed else None,
    )


async def _seed_loans(db: AsyncSession, ctx: Ctx) -> None:
    products = list(
        (
            await db.scalars(
                select(LoanType)
                .where(LoanType.active.is_(True), LoanType.category == "loan")
                .order_by(LoanType.display_order, LoanType.name)
            )
        ).all()
    )
    products = [product for product in products if product.custom_fields]
    if not products:
        raise RuntimeError("Run `alembic upgrade head`; no configured loan products were found.")
    card = await db.scalar(
        select(LoanType).where(LoanType.active.is_(True), LoanType.category == "credit_card")
    )

    for journey in catalog.client_journeys():
        if journey.line != "loans" or journey.lead_status is None:
            continue
        product = products[journey.loan_product_index % len(products)]
        opened = _days_ago(ctx.now, journey.ordinal, spread=300, floor=5)
        plan: list[tuple[str, LoanStatus, LoanType, datetime]] = []
        if journey.closed_loan:
            older = products[(journey.loan_product_index + 3) % len(products)]
            plan.append(("closed", LoanStatus.CLOSED, older, opened - timedelta(days=220)))
        if journey.rejected_loan:
            other = products[(journey.loan_product_index + 5) % len(products)]
            plan.append(("rejected", LoanStatus.REJECTED, other, opened - timedelta(days=120)))
        if journey.current_loan_status is not None:
            plan.append(("current", journey.current_loan_status, product, opened))
        for suffix, status, loan_type, opened_at in plan:
            key = f"{journey.key}:{suffix}"
            row = _loan_row(
                key=key,
                ctx=ctx,
                journey=journey,
                product=loan_type,
                status=status,
                opened=opened_at,
            )
            application = await db.get(LoanApplication, row.id)
            if application is None:
                db.add(row)
                application = row
            if suffix == "current":
                ctx.current_loans[journey.key] = application
            elif suffix == "closed":
                ctx.closed_loans[journey.key] = application
            if status in _SANCTIONED_OR_LATER:
                await add_once(
                    db,
                    LoanTxnHistory(
                        id=bulk_uuid(f"loan-txn-history:{key}"),
                        loan_application_uuid=row.id,
                        business_line="loans",
                        bank_name="Synthetic partner bank (test)",
                        amount=row.amount_sanctioned,
                        interest_rate=row.interest_rate,
                        txn_date=(opened_at + timedelta(days=18)).date(),
                        entered_by_staff_profile_uuid=ctx.staff_of(journey.telecaller_key).id
                        if journey.telecaller_key
                        else None,
                    ),
                )
        await db.flush()

        if journey.card_enquiry and card is not None and card.custom_fields:
            account = catalog.account(journey.account_key)
            await add_once(
                db,
                FinancialServiceEnquiry(
                    id=bulk_uuid(f"card-enquiry:{journey.key}"),
                    lead_uuid=ctx.leads[journey.key].id,
                    client_profile_uuid=ctx.clients[journey.key].id,
                    business_line="loans",
                    product_id=card.id,
                    product_category=card.category,
                    form_version=card.form_version,
                    form_schema_snapshot=card.custom_fields,
                    form_answers=_form_answers(
                        card,
                        ordinal=journey.ordinal,
                        amount=0,
                        mobile=account.mobile,
                        pincode="500032",
                    ),
                    submitted_at=_days_ago(ctx.now, journey.ordinal, spread=90),
                ),
            )
    await db.flush()


# ---------------------------------------------------------------------------
# Real-estate journeys
# ---------------------------------------------------------------------------

_VISIT_AFTER_DEAL = {
    PropertyDealStatus.SITE_VISIT_DONE,
    PropertyDealStatus.NEGOTIATION,
    PropertyDealStatus.BOOKED,
    PropertyDealStatus.AGREEMENT_SIGNED,
    PropertyDealStatus.CLOSED,
}
_BOOKED_OR_LATER = {
    PropertyDealStatus.BOOKED,
    PropertyDealStatus.AGREEMENT_SIGNED,
    PropertyDealStatus.CLOSED,
}


def _visit_status(journey: ClientJourney) -> SiteVisitStatus:
    if journey.deal_status in _VISIT_AFTER_DEAL:
        return SiteVisitStatus.DONE
    if journey.deal_status is not None:
        return (SiteVisitStatus.REQUESTED, SiteVisitStatus.CONFIRMED)[journey.ordinal % 2]
    return tuple(SiteVisitStatus)[journey.ordinal % len(SiteVisitStatus)]


async def _seed_real_estate(db: AsyncSession, ctx: Ctx) -> None:
    listings = [prop for prop in ctx.properties if prop.active]
    employees = [
        ctx.staff[a.key]
        for a in catalog.accounts_by_role("employee", "real_estate")
        if a.profile_status == ProfileStatus.ACTIVE
    ]
    for journey in catalog.client_journeys():
        if journey.line != "real_estate" or journey.lead_status is None:
            continue
        account = catalog.account(journey.account_key)
        user = ctx.user(account.key)
        lead = ctx.leads[journey.key]
        primary = listings[(journey.ordinal * 7) % len(listings)]
        contact = f"{account.first_name} {account.last_name}"

        for number in range(journey.bookmarks):
            prop = listings[(journey.ordinal * 11 + number * 3) % len(listings)]
            await add_once(
                db,
                Bookmark(
                    id=bulk_uuid(f"bookmark:{journey.key}:{number}"),
                    user_uuid=user.id,
                    business_line="real_estate",
                    property_ref=str(prop.id),
                    title=prop.title,
                    locality=prop.locality,
                    city=prop.city,
                    created_at=_days_ago(ctx.now, journey.ordinal + number, spread=120),
                ),
            )

        if journey.enquiry:
            prop = listings[(journey.ordinal * 5 + 1) % len(listings)]
            await add_once(
                db,
                Enquiry(
                    id=bulk_uuid(f"enquiry:{journey.key}"),
                    user_uuid=user.id,
                    lead_uuid=lead.id,
                    business_line="real_estate",
                    property_ref=str(prop.id),
                    title=prop.title,
                    locality=prop.locality,
                    city=prop.city,
                    contact_name=contact,
                    contact_mobile=account.mobile,
                    message="Synthetic enquiry: is this still available?",
                    status=tuple(EnquiryStatus)[(journey.ordinal // 3) % len(EnquiryStatus)],
                    created_at=_days_ago(ctx.now, journey.ordinal, spread=150),
                ),
            )

        visit: SiteVisit | None = None
        if journey.site_visit:
            status = _visit_status(journey)
            past = (
                status in {SiteVisitStatus.DONE, SiteVisitStatus.CANCELLED}
                and journey.ordinal % 2 == 0
            )
            preferred = (
                date.today() - timedelta(days=5 + journey.ordinal % 40)
                if status == SiteVisitStatus.DONE or past
                else date.today() + timedelta(days=1 + journey.ordinal % 14)
            )
            row = SiteVisit(
                id=bulk_uuid(f"site-visit:{journey.key}"),
                user_uuid=user.id,
                lead_uuid=lead.id,
                business_line="real_estate",
                property_ref=str(primary.id),
                title=primary.title,
                locality=primary.locality,
                city=primary.city,
                contact_name=contact,
                contact_mobile=account.mobile,
                preferred_date=preferred,
                preferred_time_slot=tuple(SiteVisitTimeSlot)[
                    journey.ordinal % len(SiteVisitTimeSlot)
                ],
                message="Synthetic site visit request.",
                status=status,
                cancelled_at=ctx.now - timedelta(days=1)
                if status == SiteVisitStatus.CANCELLED
                else None,
                created_at=_days_ago(ctx.now, journey.ordinal, spread=90, floor=6),
            )
            visit = await db.get(SiteVisit, row.id)
            if visit is None:
                db.add(row)
                visit = row
            await db.flush()

            if journey.ordinal % 3 == 0 or status == SiteVisitStatus.CONFIRMED:
                arrangement_status = {
                    SiteVisitStatus.CANCELLED: VehicleArrangementStatus.CANCELLED,
                    SiteVisitStatus.DONE: VehicleArrangementStatus.COMPLETED,
                    SiteVisitStatus.REQUESTED: VehicleArrangementStatus.REQUESTED,
                }.get(
                    status,
                    (
                        VehicleArrangementStatus.REQUESTED,
                        VehicleArrangementStatus.ARRANGED,
                        VehicleArrangementStatus.ASSIGNED,
                    )[(journey.ordinal // 2) % 3],
                )
                staffed = arrangement_status in {
                    VehicleArrangementStatus.ARRANGED,
                    VehicleArrangementStatus.ASSIGNED,
                    VehicleArrangementStatus.COMPLETED,
                }
                pickup = datetime.combine(preferred, datetime.min.time(), tzinfo=UTC) + timedelta(
                    hours=9
                )
                pickup_area = catalog.LOCALITIES[journey.ordinal % len(catalog.LOCALITIES)][0]
                await add_once(
                    db,
                    VehicleArrangement(
                        id=bulk_uuid(f"vehicle:{journey.key}"),
                        site_visit_uuid=visit.id,
                        business_line="real_estate",
                        pickup_location=f"{pickup_area} Metro Station, Hyderabad",
                        pickup_at=pickup,
                        status=arrangement_status,
                        vehicle_make_model="Synthetic Sedan" if staffed else None,
                        vehicle_registration=f"TS09BK{journey.ordinal:04d}" if staffed else None,
                        driver_name="Synthetic Driver" if staffed else None,
                        driver_mobile=catalog.bulk_mobile(80_000 + journey.ordinal)
                        if staffed
                        else None,
                        assigned_employee_profile_uuid=employees[
                            journey.ordinal % len(employees)
                        ].id
                        if arrangement_status
                        in {VehicleArrangementStatus.ASSIGNED, VehicleArrangementStatus.COMPLETED}
                        else None,
                        arranged_by_staff_profile_uuid=ctx.staff["admin-01"].id
                        if staffed
                        else None,
                        completed_at=pickup + timedelta(hours=3)
                        if arrangement_status == VehicleArrangementStatus.COMPLETED
                        else None,
                        cancelled_at=ctx.now - timedelta(days=1)
                        if arrangement_status == VehicleArrangementStatus.CANCELLED
                        else None,
                        cancellation_reason="Synthetic cancellation: visit cancelled by client."
                        if arrangement_status == VehicleArrangementStatus.CANCELLED
                        else None,
                    ),
                )

        if journey.deal_status is not None:
            status = journey.deal_status
            opened = _days_ago(ctx.now, journey.ordinal, spread=240, floor=10)
            booked = status in _BOOKED_OR_LATER
            row = PropertyDeal(
                id=bulk_uuid(f"deal:{journey.key}"),
                lead_uuid=lead.id,
                client_profile_uuid=ctx.clients[journey.key].id,
                property_id=primary.id,
                business_line="real_estate",
                site_visit_uuid=visit.id if visit is not None else None,
                price_quoted=Decimal(primary.price_paise) / 100 if booked else None,
                booking_amount=Decimal(primary.price_paise) / 100 * Decimal("0.05")
                if booked
                else None,
                status=status,
                status_reason={
                    PropertyDealStatus.ON_HOLD: "Synthetic hold: buyer arranging finance.",
                    PropertyDealStatus.REJECTED: "Synthetic rejection: buyer chose another unit.",
                }.get(status),
                opened_at=opened,
                closed_at=opened + timedelta(days=60)
                if status in {PropertyDealStatus.CLOSED, PropertyDealStatus.REJECTED}
                else None,
            )
            deal = await db.get(PropertyDeal, row.id)
            if deal is None:
                db.add(row)
                deal = row
            ctx.deals[journey.key] = deal
    await db.flush()


# ---------------------------------------------------------------------------
# Employee tasks
# ---------------------------------------------------------------------------

TASKS_PER_LINE = 45


async def _seed_tasks(db: AsyncSession, ctx: Ctx) -> None:
    statuses = tuple(TaskStatus)
    for line in ("loans", "real_estate"):
        employees = [
            ctx.staff[a.key]
            for a in catalog.accounts_by_role("employee", line)
            if a.profile_status == ProfileStatus.ACTIVE
        ]
        types = (
            (TaskType.DOCUMENT_COLLECTION, TaskType.BACKGROUND_CHECK)
            if line == "loans"
            else (TaskType.PROPERTY_VISIT, TaskType.DOCUMENT_COLLECTION, TaskType.BACKGROUND_CHECK)
        )
        eligible = [
            (key, lead)
            for key, lead in sorted(ctx.leads.items())
            if lead.business_line == line
            and lead.assigned_telecaller_profile_uuid is not None
            and lead.status in {LeadStatus.WORKING, LeadStatus.CONVERTED, LeadStatus.ASSIGNED}
        ]
        for number in range(min(TASKS_PER_LINE, len(eligible))):
            key, lead = eligible[number]
            status = statuses[number % len(statuses)]
            task_type = types[number % len(types)]
            due = ctx.now + timedelta(hours=(-50, -4, 6, 30, 80)[number % 5])
            row = Task(
                id=bulk_uuid(f"task:{line}:{number}"),
                assigned_employee_profile_uuid=None
                if status == TaskStatus.UNASSIGNED
                # Offset by the status round so each Employee gets a mix of states
                # even when the team size equals the number of statuses.
                else employees[(number + number // len(statuses)) % len(employees)].id,
                raised_by_staff_profile_uuid=lead.assigned_telecaller_profile_uuid,
                business_line=line,
                task_type=task_type,
                lead_uuid=lead.id,
                status=status,
                notes=f"Synthetic {task_type.value.replace('_', ' ')} task for {key}.",
                outcome=tuple(BgCheckOutcome)[number % len(BgCheckOutcome)]
                if task_type == TaskType.BACKGROUND_CHECK and status == TaskStatus.COMPLETED
                else None,
                due_at=due,
                created_at=due - timedelta(days=3),
            )
            task = await db.get(Task, row.id)
            if task is None:
                db.add(row)
                task = row
            ctx.tasks.append(task)
    await db.flush()


# ---------------------------------------------------------------------------
# Money: ledgers, payouts, cashbacks, commissions and referrals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PayoutSpec:
    key: str
    recipient: User
    line: str
    kind: PayoutType
    amount_paise: int
    status: PayoutStatus
    destination: PayoutDestination
    maker: User
    checker: User | None


async def _payout(db: AsyncSession, ctx: Ctx, spec: PayoutSpec) -> Payout:
    from app.services.payments import _clawback_description, _ledger_description

    payout_id = bulk_uuid(f"payout:{spec.key}")
    existing = await db.get(Payout, payout_id)
    if existing is not None:
        return existing

    manual = spec.destination == PayoutDestination.CHEQUE
    created = ctx.now - timedelta(days=5 + sum(map(ord, spec.key)) % 60)
    status = spec.status
    ledger_id = None
    reversal_id = None
    if status in {PayoutStatus.PAID, PayoutStatus.REVERSED}:
        ledger = Transaction(
            id=bulk_uuid(f"transaction:{spec.key}"),
            user_uuid=spec.recipient.id,
            business_line=spec.line,
            type=TransactionType(spec.kind.value),
            status=TransactionStatus.PAID,
            amount_paise=spec.amount_paise,
            description=_ledger_description(spec.kind),
            reference=f"payout:{payout_id}",
            created_at=created + timedelta(days=2),
        )
        db.add(ledger)
        ledger_id = ledger.id
        if status == PayoutStatus.REVERSED:
            reversal = Transaction(
                id=bulk_uuid(f"transaction:{spec.key}:reversal"),
                user_uuid=spec.recipient.id,
                business_line=spec.line,
                type=TransactionType(spec.kind.value),
                status=TransactionStatus.PAID,
                amount_paise=-spec.amount_paise,
                description=_clawback_description(spec.kind),
                reference=f"payout:{payout_id}",
                created_at=created + timedelta(days=6),
            )
            db.add(reversal)
            reversal_id = reversal.id
        await db.flush()

    gateway = not manual and status in {
        PayoutStatus.INITIATED,
        PayoutStatus.PROCESSING,
        PayoutStatus.PAID,
        PayoutStatus.FAILED,
        PayoutStatus.REVERSED,
    }
    issued = manual and status in {
        PayoutStatus.PROCESSING,
        PayoutStatus.PAID,
        PayoutStatus.FAILED,
        PayoutStatus.REVERSED,
    }
    hint = {
        PayoutDestination.VPA: "UPI · bk****@okaxis",
        PayoutDestination.BANK_ACCOUNT: "Bank · XXXX4321",
        PayoutDestination.CHEQUE: f"Cheque · BK{int(_fingerprint(spec.key)[:6], 16) % 100000:05d}",
    }[spec.destination]
    payout = Payout(
        id=payout_id,
        recipient_user_uuid=spec.recipient.id,
        business_line=spec.line,
        type=spec.kind,
        amount_paise=spec.amount_paise,
        status=status,
        destination_type=spec.destination,
        provider=PayoutProvider.MANUAL if manual else PayoutProvider.RAZORPAYX,
        destination_hint=hint,
        idempotency_key=f"bulk-{spec.key}"[:64],
        maker_user_uuid=spec.maker.id,
        checker_user_uuid=spec.checker.id
        if spec.checker is not None and status != PayoutStatus.REJECTED
        else None,
        rejected_by_user_uuid=spec.checker.id
        if spec.checker is not None and status == PayoutStatus.REJECTED
        else None,
        reject_reason="Synthetic rejection: amount does not match the agreement."
        if status == PayoutStatus.REJECTED
        else None,
        gateway_contact_id=f"cont_bulk{_fingerprint(spec.key)[:10]}" if gateway else None,
        gateway_fund_account_id=f"fa_bulk{_fingerprint(spec.key)[:12]}" if gateway else None,
        gateway_payout_id=f"pout_bulk{_fingerprint(spec.key)[:12]}" if gateway else None,
        gateway_status={
            PayoutStatus.INITIATED: "queued",
            PayoutStatus.PROCESSING: "processing",
            PayoutStatus.PAID: "processed",
            PayoutStatus.FAILED: "failed",
            PayoutStatus.REVERSED: "reversed",
        }.get(status)
        if gateway
        else None,
        failure_reason={
            PayoutStatus.FAILED: "Synthetic failure: beneficiary bank rejected the transfer.",
            PayoutStatus.REVERSED: "Synthetic reversal: funds returned by the bank.",
        }.get(status),
        manual_reference_fingerprint=_fingerprint(spec.key) if issued else None,
        manual_issued_at=created + timedelta(days=1) if issued else None,
        manual_cleared_at=created + timedelta(days=2)
        if manual and status in {PayoutStatus.PAID, PayoutStatus.REVERSED}
        else None,
        ledger_transaction_id=ledger_id,
        reversal_transaction_id=reversal_id,
        created_at=created,
    )
    db.add(payout)
    await db.flush()
    return payout


async def _seed_money(db: AsyncSession, ctx: Ctx) -> None:
    makers = [ctx.user("subadmin-06"), ctx.user("subadmin-07"), ctx.user("admin-01")]
    checker = ctx.user("admin-02")
    destinations = (PayoutDestination.VPA, PayoutDestination.BANK_ACCOUNT, PayoutDestination.CHEQUE)

    # Fee cashbacks on disbursed loans whose fee outcome is cashback.
    cashback_cycle = (
        FeeCashbackStatus.PENDING,
        FeeCashbackStatus.PAID,
        FeeCashbackStatus.CANCELLED,
    )
    number = 0
    for key, application in sorted(
        {**ctx.current_loans, **{f"{k}:closed": v for k, v in ctx.closed_loans.items()}}.items()
    ):
        if application.disbursed_at is None or application.processing_fee is None:
            continue
        journey_key = key.removesuffix(":closed")
        client_user = ctx.user(journey_key.split(":")[0])
        fee_paise = int(Decimal(application.processing_fee) * 100)
        status = cashback_cycle[number % len(cashback_cycle)]
        amount = fee_paise // 2
        payout = None
        if status == FeeCashbackStatus.PAID:
            payout = await _payout(
                db,
                ctx,
                PayoutSpec(
                    f"cashback:{key}",
                    client_user,
                    "loans",
                    PayoutType.CASHBACK,
                    amount,
                    PayoutStatus.PAID,
                    destinations[number % 3],
                    makers[number % 3],
                    checker,
                ),
            )
        await add_once(
            db,
            FeeCashback(
                id=bulk_uuid(f"fee-cashback:{key}"),
                loan_application_uuid=application.id,
                client_profile_uuid=application.client_profile_uuid,
                recipient_auth_user_uuid=client_user.id,
                business_line="loans",
                processing_fee_paise=fee_paise,
                amount_paise=amount,
                status=status,
                payout_uuid=payout.id if payout else None,
                payout_txn_uuid=payout.ledger_transaction_id if payout else None,
                entered_by_uuid=ctx.user("admin-01").id,
                notes="Synthetic processing-fee cashback.",
                cancelled_reason="Synthetic cancellation: fee was waived instead."
                if status == FeeCashbackStatus.CANCELLED
                else None,
            ),
        )
        number += 1

    # Agent commissions on disbursed loans and booked-or-later deals.
    commission_cycle = (CommissionStatus.PENDING, CommissionStatus.PAID, CommissionStatus.CANCELLED)
    number = 0
    for journey in catalog.client_journeys():
        if journey.agent_key is None or journey.agent_key not in ctx.agents:
            continue
        loan = ctx.current_loans.get(journey.key) or ctx.closed_loans.get(journey.key)
        deal = ctx.deals.get(journey.key)
        if journey.line == "loans" and (loan is None or loan.disbursed_at is None):
            continue
        if journey.line == "real_estate" and (deal is None or deal.status not in _BOOKED_OR_LATER):
            continue
        agent_user = ctx.user(journey.agent_key)
        status = commission_cycle[number % len(commission_cycle)]
        amount = (25_000 if journey.line == "loans" else 75_000) * 100 + number * 1_000_00
        payout = None
        if status == CommissionStatus.PAID:
            payout = await _payout(
                db,
                ctx,
                PayoutSpec(
                    f"commission:{journey.key}",
                    agent_user,
                    journey.line,
                    PayoutType.COMMISSION,
                    amount,
                    PayoutStatus.PAID,
                    destinations[number % 3],
                    makers[number % 3],
                    checker,
                ),
            )
        await add_once(
            db,
            Commission(
                id=bulk_uuid(f"commission:{journey.key}"),
                agent_auth_user_uuid=agent_user.id,
                agent_profile_uuid=ctx.agents[journey.agent_key].id,
                business_line=journey.line,
                lead_uuid=ctx.leads[journey.key].id,
                loan_application_uuid=loan.id if journey.line == "loans" and loan else None,
                property_deal_uuid=deal.id if journey.line == "real_estate" and deal else None,
                agreed_amount_paise=amount,
                status=status,
                payout_uuid=payout.id if payout else None,
                payout_txn_uuid=payout.ledger_transaction_id if payout else None,
                entered_by_uuid=ctx.user("admin-01").id,
                notes="Synthetic negotiated commission.",
                cancelled_reason="Synthetic cancellation: deal terms changed."
                if status == CommissionStatus.CANCELLED
                else None,
            ),
        )
        number += 1

    # Stand-alone payouts covering every maker/checker and gateway state.
    recipients = [
        (ctx.user(a.key), a.business_line or "loans", PayoutType.COMMISSION)
        for a in catalog.accounts_by_role("agent")
        if a.profile_status == ProfileStatus.ACTIVE
    ]
    recipients += [
        (ctx.user(c.key), c.client_lines[0], PayoutType.REFERRAL_BONUS)
        for c in catalog.client_accounts()[:20]
        if c.user_status == UserStatus.ACTIVE
    ]
    for position, status in enumerate(list(PayoutStatus) * 3):
        recipient, line, kind = recipients[position % len(recipients)]
        destination = destinations[position % 3]
        if status in {PayoutStatus.INITIATED} and destination == PayoutDestination.CHEQUE:
            destination = PayoutDestination.VPA  # cheques have no gateway hand-off
        await _payout(
            db,
            ctx,
            PayoutSpec(
                f"state:{status.value}:{position}",
                recipient,
                line,
                kind,
                (1_500 + position * 250) * 100,
                status,
                destination,
                makers[position % 3],
                None if status == PayoutStatus.PENDING_APPROVAL else checker,
            ),
        )

    await _seed_referrals(db, ctx)


async def _referral_config(db: AsyncSession, ctx: Ctx, line: str) -> ReferralBonusConfig:
    active = await db.scalar(
        select(ReferralBonusConfig).where(
            ReferralBonusConfig.business_line == line, ReferralBonusConfig.active.is_(True)
        )
    )
    if active is not None:
        return active
    config = ReferralBonusConfig(
        id=bulk_uuid(f"referral-config:{line}"),
        business_line=line,
        bonus_amount=Decimal("1500") if line == "loans" else Decimal("2500"),
        rule={"minimum_conversions": 1, "monthly_cap": 10, "synthetic": True},
        active=True,
        created_by_uuid=ctx.user("subadmin-06").id,
    )
    existing = await db.get(ReferralBonusConfig, config.id)
    if existing is not None:
        return existing
    db.add(config)
    await db.flush()
    return config


async def _seed_referrals(db: AsyncSession, ctx: Ctx) -> None:
    config = await _referral_config(db, ctx, "loans")
    referrers = [c for c in catalog.client_accounts() if c.user_status == UserStatus.ACTIVE]
    # Referred, registered clients: Loans journeys with a current application.
    referred = [
        journey
        for journey in catalog.client_journeys()
        if journey.line == "loans" and journey.key in ctx.current_loans and journey.ordinal >= 40
    ]
    statuses = tuple(ReferralStatus)
    for number in range(25):
        status = statuses[number % len(statuses)]
        referrer = ctx.user(referrers[number].key)
        row_id = bulk_uuid(f"referral:{number}")
        if await db.get(Referral, row_id) is not None:
            continue
        if status in {ReferralStatus.PENDING, ReferralStatus.VOID}:
            db.add(
                Referral(
                    id=row_id,
                    referrer_auth_user_uuid=referrer.id,
                    referred_mobile=catalog.bulk_mobile(catalog.REFERRED_MOBILE_BASE + number + 1),
                    conversion_status=status,
                    created_at=ctx.now - timedelta(days=3 + number),
                )
            )
            continue
        journey = referred[number % len(referred)]
        referred_account = catalog.account(journey.account_key)
        application = ctx.current_loans[journey.key]
        if referred_account.key == referrers[number].key:
            continue
        amount = int(Decimal(config.bonus_amount) * 100)
        payout = None
        if status == ReferralStatus.PAID:
            payout = await _payout(
                db,
                ctx,
                PayoutSpec(
                    f"referral:{number}",
                    referrer,
                    "loans",
                    PayoutType.REFERRAL_BONUS,
                    amount,
                    PayoutStatus.PAID,
                    PayoutDestination.VPA,
                    ctx.user("subadmin-06"),
                    ctx.user("admin-02"),
                ),
            )
        accrued = status in {ReferralStatus.ACCRUED, ReferralStatus.PAID}
        db.add(
            Referral(
                id=row_id,
                referrer_auth_user_uuid=referrer.id,
                referred_mobile=referred_account.mobile,
                referred_auth_user_uuid=ctx.user(referred_account.key).id,
                referred_lead_uuid=ctx.leads[journey.key].id,
                business_line="loans",
                conversion_status=status,
                converted_ref_type="loan_application",
                converted_ref_uuid=application.id,
                converted_at=ctx.now - timedelta(days=10 + number),
                bonus_config_uuid=config.id if accrued else None,
                bonus_amount_paise=amount if accrued else None,
                accrual_reason="accrued" if accrued else None,
                reward_txn_uuid=payout.ledger_transaction_id if payout else None,
                reward_payout_uuid=payout.id if payout else None,
                created_at=ctx.now - timedelta(days=30 + number),
            )
        )
        await db.flush()


# ---------------------------------------------------------------------------
# Support, notifications and audit
# ---------------------------------------------------------------------------

_ROLE_NOTIFICATIONS: dict[str, tuple[tuple[NotificationType, str, str, str], ...]] = {
    "admin": (
        (
            NotificationType.ADMIN_PAYOUT_REVIEWED,
            "Payout awaiting review",
            "A synthetic payout needs a checker.",
            "/dashboard/payouts",
        ),
        (
            NotificationType.SUPPORT_TICKET_RECEIVED,
            "New support ticket",
            "A synthetic ticket was raised.",
            "/dashboard/support",
        ),
    ),
    "sub_admin": (
        (
            NotificationType.ADMIN_BROADCAST,
            "Team update",
            "Synthetic broadcast for your workspace.",
            "/dashboard",
        ),
        (
            NotificationType.CAMPAIGN_CHANGES_REQUESTED,
            "Changes requested",
            "A synthetic campaign needs edits.",
            "/dashboard/banners",
        ),
    ),
    "telecaller": (
        (
            NotificationType.LEAD_ASSIGNED,
            "Lead assigned",
            "A synthetic lead was assigned to you.",
            "/dashboard/leads",
        ),
        (
            NotificationType.LEAD_RELEASED,
            "Lead released",
            "A synthetic lead returned to the pool.",
            "/dashboard/leads",
        ),
    ),
    "employee": (
        (
            NotificationType.TASK_ASSIGNED,
            "Task assigned",
            "A synthetic field task is due soon.",
            "/dashboard/tasks",
        ),
        (
            NotificationType.VEHICLE_ARRANGEMENT_UPDATED,
            "Pickup updated",
            "A synthetic vehicle pickup changed.",
            "/dashboard/tasks",
        ),
    ),
    "agent": (
        (
            NotificationType.LEAD_ASSIGNED,
            "Lead accepted",
            "Your synthetic lead is being worked.",
            "/dashboard/leads",
        ),
        (
            NotificationType.AGENT_LEAD_EXPIRY_REMINDER,
            "Lead expiring soon",
            "A synthetic lead's protection ends soon.",
            "/dashboard/leads",
        ),
    ),
    "client": (
        (
            NotificationType.LOAN_STATUS_UPDATED,
            "Loan status updated",
            "Your synthetic application moved forward.",
            "/dashboard/loan-applications",
        ),
        (
            NotificationType.SITE_VISIT_REQUESTED,
            "Site visit update",
            "Your synthetic site visit was updated.",
            "/dashboard/site-visits",
        ),
    ),
}


async def _seed_support_and_notifications(db: AsyncSession, ctx: Ctx) -> None:
    authors = [*catalog.client_accounts()[:30], *catalog.accounts_by_role("agent")]
    combos = [(status, category) for status in SupportStatus for category in SupportCategory]
    for number, (status, category) in enumerate(combos):
        author = authors[(number * 7) % len(authors)]
        resolved = status in {SupportStatus.RESOLVED, SupportStatus.CLOSED}
        await add_once(
            db,
            SupportTicket(
                id=bulk_uuid(f"support:{number}"),
                auth_user_uuid=ctx.user(author.key).id,
                category=category,
                subject=f"Synthetic {category.value.replace('_', ' ')} request {number + 1}",
                body="Synthetic support request for development testing.",
                status=status,
                resolution_note="Synthetic resolution recorded by support." if resolved else None,
                created_at=ctx.now - timedelta(days=1 + number * 2),
            ),
        )

    recipients = [*catalog.staff_accounts(), *catalog.client_accounts()[:60]]
    for number, account in enumerate(recipients):
        for index, (kind, title, body, href) in enumerate(_ROLE_NOTIFICATIONS[account.role]):
            await add_once(
                db,
                Notification(
                    id=bulk_uuid(f"notification:{account.key}:{index}"),
                    user_uuid=ctx.user(account.key).id,
                    type=kind,
                    title=title,
                    body=body,
                    href=href,
                    created_at=ctx.now - timedelta(hours=2 + number % 48 + index * 5),
                ),
            )

    audits = (
        (AuditAction.STAFF_CREATED, "staff_profile", ctx.staff["subadmin-01"].id, None),
        (AuditAction.STAFF_FEATURE_GRANTED, "staff_profile", ctx.staff["subadmin-06"].id, None),
        (AuditAction.AGENT_APPROVED, "agent_profile", ctx.agents["agent-01"].id, "loans"),
        (
            AuditAction.AGENT_REJECTED,
            "agent_application",
            bulk_uuid("agent-application:agent-application-03"),
            "loans",
        ),
        (
            AuditAction.PROPERTY_SUBMISSION_APPROVED,
            "property_submission",
            bulk_uuid("property-submission:submission-04"),
            "real_estate",
        ),
        (
            AuditAction.PROPERTY_SUBMISSION_REJECTED,
            "property_submission",
            bulk_uuid("property-submission:submission-03"),
            "real_estate",
        ),
        (AuditAction.PAYOUT_APPROVED, "payout", bulk_uuid("payout:state:approved:1"), None),
        (AuditAction.PAYOUT_REJECTED, "payout", bulk_uuid("payout:state:rejected:2"), None),
        (
            AuditAction.ACCOUNT_STATUS_UPDATED,
            "staff_profile",
            ctx.staff["telecaller-08"].id,
            "loans",
        ),
    )
    for number, (action, entity_type, entity_uuid, line) in enumerate(audits):
        await add_once(
            db,
            AuditLog(
                id=bulk_uuid(f"audit:{number}"),
                actor_uuid=ctx.user("admin-01").id,
                actor_role="admin",
                action=action,
                entity_type=entity_type,
                entity_uuid=entity_uuid,
                business_line=line,
                detail={"synthetic": True, "source": SCRIPT},
                created_at=ctx.now - timedelta(hours=5 + number * 7),
            ),
        )


# ---------------------------------------------------------------------------
# Synthetic media (written directly at the services' canonical keys)
# ---------------------------------------------------------------------------


async def _seed_media(ctx: Ctx) -> dict[str, int]:
    """Gallery photos, 360 panoramas and private documents.

    Rows are written directly at the same canonical object keys the upload
    services produce (as ``seed_demo`` does for listing media). This keeps the
    run independent of the per-user presign rate limits and the malware
    scanner, while every generated file is a clean JPEG/PDF the validators
    accept. Banners, campaign artwork and videos are deliberately excluded.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.loan_document import LoanDocument
    from app.models.property_media import (
        MediaProcessingStatus,
        PropertyMedia,
        PropertyMediaKind,
        PropertySubmissionMedia,
    )
    from app.models.task import TaskDocument, TaskFeedbackMedia
    from app.scripts import demo_media
    from app.services.media_processing import validate_panorama_bytes

    counts = {
        "property_media": 0,
        "submission_media": 0,
        "loan_documents": 0,
        "task_documents": 0,
        "feedback_media": 0,
    }
    now = ctx.now

    async with AsyncSessionLocal() as db:
        for index, prop in enumerate(ctx.properties):
            items: list[tuple[str, PropertyMediaKind, bytes]] = [
                (
                    f"photo-{number + 1}",
                    PropertyMediaKind.IMAGE,
                    demo_media.property_photo(label=prop.title[:40], variant=number % 3),
                )
                for number in range(catalog.photo_count(index))
            ]
            if catalog.has_panorama(index):
                panorama = demo_media.panorama(label=prop.title[:30])
                validate_panorama_bytes(panorama, "image/jpeg")
                items.append(("panorama", PropertyMediaKind.PANORAMA, panorama))
            for position, (name, kind, content) in enumerate(items):
                media_id = bulk_uuid(f"property-media:{index}:{name}")
                if await db.get(PropertyMedia, media_id) is not None:
                    continue
                object_key = f"public/properties/{prop.id}/{media_id}/{name}.jpg"
                await put_once(object_key, content, "image/jpeg")
                db.add(
                    PropertyMedia(
                        id=media_id,
                        property_uuid=prop.id,
                        business_line="real_estate",
                        kind=kind,
                        content_type="image/jpeg",
                        object_key=object_key,
                        size_bytes=len(content),
                        position=position,
                        sanitized_at=now,
                    )
                )
                counts["property_media"] += 1
            await db.commit()

        for plan in catalog.submission_plans():
            submission_id = bulk_uuid(f"property-submission:{plan.key}")
            owner = ctx.user(plan.submitter_key).id
            items = [
                (
                    "photo-1",
                    PropertyMediaKind.IMAGE,
                    "image/jpeg",
                    demo_media.property_photo(label=plan.key, variant=0),
                ),
                (
                    "photo-2",
                    PropertyMediaKind.IMAGE,
                    "image/jpeg",
                    demo_media.property_photo(label=plan.key, variant=1),
                ),
                (
                    "document",
                    "document",
                    "application/pdf",
                    demo_media.document_pdf(
                        title="Ownership document",
                        lines=(plan.key, "Sale deed summary (synthetic)"),
                    ),
                ),
            ]
            if plan.index % 2 == 0:
                items.append(
                    (
                        "panorama",
                        PropertyMediaKind.PANORAMA,
                        "image/jpeg",
                        demo_media.panorama(label=plan.key),
                    )
                )
            for position, (name, kind, content_type, content) in enumerate(items):
                media_id = bulk_uuid(f"submission-media:{plan.key}:{name}")
                if await db.get(PropertySubmissionMedia, media_id) is not None:
                    continue
                extension = ".pdf" if content_type == "application/pdf" else ".jpg"
                object_key = (
                    f"private/property-submissions/canonical/{owner}/{media_id}/asset{extension}"
                )
                await put_once(object_key, content, content_type)
                db.add(
                    PropertySubmissionMedia(
                        id=media_id,
                        submission_uuid=submission_id,
                        business_line="real_estate",
                        kind=kind,
                        content_type=content_type,
                        object_key=object_key,
                        size_bytes=len(content),
                        position=position,
                        processing_status=MediaProcessingStatus.READY,
                        processed_at=now,
                        sanitized_at=now,
                    )
                )
                counts["submission_media"] += 1
            await db.commit()

        # Origin submissions keep the private intake copy a real approval leaves
        # behind: one photo plus the ownership PDF the reviewer checked.
        for index in catalog.listing_origin_indices():
            key = f"origin-{index}"
            submission_id = bulk_uuid(f"property-submission:{key}")
            owner = ctx.user(catalog.listing_origin_author(index)).id
            title = ctx.properties[index].title[:40]
            origin_items = (
                (
                    "photo-1",
                    PropertyMediaKind.IMAGE,
                    "image/jpeg",
                    demo_media.property_photo(label=title, variant=index % 3),
                ),
                (
                    "document",
                    PropertyMediaKind.DOCUMENT,
                    "application/pdf",
                    demo_media.document_pdf(
                        title="Ownership document",
                        lines=(title, "Sale deed summary (synthetic)"),
                    ),
                ),
            )
            for position, (name, kind, content_type, content) in enumerate(origin_items):
                media_id = bulk_uuid(f"submission-media:{key}:{name}")
                if await db.get(PropertySubmissionMedia, media_id) is not None:
                    continue
                extension = ".pdf" if content_type == "application/pdf" else ".jpg"
                object_key = (
                    f"private/property-submissions/canonical/{owner}/{media_id}/asset{extension}"
                )
                await put_once(object_key, content, content_type)
                db.add(
                    PropertySubmissionMedia(
                        id=media_id,
                        submission_uuid=submission_id,
                        business_line="real_estate",
                        kind=kind,
                        content_type=content_type,
                        object_key=object_key,
                        size_bytes=len(content),
                        position=position,
                        processing_status=MediaProcessingStatus.READY,
                        processed_at=now,
                        sanitized_at=now,
                    )
                )
                counts["submission_media"] += 1
            await db.commit()

        loan_items = (
            ("salary_slip", "application/pdf"),
            ("bank_statement", "application/pdf"),
            ("photo", "image/jpeg"),
        )
        for position, (key, application) in enumerate(sorted(ctx.current_loans.items())):
            if position % 5 in {3, 4}:
                continue  # some applications intentionally have no documents
            account = catalog.account(key.split(":")[0])
            for item_number, (doc_type, content_type) in enumerate(loan_items[: 1 + position % 3]):
                media_id = bulk_uuid(f"loan-document:{key}:{doc_type}")
                if await db.get(LoanDocument, media_id) is not None:
                    continue
                content = (
                    demo_media.document_pdf(
                        title=doc_type.replace("_", " ").title(),
                        lines=(
                            f"{account.first_name} {account.last_name}",
                            "Synthetic figures only",
                        ),
                    )
                    if content_type == "application/pdf"
                    else demo_media.property_photo(
                        label="Applicant photo", line="loans", variant=item_number
                    )
                )
                extension = ".pdf" if content_type == "application/pdf" else ".jpg"
                object_key = (
                    f"private/loan-applications/canonical/{application.client_profile_uuid}/"
                    f"{application.id}/{media_id}/asset{extension}"
                )
                await put_once(object_key, content, content_type)
                verified = position % 4 == 0
                db.add(
                    LoanDocument(
                        id=media_id,
                        loan_application_uuid=application.id,
                        client_profile_uuid=application.client_profile_uuid,
                        business_line="loans",
                        doc_type=doc_type,
                        object_key=object_key,
                        content_type=content_type,
                        size_bytes=len(content),
                        uploaded_by_uuid=ctx.user(account.key).id,
                        verified=verified,
                        verified_by_profile_uuid=ctx.staff["admin-01"].id if verified else None,
                        verified_at=now - timedelta(days=1) if verified else None,
                        review_note="Synthetic note: please upload a clearer copy."
                        if position % 4 == 1
                        else None,
                        processing_status=MediaProcessingStatus.READY,
                        processed_at=now,
                        sanitized_at=now,
                    )
                )
                counts["loan_documents"] += 1
            await db.commit()

        active_task_states = {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.BLOCKED}
        for position, task in enumerate(ctx.tasks):
            if task.status not in active_task_states or task.assigned_employee_profile_uuid is None:
                continue
            employee = await db.get(StaffProfile, task.assigned_employee_profile_uuid)
            if task.task_type == TaskType.PROPERTY_VISIT:
                media_id = bulk_uuid(f"feedback-media:{task.id}")
                if await db.get(TaskFeedbackMedia, media_id) is not None:
                    continue
                content = demo_media.property_photo(label="Site visit photo", variant=position % 3)
                object_key = f"private/task-feedback/canonical/{task.id}/{media_id}/asset.jpg"
                await put_once(object_key, content, "image/jpeg")
                db.add(
                    TaskFeedbackMedia(
                        id=media_id,
                        task_uuid=task.id,
                        business_line=task.business_line,
                        kind="image",
                        content_type="image/jpeg",
                        object_key=object_key,
                        size_bytes=len(content),
                        uploaded_by_uuid=employee.auth_user_uuid,
                        sanitized_at=now,
                    )
                )
                counts["feedback_media"] += 1
            elif task.task_type == TaskType.DOCUMENT_COLLECTION:
                doc_type = ("salary_slip", "bank_statement", "sale_deed")[position % 3]
                document_id = bulk_uuid(f"task-document:{task.id}")
                if await db.get(TaskDocument, document_id) is not None:
                    continue
                content = demo_media.document_pdf(
                    title=doc_type.replace("_", " ").title(),
                    lines=("Collected in the field", "Synthetic figures only"),
                )
                object_key = f"tasks/{task.id}/confirmed/{document_id}-{doc_type}"
                await put_once(object_key, content, "application/pdf")
                verified = task.status == TaskStatus.COMPLETED
                db.add(
                    TaskDocument(
                        id=document_id,
                        task_uuid=task.id,
                        doc_type=doc_type,
                        object_key=object_key,
                        verified=verified,
                        verified_by_profile_uuid=ctx.staff["admin-01"].id if verified else None,
                        verified_at=now - timedelta(hours=6) if verified else None,
                    )
                )
                counts["task_documents"] += 1
        await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def seed_bulk(*, include_media: bool = True) -> dict[str, int]:
    require_development(SCRIPT)
    from app.db.session import AsyncSessionLocal

    ctx = Ctx(now=datetime.now(UTC))
    async with AsyncSessionLocal() as db:
        await _seed_users(db, ctx)
        await _seed_profiles(db, ctx)
        await _seed_teams(db, ctx)
        await _seed_referral_codes(db, ctx)
        await db.commit()
        print(f"[{SCRIPT}] accounts, profiles and teams ready", flush=True)

        await _seed_properties(db, ctx)
        await db.commit()
        print(f"[{SCRIPT}] listings and submissions ready", flush=True)

        await _seed_leads(db, ctx)
        await _seed_loans(db, ctx)
        await db.commit()
        print(f"[{SCRIPT}] leads and loan journeys ready", flush=True)

        await _seed_real_estate(db, ctx)
        await _seed_tasks(db, ctx)
        await db.commit()
        print(f"[{SCRIPT}] property journeys and tasks ready", flush=True)

        await _seed_money(db, ctx)
        await _seed_support_and_notifications(db, ctx)
        await db.commit()
        print(f"[{SCRIPT}] payouts, referrals, tickets and notifications ready", flush=True)

    media = await _seed_media(ctx) if include_media else {}
    async with AsyncSessionLocal() as db:
        summary = {
            "accounts": len(catalog.all_accounts()),
            "client_profiles": len(ctx.clients),
            "properties": len(ctx.properties),
            "leads": len(ctx.leads),
            "loan_applications": int(
                await db.scalar(
                    select(func.count())
                    .select_from(LoanApplication)
                    .where(
                        LoanApplication.client_profile_uuid.in_(
                            [p.id for p in ctx.clients.values()]
                        )
                    )
                )
                or 0
            ),
            "deals": len(ctx.deals),
            "tasks": len(ctx.tasks),
        }
    summary.update({f"new_{key}": value for key, value in media.items()})
    return summary


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

VERIFY_ACCOUNTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("admin-01", ("/api/v1/admin/home",)),
    ("subadmin-01", ("/api/v1/sub-admin/home", "/api/v1/manager/teams")),
    ("subadmin-06", ("/api/v1/sub-admin/home",)),
    ("telecaller-01", ("/api/v1/telecaller/home",)),
    ("telecaller-09", ("/api/v1/telecaller/home",)),
    ("employee-01", ("/api/v1/employee/home",)),
    ("employee-09", ("/api/v1/employee/home",)),
    ("agent-01", ("/api/v1/agent/home",)),
    ("agent-09", ("/api/v1/agent/home",)),
    ("client-001", ("/api/v1/loans/applications",)),
    ("client-087", ("/api/v1/site-visits",)),
    ("client-172", ("/api/v1/loans/applications", "/api/v1/site-visits")),
)


def _has_data(endpoint: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if endpoint.endswith("/loans/applications"):
        return bool(payload.get("applications"))
    if endpoint.endswith("/site-visits"):
        return bool(payload.get("visits"))
    if endpoint.endswith("/manager/teams"):
        return bool(payload.get("teams"))
    return any(
        (isinstance(value, int) and not isinstance(value, bool) and value > 0)
        or (isinstance(value, list | dict) and value)
        for value in payload.values()
    )


async def verify_bulk_api(base_url: str) -> dict[str, str]:
    """Log in a representative account per role and check its primary APIs."""
    import httpx

    verified: dict[str, str] = {}
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30) as client:
        for key, endpoints in VERIFY_ACCOUNTS:
            account: BulkAccount = catalog.account(key)
            login = await client.post(
                "/api/v1/auth/login",
                json={"mobile": account.mobile, "password": catalog.BULK_PASSWORD},
            )
            if login.status_code != 200:
                raise RuntimeError(f"Bulk login failed for {key}: HTTP {login.status_code}.")
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            for endpoint in endpoints:
                response = await client.get(endpoint, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Bulk API check failed for {key} at {endpoint}: "
                        f"HTTP {response.status_code}."
                    )
                if not _has_data(endpoint, response.json()):
                    raise RuntimeError(f"Bulk API check returned no data for {key} at {endpoint}.")
            verified[key] = account.role
    return verified


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--credentials", action="store_true", help="Print the roster without writing data."
    )
    parser.add_argument(
        "--skip-media", action="store_true", help="Write database rows only, no object storage."
    )
    parser.add_argument(
        "--verify", action="store_true", help="After seeding, log in sample accounts per role."
    )
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000",
        help="API origin used by --verify (default: http://localhost:8000).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    require_development(SCRIPT)
    if args.credentials:
        print(catalog.credentials_table())
        return

    async def run() -> tuple[dict[str, int], dict[str, str] | None]:
        summary = await seed_bulk(include_media=not args.skip_media)
        verified = await verify_bulk_api(args.api_base_url) if args.verify else None
        return summary, verified

    summary, verified = asyncio.run(run())
    print(f"[{SCRIPT}] Ready: {summary}")
    if verified is not None:
        print(f"[{SCRIPT}] Verified logins and role APIs: {verified}")
    print(catalog.credentials_table())


if __name__ == "__main__":
    main()
