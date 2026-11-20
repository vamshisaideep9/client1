"""Batch 2 (CS-028): a resubmitted lead goes back to its last Telecaller.

Every path that clears a lead's Telecaller assignment (the expiry job, the
retry job's stale-assignee repair, an Admin release) records the cleared
assignee in ``leads.last_telecaller_profile_uuid``. When the originating Agent
resubmits an expired lead that is still unassigned, it goes straight back to
that Telecaller if they are still an active Telecaller on the lead's line (or
both lines), without touching the round-robin cursor; otherwise round-robin
assignment applies as before. ``resubmit_count`` / ``last_resubmitted_at``
are exposed on the Agent, Telecaller and Admin lead reads.

The trigger ``trg_leads_last_telecaller_guard`` keeps both columns honest for
every session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

import app.db.session as db_session
from app.jobs.assign_unassigned_leads import _assign_batch
from app.jobs.expire_agent_leads import expire_agent_leads
from app.models.audit_log import AuditAction, AuditLog
from app.models.lead import Lead, LeadAssignmentCursor, LeadOrigin, LeadStatus
from app.models.notification import Notification, NotificationType
from app.models.profile import AgentProfile, ProfileStatus, StaffProfile, StaffRole
from app.services.leads import (
    auto_assign_locked_lead,
    release_lead_from_telecaller,
    sticky_assign_locked_lead,
)
from app.tests.contest_support import headers, seed_staff, token_for
from app.tests.test_agent_api import _agent_token
from app.tests.test_lead_auto_assignment import (  # noqa: F401 — autouse fixture
    _isolate_eligible_telecallers,
    _seed_agent,
    _seed_telecaller,
)
from conftest import unique_mobile

pytestmark = pytest.mark.asyncio


async def _assigned_agent_lead(agent: AgentProfile, telecaller: StaffProfile, **fields) -> Lead:
    """An Agent lead held by ``telecaller``, by default past its window."""
    fields.setdefault("expires_at", datetime.now(UTC) - timedelta(minutes=1))
    async with db_session.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            name="Sticky Client",
            business_line="loans",
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=agent.id,
            status=LeadStatus.ASSIGNED,
            assigned_telecaller_profile_uuid=telecaller.id,
            **fields,
        )
        db.add(lead)
        await db.commit()
        return lead


async def _load(lead_id: uuid.UUID) -> Lead:
    async with db_session.AsyncSessionLocal() as db:
        lead = await db.get(Lead, lead_id)
        assert lead is not None
        return lead


async def _set_cursor(telecaller_id: uuid.UUID | None) -> None:
    async with db_session.AsyncSessionLocal() as db:
        cursor = await db.get(LeadAssignmentCursor, "loans")
        if cursor is None:
            db.add(
                LeadAssignmentCursor(
                    business_line="loans", last_telecaller_profile_uuid=telecaller_id
                )
            )
        else:
            cursor.last_telecaller_profile_uuid = telecaller_id
        await db.commit()


async def _cursor() -> uuid.UUID | None:
    async with db_session.AsyncSessionLocal() as db:
        cursor = await db.get(LeadAssignmentCursor, "loans")
        return cursor.last_telecaller_profile_uuid if cursor else None


async def _assignment_modes(lead_id: uuid.UUID) -> list[str]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_uuid == lead_id, AuditLog.action == AuditAction.LEAD_ASSIGNED)
            .order_by(AuditLog.created_at)
        )
        return [row.detail["mode"] for row in rows]


async def _resubmit(client: AsyncClient, agent: AgentProfile, lead_id: uuid.UUID):  # noqa: ANN202
    token = _agent_token(str(agent.auth_user_uuid), str(agent.id))
    return await client.post(
        f"/api/v1/agent/leads/{lead_id}/resubmit",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_resubmitted_lead_returns_to_its_last_telecaller(client: AsyncClient) -> None:
    first = await _seed_telecaller("loans")
    second = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(agent, first)

    await expire_agent_leads()
    expired = await _load(lead.id)
    assert expired.assigned_telecaller_profile_uuid is None
    assert expired.status == LeadStatus.RELEASED
    assert expired.agent_expired_at is not None
    assert expired.last_telecaller_profile_uuid == first.id

    # Round robin would hand the next lead to ``second``.
    await _set_cursor(first.id)
    started = datetime.now(UTC)
    res = await _resubmit(client, agent, lead.id)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["resubmit_count"] == 1
    assert datetime.fromisoformat(body["last_resubmitted_at"]) >= started

    refreshed = await _load(lead.id)
    assert refreshed.assigned_telecaller_profile_uuid == first.id
    assert refreshed.status == LeadStatus.ASSIGNED
    assert refreshed.resubmit_count == 1
    assert refreshed.last_resubmitted_at is not None
    # The cursor is not advanced by a sticky return.
    assert await _cursor() == first.id
    assert (await _assignment_modes(lead.id))[-1] == "sticky_resubmit"

    async with db_session.AsyncSessionLocal() as db:
        notified = await db.scalar(
            select(Notification).where(
                Notification.user_uuid == first.auth_user_uuid,
                Notification.type == NotificationType.LEAD_ASSIGNED,
                Notification.created_at >= started,
            )
        )
    assert notified is not None
    assert second.id != first.id


async def test_resubmit_falls_back_when_the_last_telecaller_is_inactive(
    client: AsyncClient,
) -> None:
    first = await _seed_telecaller("loans")
    second = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(agent, first)
    await expire_agent_leads()
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == first.id)
            .values(status=ProfileStatus.INACTIVE)
        )
        await db.commit()
    await _set_cursor(first.id)

    res = await _resubmit(client, agent, lead.id)
    assert res.status_code == 200, res.text
    refreshed = await _load(lead.id)
    assert refreshed.assigned_telecaller_profile_uuid == second.id
    assert await _cursor() == second.id
    assert (await _assignment_modes(lead.id))[-1] == "automatic"


async def test_resubmit_falls_back_when_the_last_telecaller_was_deleted(
    client: AsyncClient,
) -> None:
    first = await _seed_telecaller("loans")
    second = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(agent, first)
    await expire_agent_leads()
    await _set_cursor(None)
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(delete(StaffProfile).where(StaffProfile.id == first.id))
        await db.commit()
    # ON DELETE SET NULL cleared the memory.
    assert (await _load(lead.id)).last_telecaller_profile_uuid is None

    res = await _resubmit(client, agent, lead.id)
    assert res.status_code == 200, res.text
    assert (await _load(lead.id)).assigned_telecaller_profile_uuid == second.id


async def test_sticky_return_requires_the_lead_line_or_both() -> None:
    """Off-line Telecallers never qualify; dual-line Telecallers do."""
    real_estate = await _seed_telecaller("real_estate")
    _user, dual = await seed_staff(StaffRole.TELECALLER, business_line="both")
    async with db_session.AsyncSessionLocal() as db:
        transient = Lead(
            id=uuid.uuid4(),
            mobile=unique_mobile(),
            business_line="loans",
            status=LeadStatus.RELEASED,
            last_telecaller_profile_uuid=real_estate.id,
        )
        assert await sticky_assign_locked_lead(db, transient) is None
        assert transient.assigned_telecaller_profile_uuid is None

        transient.last_telecaller_profile_uuid = dual.id
        notice = await sticky_assign_locked_lead(db, transient)
        assert notice is not None
        assert transient.assigned_telecaller_profile_uuid == dual.id
        assert transient.status == LeadStatus.ASSIGNED
        await db.rollback()

        # Never for an already-assigned or terminal lead.
        for lead in (
            Lead(
                id=uuid.uuid4(),
                business_line="loans",
                status=LeadStatus.ASSIGNED,
                assigned_telecaller_profile_uuid=real_estate.id,
                last_telecaller_profile_uuid=dual.id,
            ),
            Lead(
                id=uuid.uuid4(),
                business_line="loans",
                status=LeadStatus.CONVERTED,
                last_telecaller_profile_uuid=dual.id,
            ),
        ):
            assert await sticky_assign_locked_lead(db, lead) is None


async def test_a_lead_the_pool_already_reassigned_keeps_its_telecaller(
    client: AsyncClient,
) -> None:
    """Expiry returns the lead to the open pool (FR-4.6); the retry job may
    give it to someone else before the Agent resubmits. Resubmission then
    leaves that current assignment alone, as before CS-028."""
    first = await _seed_telecaller("loans")
    second = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(agent, first)
    await expire_agent_leads()
    await _set_cursor(first.id)
    # What the retry job does to an open-pool lead (same function, same lock).
    async with db_session.AsyncSessionLocal() as db:
        locked = await db.scalar(select(Lead).where(Lead.id == lead.id).with_for_update())
        assert await auto_assign_locked_lead(db, locked) is not None
        await db.commit()
    assert (await _load(lead.id)).assigned_telecaller_profile_uuid == second.id

    res = await _resubmit(client, agent, lead.id)
    assert res.status_code == 200, res.text
    refreshed = await _load(lead.id)
    assert refreshed.assigned_telecaller_profile_uuid == second.id
    assert refreshed.last_telecaller_profile_uuid == first.id


async def test_admin_release_records_the_cleared_telecaller() -> None:
    first = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    async with db_session.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            business_line="loans",
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=agent.id,
            status=LeadStatus.WORKING,
            assigned_telecaller_profile_uuid=first.id,
            expires_at=datetime.now(UTC) + timedelta(days=10),
        )
        db.add(lead)
        await db.commit()
    async with db_session.AsyncSessionLocal() as db:
        released, previous = await release_lead_from_telecaller(
            db,
            lead.id,
            telecaller_staff_profile_uuid=None,
            release_reason="Customer asked for another caller.",
            actor_uuid=uuid.uuid4(),
            actor_role="admin",
        )
    assert previous == first.id
    assert released.assigned_telecaller_profile_uuid is None
    assert released.last_telecaller_profile_uuid == first.id


async def test_stale_assignee_repair_records_the_cleared_telecaller() -> None:
    first = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(
        agent, first, expires_at=datetime.now(UTC) + timedelta(days=10)
    )
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            update(StaffProfile)
            .where(StaffProfile.id == first.id)
            .values(status=ProfileStatus.INACTIVE)
        )
        await db.execute(
            update(Lead)
            .where(Lead.id == lead.id)
            .values(created_at=datetime(1997, 1, 1, tzinfo=UTC))
        )
        await db.commit()
    async with db_session.AsyncSessionLocal() as db:
        await _assign_batch(db)
    repaired = await _load(lead.id)
    assert repaired.assigned_telecaller_profile_uuid is None
    assert repaired.status == LeadStatus.RELEASED
    assert repaired.last_telecaller_profile_uuid == first.id


async def test_trigger_guards_the_two_new_columns() -> None:
    first = await _seed_telecaller("loans")
    other = await _seed_telecaller("loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(
        agent, first, expires_at=datetime.now(UTC) + timedelta(days=10)
    )

    async def _refused(sql: str, **params: object) -> None:
        async with db_session.AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError, match="last_telecaller|last_resubmitted|new lead"):
                await db.execute(text(sql), {"id": lead.id, **params})
            await db.rollback()

    # Pointing the memory at someone without clearing the assignment.
    await _refused(
        "UPDATE leads SET last_telecaller_profile_uuid = :other WHERE id = :id",
        other=other.id,
    )
    # Clearing the assignment but recording someone else.
    await _refused(
        "UPDATE leads SET assigned_telecaller_profile_uuid = NULL, "
        "last_telecaller_profile_uuid = :other, status = 'released' WHERE id = :id",
        other=other.id,
    )
    # A resubmission time without a resubmission.
    await _refused("UPDATE leads SET last_resubmitted_at = now() WHERE id = :id")
    # A new lead cannot arrive pre-pointed at a Telecaller.
    async with db_session.AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError, match="new lead"):
            await db.execute(
                text(
                    "INSERT INTO leads (id, mobile, business_line, origin, status, "
                    "detail_ownership, resubmit_count, last_telecaller_profile_uuid, "
                    "created_at, updated_at) VALUES (gen_random_uuid(), :mobile, 'loans', "
                    "'direct', 'new', '{}'::jsonb, 0, :tc, now(), now())"
                ),
                {"mobile": unique_mobile(), "tc": first.id},
            )
        await db.rollback()

    # The legitimate clearing transition is accepted.
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            text(
                "UPDATE leads SET last_telecaller_profile_uuid = assigned_telecaller_profile_uuid, "
                "assigned_telecaller_profile_uuid = NULL, status = 'released' WHERE id = :id"
            ),
            {"id": lead.id},
        )
        await db.commit()
    assert (await _load(lead.id)).last_telecaller_profile_uuid == first.id


async def test_resubmission_is_visible_to_telecaller_and_admin(client: AsyncClient) -> None:
    tc_user, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    agent = await _seed_agent("loans")
    lead = await _assigned_agent_lead(agent, telecaller)
    await expire_agent_leads()
    res = await _resubmit(client, agent, lead.id)
    assert res.status_code == 200, res.text
    assert (await _load(lead.id)).assigned_telecaller_profile_uuid == telecaller.id

    tc_headers = headers(
        token_for(tc_user, "telecaller", business_line="loans", staff_profile=telecaller)
    )
    listed = await client.get("/api/v1/telecaller/leads", headers=tc_headers)
    row = next(item for item in listed.json() if item["id"] == str(lead.id))
    assert row["resubmit_count"] == 1
    assert row["last_resubmitted_at"] is not None
    detail = await client.get(f"/api/v1/telecaller/leads/{lead.id}", headers=tc_headers)
    assert detail.json()["resubmit_count"] == 1

    admin_user, admin_profile = await seed_staff(StaffRole.ADMIN)
    admin_headers = headers(
        token_for(admin_user, "admin", platform_scope="true", staff_profile=admin_profile)
    )
    assigned = await client.get("/api/v1/admin/leads/assigned?limit=500", headers=admin_headers)
    assert assigned.status_code == 200, assigned.text
    row = next(item for item in assigned.json() if item["id"] == str(lead.id))
    assert row["resubmit_count"] == 1
    assert row["last_resubmitted_at"] is not None

    # A never-resubmitted lead reads 0 / null on the Agent list.
    token = _agent_token(str(agent.auth_user_uuid), str(agent.id))
    created = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), "name": "Fresh"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["resubmit_count"] == 0
    assert created.json()["last_resubmitted_at"] is None
