"""Shared seeding and session helpers for the CS-027 contest tests."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.db.session as db_session
from app.core.config import settings
from app.core.security import create_access_token
from app.models.contest import Contest
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.lead_activity import CallDisposition, LeadActivity
from app.models.loan import Bank, LoanApplication, LoanStatus, LoanType
from app.models.profile import (
    AgentProfile,
    ClientProfile,
    ProfileScope,
    ProfileStatus,
    StaffProfile,
    StaffRole,
)
from app.models.property import Property, PropertyCategory, PropertySubtype
from app.models.property_deal import PropertyDeal, PropertyDealStatus
from app.models.staff_team import StaffTeam, StaffTeamMember
from app.models.user import User
from app.services.contests import today_ist
from conftest import unique_mobile


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def seed_user(first_name: str = "Test", last_name: str = "User") -> User:
    async with db_session.AsyncSessionLocal() as db:
        user = User(
            first_name=first_name,
            last_name=last_name,
            mobile=unique_mobile(),
            email=f"contest_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.commit()
        return user


async def seed_staff(
    role: StaffRole,
    *,
    business_line: str | None = None,
    first_name: str = "Staff",
    created_at: datetime | None = None,
) -> tuple[User, StaffProfile]:
    user = await seed_user(first_name, role.value.title())
    async with db_session.AsyncSessionLocal() as db:
        platform = role in (StaffRole.ADMIN, StaffRole.SUB_ADMIN)
        profile = StaffProfile(
            auth_user_uuid=user.id,
            role=role,
            scope=ProfileScope.PLATFORM if platform else ProfileScope.LINE,
            business_line=None if platform else business_line,
            staff_code=f"CT-{uuid.uuid4().hex[:10]}",
            status=ProfileStatus.ACTIVE,
        )
        if created_at is not None:
            profile.created_at = created_at
        db.add(profile)
        await db.commit()
        return user, profile


async def main_admin_token() -> str:
    """Authenticate the single Main Admin already provisioned in the test database."""
    async with db_session.AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(User, StaffProfile)
                .join(StaffProfile, StaffProfile.auth_user_uuid == User.id)
                .where(StaffProfile.is_primary_admin.is_(True))
            )
        ).one_or_none()
    if existing is None:
        user, profile = await seed_staff(StaffRole.ADMIN)
        async with db_session.AsyncSessionLocal() as db:
            stored = await db.get(StaffProfile, profile.id)
            assert stored is not None
            stored.is_primary_admin = True
            await db.commit()
    else:
        user, profile = existing
    return create_access_token(
        {
            "sub": str(user.id),
            "role": "admin",
            "staff_profile_uuid": str(profile.id),
            "platform_scope": "true",
            "business_line": "both",
            "session_version": user.session_version,
        }
    )


async def seed_agent(
    business_line: str = "loans",
    *,
    first_name: str = "Agent",
    kyc_status: str | None = "verified",
    created_at: datetime | None = None,
) -> tuple[User, AgentProfile]:
    user = await seed_user(first_name, "Agent")
    async with db_session.AsyncSessionLocal() as db:
        profile = AgentProfile(
            auth_user_uuid=user.id,
            agent_code=f"AG-{uuid.uuid4().hex[:10]}",
            business_line=business_line,
            status=ProfileStatus.ACTIVE,
            kyc_status=kyc_status,
        )
        if created_at is not None:
            profile.created_at = created_at
        db.add(profile)
        await db.commit()
        return user, profile


def token_for(
    user: User,
    role: str,
    *,
    business_line: str = "",
    platform_scope: str = "line",
    agent_profile: AgentProfile | None = None,
    staff_profile: StaffProfile | None = None,
) -> str:
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "role": role,
        "business_line": business_line,
        "platform_scope": platform_scope,
    }
    if agent_profile is not None:
        claims["agent_profile_uuid"] = str(agent_profile.id)
    if staff_profile is not None:
        claims["staff_profile_uuid"] = str(staff_profile.id)
    return create_access_token(claims)


async def sub_admin_token() -> tuple[str, User, StaffProfile]:
    user, profile = await seed_staff(StaffRole.SUB_ADMIN, first_name="Maker")
    return (
        token_for(user, "sub_admin", platform_scope="true", staff_profile=profile),
        user,
        profile,
    )


async def admin_token() -> tuple[str, User]:
    user, profile = await seed_staff(StaffRole.ADMIN, first_name="Checker")
    return token_for(user, "admin", platform_scope="true", staff_profile=profile), user


def definition(**overrides: Any) -> dict[str, Any]:
    """A valid Agent loans contest starting tomorrow (IST)."""
    start = today_ist() + timedelta(days=1)
    body: dict[str, Any] = {
        "title": "Personal loan sprint",
        "description": "Disburse personal loans this month.",
        "terms": "Prizes are paid after the end date.",
        "business_line": "loans",
        "audience": "agent",
        "metric": "amount",
        "criteria": {
            "version": 1,
            "loans": {
                "counted_stage": "disbursed",
                "count_at_least": 1,
                "count_at_most": 5,
                "amount_at_least_paise": 5_000_000_00,
            },
        },
        "win_mode": "threshold",
        "prize_paise": 10_000_00,
        "starts_on": start.isoformat(),
        "ends_on": (start + timedelta(days=29)).isoformat(),
    }
    body.update(overrides)
    return body


async def seed_contest(
    *,
    created_by: User,
    status: str = "live",
    checker: User | None = None,
    starts_on: date | None = None,
    ends_on: date | None = None,
    **fields: Any,
) -> Contest:
    """Insert a contest directly (bypass session), defaulting to a live
    Agent loans threshold contest over the last ten IST days."""
    today = today_ist()
    values: dict[str, Any] = {
        "title": "Seeded contest",
        "business_line": "loans",
        "audience": "agent",
        "metric": "cases",
        "criteria": {"version": 1, "loans": {"counted_stage": "disbursed", "count_at_least": 1}},
        "win_mode": "threshold",
        "prize_paise": 1_000_00,
        "starts_on": starts_on or today - timedelta(days=9),
        "ends_on": ends_on or today,
    }
    values.update(fields)
    reviewed = status in ("approved", "live", "ended", "finalized", "rejected")
    if reviewed and checker is None:
        checker = await seed_user("Seed", "Checker")
    async with db_session.AsyncSessionLocal() as db:
        contest = Contest(
            **values,
            status=status,
            created_by_uuid=created_by.id,
            checker_uuid=checker.id if reviewed and checker else None,
            reviewed_at=datetime.now(UTC) if reviewed else None,
        )
        db.add(contest)
        await db.commit()
        return contest


async def seed_lead(
    business_line: str,
    *,
    agent: AgentProfile | None = None,
    telecaller: StaffProfile | None = None,
) -> Lead:
    async with db_session.AsyncSessionLocal() as db:
        lead = Lead(
            name="Contest Lead",
            mobile=unique_mobile(),
            business_line=business_line,
            status=LeadStatus.WORKING if telecaller else LeadStatus.NEW,
            origin=LeadOrigin.AGENT if agent else LeadOrigin.DIRECT,
            origin_agent_profile_uuid=agent.id if agent else None,
            assigned_telecaller_profile_uuid=telecaller.id if telecaller else None,
        )
        db.add(lead)
        await db.commit()
        return lead


async def seed_call(
    telecaller: StaffProfile,
    lead: Lead,
    *,
    at: datetime,
    connected: bool = True,
    follow_up_at: datetime | None = None,
) -> None:
    """A call the Telecaller logged on the lead at ``at``."""
    async with db_session.AsyncSessionLocal() as db:
        db.add(
            LeadActivity(
                lead_uuid=lead.id,
                telecaller_staff_profile_uuid=telecaller.id,
                business_line=lead.business_line,
                disposition=CallDisposition.CONNECTED if connected else CallDisposition.NO_ANSWER,
                follow_up_at=follow_up_at,
                created_at=at,
            )
        )
        await db.commit()


async def seed_client_profile(business_line: str) -> ClientProfile:
    user = await seed_user("Contest", "Client")
    async with db_session.AsyncSessionLocal() as db:
        profile = ClientProfile(
            auth_user_uuid=user.id,
            business_line=business_line,
            customer_code=f"CL{uuid.uuid4().hex[:10]}",
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        return profile


async def seed_loan_type(label: str = "Personal loan") -> LoanType:
    async with db_session.AsyncSessionLocal() as db:
        loan_type = LoanType(name=f"ct_{uuid.uuid4().hex[:10]}", label=label)
        db.add(loan_type)
        await db.commit()
        return loan_type


async def seed_bank(name: str = "Contest Bank") -> Bank:
    async with db_session.AsyncSessionLocal() as db:
        bank = Bank(name=f"{name} {uuid.uuid4().hex[:6]}")
        db.add(bank)
        await db.commit()
        return bank


async def seed_loan(
    lead: Lead,
    *,
    loan_type: LoanType,
    status: LoanStatus = LoanStatus.DISBURSED,
    requested: int = 1_000_000,
    sanctioned: int | None = 1_000_000,
    bank: Bank | None = None,
    at: datetime | None = None,
) -> LoanApplication:
    """A loan case that reached ``status`` at ``at`` (stage markers set as the
    progress service would). Amounts are rupees."""
    when = at or datetime.now(UTC)
    client_profile = await seed_client_profile("loans")
    order = [
        LoanStatus.SUBMITTED_TO_BANK,
        LoanStatus.UNDER_REVIEW,
        LoanStatus.SANCTIONED,
        LoanStatus.AGREEMENT_COLLECTED,
        LoanStatus.AGREEMENT_SUBMITTED_TO_BANK,
        LoanStatus.DISBURSED,
    ]
    reached = order.index(status) if status in order else -1
    async with db_session.AsyncSessionLocal() as db:
        loan = LoanApplication(
            lead_uuid=lead.id,
            client_profile_uuid=client_profile.id,
            business_line="loans",
            loan_type_id=loan_type.id,
            bank_id=bank.id if bank else None,
            amount_requested=Decimal(requested),
            amount_sanctioned=Decimal(sanctioned) if sanctioned is not None else None,
            status=status,
            opened_at=when - timedelta(days=1),
            submitted_at=when if reached >= 0 else None,
            sanctioned_at=when if reached >= 2 else None,
            disbursed_at=when if status == LoanStatus.DISBURSED else None,
        )
        db.add(loan)
        await db.commit()
        return loan


async def seed_property(
    *,
    category: PropertyCategory = PropertyCategory.APARTMENTS,
    subtype: PropertySubtype | None = PropertySubtype.GATED_COMMUNITY_APARTMENT,
    city: str = "Hyderabad",
    intent: str = "sale",
    price_paise: int = 75_00_000_00,
) -> Property:
    async with db_session.AsyncSessionLocal() as db:
        prop = Property(
            business_line="real_estate",
            listing_intent=intent,
            title="Contest Residency",
            type="Apartment",
            location=f"Madhapur, {city}",
            price_display="₹75 L",
            category=category,
            property_subtype=subtype,
            city=city,
            locality="Madhapur",
            pincode="500081",
            price_paise=price_paise,
            bhk=2,
            area_sqft=1200,
        )
        db.add(prop)
        await db.commit()
        return prop


async def seed_deal(
    lead: Lead,
    prop: Property,
    *,
    status: PropertyDealStatus = PropertyDealStatus.CLOSED,
    price_quoted: int | None = 7_000_000,
    at: datetime | None = None,
) -> PropertyDeal:
    when = at or datetime.now(UTC)
    client_profile = await seed_client_profile("real_estate")
    order = [
        PropertyDealStatus.SITE_VISIT_DONE,
        PropertyDealStatus.NEGOTIATION,
        PropertyDealStatus.BOOKED,
        PropertyDealStatus.AGREEMENT_SIGNED,
        PropertyDealStatus.CLOSED,
    ]
    reached = order.index(status) if status in order else -1
    async with db_session.AsyncSessionLocal() as db:
        deal = PropertyDeal(
            lead_uuid=lead.id,
            client_profile_uuid=client_profile.id,
            property_id=prop.id,
            business_line="real_estate",
            price_quoted=Decimal(price_quoted) if price_quoted is not None else None,
            status=status,
            opened_at=when - timedelta(days=1),
            site_visit_done_at=when if reached >= 0 else None,
            booked_at=when if reached >= 2 else None,
            agreement_signed_at=when if reached >= 3 else None,
            closed_at=when if status == PropertyDealStatus.CLOSED else None,
        )
        db.add(deal)
        await db.commit()
        return deal


async def seed_team(
    manager: StaffProfile, business_line: str, member_role: str, members: list[StaffProfile]
) -> StaffTeam:
    async with db_session.AsyncSessionLocal() as db:
        team = StaffTeam(
            name=f"Team {uuid.uuid4().hex[:6]}",
            business_line=business_line,
            member_role=member_role,
            manager_staff_profile_uuid=manager.id,
        )
        db.add(team)
        await db.flush()
        for member in members:
            db.add(
                StaffTeamMember(
                    team_uuid=team.id,
                    staff_profile_uuid=member.id,
                    business_line=business_line,
                )
            )
        await db.commit()
        return team


def rls_engine():
    url = settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432")
    return create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )


async def as_role(
    sql: str,
    *,
    user_uuid: uuid.UUID | str,
    role: str,
    business_line: str = "",
    platform_scope: str = "false",
    agent_profile_uuid: uuid.UUID | str | None = None,
    staff_profile_uuid: uuid.UUID | str | None = None,
    params: dict[str, Any] | None = None,
) -> list[Any]:
    """Run ``sql`` as api_user with an RLS context and return its rows."""
    engine = rls_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(
                text(
                    "SELECT "
                    "set_config('app.auth_user_uuid', :uuid, true),"
                    "set_config('app.role', :role, true),"
                    "set_config('app.business_line', :bl, true),"
                    "set_config('app.client_profile_uuid', '', true),"
                    "set_config('app.agent_profile_uuid', :agent, true),"
                    "set_config('app.staff_profile_uuid', :staff, true),"
                    "set_config('app.platform_scope', :ps, true)"
                ),
                {
                    "uuid": str(user_uuid),
                    "role": role,
                    "bl": business_line,
                    "agent": str(agent_profile_uuid or ""),
                    "staff": str(staff_profile_uuid or ""),
                    "ps": platform_scope,
                },
            )
            result = await conn.execute(text(sql), params or {})
            return list(result.fetchall()) if result.returns_rows else []
    finally:
        await engine.dispose()
