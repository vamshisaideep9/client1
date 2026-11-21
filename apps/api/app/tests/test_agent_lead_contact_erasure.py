"""CS-028: account deletion erases lead email without erasing others' contacts."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

import app.db.session as db_session
from app.models.lead import Lead, LeadStatus
from app.models.profile import AgentProfile, ProfileStatus, StaffRole
from app.models.user import User
from app.tests.contest_support import as_role, headers, seed_staff, seed_user, token_for
from conftest import PASSWORD, full_registration, unique_mobile


@pytest.mark.asyncio
@pytest.mark.parametrize("by_admin", [False, True])
async def test_account_deletion_erases_own_lead_emails_only(
    client: AsyncClient, by_admin: bool
) -> None:
    token, mobile = await full_registration(client, lines=["loans"])
    _, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    async with db_session.AsyncSessionLocal() as db:
        target = await db.scalar(select(User).where(User.mobile == mobile))
        lead = await db.scalar(
            select(Lead).where(Lead.mobile == mobile, Lead.status != LeadStatus.CLOSED)
        )
        assert target is not None and lead is not None
        target_uuid, lead_uuid = target.id, lead.id
        client_uuid = lead.client_profile_uuid
        lead.assigned_telecaller_profile_uuid = telecaller.id
        lead.status = LeadStatus.ASSIGNED
        lead.requirement = {"email": "delete-me@example.com", "notes": "Keep workflow history"}
        agent = AgentProfile(
            auth_user_uuid=target_uuid,
            agent_code=f"AG-{uuid.uuid4().hex[:8]}",
            business_line="loans",
            status=ProfileStatus.ACTIVE,
        )
        db.add(agent)
        await db.flush()
        historical = Lead(
            mobile=mobile,
            business_line="real_estate",
            status=LeadStatus.CLOSED,
            requirement={"email": "old-contact@example.com"},
        )
        # A bound journey may retain a different old mobile after contact changes.
        bound = Lead(
            mobile=unique_mobile(),
            client_profile_uuid=client_uuid,
            business_line="loans",
            status=LeadStatus.CLOSED,
            requirement={"email": "bound-contact@example.com"},
        )
        prospect = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            origin="agent",
            origin_agent_profile_uuid=agent.id,
            requirement={"email": "another-person@example.com"},
        )
        db.add_all([historical, bound, prospect])
        await db.commit()
        historical_uuid, bound_uuid, prospect_uuid = historical.id, bound.id, prospect.id

    if by_admin:
        admin_user, admin = await seed_staff(StaffRole.ADMIN)
        response = await client.post(
            f"/api/v1/admin/users/{target_uuid}/delete",
            json={"reason": "Test account removal"},
            headers=headers(
                token_for(admin_user, "admin", platform_scope="true", staff_profile=admin)
            ),
        )
    else:
        response = await client.request(
            "DELETE",
            "/api/v1/auth/me",
            headers=headers(token),
            json={"current_password": PASSWORD},
        )
    assert response.status_code == 200, response.text
    async with db_session.AsyncSessionLocal() as db:
        lead = await db.get(Lead, lead_uuid)
        assert lead.status == LeadStatus.CLOSED
        assert lead.assigned_telecaller_profile_uuid is None
        assert lead.requirement == {"notes": "Keep workflow history"}
        assert lead.last_telecaller_profile_uuid == telecaller.id
        for row_uuid in (historical_uuid, bound_uuid):
            assert (await db.get(Lead, row_uuid)).requirement == {}
        assert (await db.get(Lead, prospect_uuid)).requirement == {
            "email": "another-person@example.com"
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,scope", [("client", "false"), ("admin", "line"), ("sub_admin", "true"), ("", "")]
)
async def test_lead_contact_erasure_refuses_another_accounts_caller(
    client: AsyncClient, role: str, scope: str
) -> None:
    target = await seed_user("Target", "Client")
    caller = await seed_user("Other", "Caller")
    with pytest.raises(DBAPIError, match="lead closure is not authorized"):
        await as_role(
            "SELECT close_account_leads(:target)",
            params={"target": target.id},
            user_uuid=caller.id,
            role=role,
            platform_scope=scope,
        )
