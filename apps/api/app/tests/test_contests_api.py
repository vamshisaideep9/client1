"""CS-027 contest authoring and maker-checker review (/api/v1/contests)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

import app.db.session as db_session
from app.models.audit_log import AuditAction, AuditLog
from app.models.contest import Contest
from app.models.notification import Notification, NotificationType
from app.models.profile import StaffRole
from app.services.contests import today_ist
from app.tests.contest_support import (
    admin_token,
    definition,
    headers,
    seed_agent,
    seed_contest,
    seed_loan_type,
    seed_staff,
    sub_admin_token,
    token_for,
)

pytestmark = pytest.mark.asyncio


async def _create(client: AsyncClient, token: str, **overrides) -> dict:
    response = await client.post(
        "/api/v1/contests", json=definition(**overrides), headers=headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_sub_admin_creates_a_draft_and_others_cannot(client: AsyncClient) -> None:
    maker, maker_user, _ = await sub_admin_token()
    created = await _create(client, maker)
    assert created["status"] == "draft"
    assert created["is_mine"] is True
    assert created["created_by_name"]
    assert created["criteria"]["loans"]["count_at_most"] == 5

    admin, _ = await admin_token()
    agent_user, agent = await seed_agent()
    agent_token = token_for(agent_user, "agent", business_line="loans", agent_profile=agent)
    for token in (admin, agent_token):
        response = await client.post("/api/v1/contests", json=definition(), headers=headers(token))
        assert response.status_code == 403


async def test_invalid_definitions_are_422(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    response = await client.post(
        "/api/v1/contests",
        json=definition(
            criteria={"version": 1, "loans": {"counted_stage": "disbursed", "count_at_most": 5}}
        ),
        headers=headers(maker),
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/v1/contests",
        json=definition(
            criteria={
                "version": 1,
                "loans": {
                    "counted_stage": "disbursed",
                    "count_at_least": 1,
                    "loan_type_ids": [str(uuid.uuid4())],
                },
            }
        ),
        headers=headers(maker),
    )
    assert response.status_code == 422
    assert "loan product" in response.json()["detail"]


async def test_only_the_maker_edits_and_submits(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    other, _, _ = await sub_admin_token()
    loan_type = await seed_loan_type()
    created = await _create(client, maker)
    body = definition(
        title="Personal loan sprint v2",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "count_at_least": 2,
            },
        },
    )
    response = await client.put(
        f"/api/v1/contests/{created['id']}", json=body, headers=headers(other)
    )
    assert response.status_code == 403
    response = await client.post(f"/api/v1/contests/{created['id']}/submit", headers=headers(other))
    assert response.status_code == 403

    response = await client.put(
        f"/api/v1/contests/{created['id']}", json=body, headers=headers(maker)
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Personal loan sprint v2"
    assert response.json()["version"] == 2

    # The other Sub Admin still reads it (shared authoring surface).
    response = await client.get(f"/api/v1/contests/{created['id']}", headers=headers(other))
    assert response.status_code == 200
    assert response.json()["is_mine"] is False


async def test_admin_edit_checks_version_and_exact_window_even_if_scheduler_lags(client) -> None:
    maker, maker_user, maker_profile = await sub_admin_token()
    admin, _ = await admin_token()
    participant, _ = await seed_agent("loans")
    yesterday, tomorrow = (today_ist() + timedelta(days=offset) for offset in (-1, 1))
    contest = await seed_contest(
        created_by=maker_user, status="approved", starts_on=yesterday, ends_on=tomorrow
    )
    url = f"/api/v1/contests/{contest.id}"
    body = definition(
        expected_version=contest.version,
        title="Updated sprint",
        description=None,
        terms=None,
        starts_on=str(yesterday),
        ends_on=str(tomorrow),
        prize_paise=contest.prize_paise,
        metric=contest.metric,
        criteria=contest.criteria,
    )
    maker_as_admin = token_for(
        maker_user, "admin", platform_scope="true", staff_profile=maker_profile
    )
    for token, update, code in (
        (maker, body, 422),
        (maker_as_admin, body, 403),
        (admin, {**body, "prize_paise": 999}, 409),
        (admin, {**body, "end_time": "22:00"}, 409),
        (admin, body, 200),
        (admin, body, 409),
    ):
        response = await client.put(url, json=update, headers=headers(token))
        assert response.status_code == code, response.text
    async with db_session.AsyncSessionLocal() as db:
        stored = await db.get(Contest, contest.id)
        assert stored.title == "Updated sprint" and stored.status == "approved"
        assert stored.checker_uuid == contest.checker_uuid
        audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == AuditAction.CONTEST_UPDATED, AuditLog.entity_uuid == contest.id
            )
        )
        assert audit.detail["before"]["title"] == contest.title
        assert audit.detail["after"]["title"] == "Updated sprint"
        notification = await db.scalar(
            select(Notification).where(
                Notification.type == NotificationType.CONTEST_UPDATED,
                Notification.user_uuid == participant.id,
                Notification.href == f"/dashboard/contests?contest={contest.id}",
            )
        )
        assert notification is not None
        stored.starts_on = yesterday - timedelta(days=1)
        stored.ends_on = yesterday
        await db.commit()
    response = await client.put(
        url, json={**body, "expected_version": contest.version + 1}, headers=headers(admin)
    )
    assert response.status_code == 409 and "ended" in response.json()["detail"]


async def test_full_review_cycle_with_maker_checker(client: AsyncClient) -> None:
    maker, maker_user, maker_profile = await sub_admin_token()
    admin, admin_user = await admin_token()
    created = await _create(client, maker)
    contest_id = created["id"]

    # Approve before submission is an illegal transition.
    response = await client.post(f"/api/v1/contests/{contest_id}/approve", headers=headers(admin))
    assert response.status_code == 409

    response = await client.post(f"/api/v1/contests/{contest_id}/submit", headers=headers(maker))
    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"

    # A pending contest is frozen for the maker.
    response = await client.put(
        f"/api/v1/contests/{contest_id}", json=definition(), headers=headers(maker)
    )
    assert response.status_code == 409

    # The maker's own account, even holding an Admin session, cannot approve.
    maker_as_admin = token_for(
        maker_user, "admin", platform_scope="true", staff_profile=maker_profile
    )
    response = await client.post(
        f"/api/v1/contests/{contest_id}/approve", headers=headers(maker_as_admin)
    )
    assert response.status_code == 403
    response = await client.post(
        f"/api/v1/contests/{contest_id}/reject",
        json={"note": "Self review"},
        headers=headers(maker_as_admin),
    )
    assert response.status_code == 403

    # A Sub Admin cannot review at all; a line-scoped Admin neither.
    response = await client.post(f"/api/v1/contests/{contest_id}/approve", headers=headers(maker))
    assert response.status_code == 403
    line_admin = token_for(admin_user, "admin", platform_scope="line")
    response = await client.post(
        f"/api/v1/contests/{contest_id}/approve", headers=headers(line_admin)
    )
    assert response.status_code == 403

    response = await client.post(
        f"/api/v1/contests/{contest_id}/reject",
        json={"note": "Lower the amount target."},
        headers=headers(admin),
    )
    assert response.status_code == 200
    rejected = response.json()
    assert rejected["status"] == "rejected"
    assert rejected["review_note"] == "Lower the amount target."
    assert rejected["checker_name"]

    # Editing a rejected contest returns it to draft; resubmit; approve.
    response = await client.put(
        f"/api/v1/contests/{contest_id}", json=definition(), headers=headers(maker)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    response = await client.post(f"/api/v1/contests/{contest_id}/submit", headers=headers(maker))
    assert response.status_code == 200
    response = await client.post(f"/api/v1/contests/{contest_id}/approve", headers=headers(admin))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"

    # Approving twice, deleting or cancelling as maker after approval: 409.
    response = await client.post(f"/api/v1/contests/{contest_id}/approve", headers=headers(admin))
    assert response.status_code == 409
    response = await client.delete(f"/api/v1/contests/{contest_id}", headers=headers(maker))
    assert response.status_code == 409
    response = await client.post(
        f"/api/v1/contests/{contest_id}/cancel",
        json={"reason": "No budget"},
        headers=headers(maker),
    )
    assert response.status_code == 409

    async with db_session.AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity_uuid == uuid.UUID(contest_id))
                .order_by(AuditLog.created_at)
            )
        )
    assert actions[0] == AuditAction.CONTEST_CREATED
    assert AuditAction.CONTEST_REJECTED in actions
    assert actions[-1] == AuditAction.CONTEST_APPROVED


async def test_past_start_date_cannot_be_submitted(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    yesterday = today_ist() - timedelta(days=1)
    created = await _create(
        client,
        maker,
        starts_on=yesterday.isoformat(),
        ends_on=(yesterday + timedelta(days=10)).isoformat(),
    )
    response = await client.post(f"/api/v1/contests/{created['id']}/submit", headers=headers(maker))
    assert response.status_code == 409
    assert "start date" in response.json()["detail"]


async def test_withdraw_cancel_and_delete(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    first = await _create(client, maker)
    response = await client.post(f"/api/v1/contests/{first['id']}/submit", headers=headers(maker))
    assert response.status_code == 200
    response = await client.post(f"/api/v1/contests/{first['id']}/withdraw", headers=headers(maker))
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    response = await client.delete(f"/api/v1/contests/{first['id']}", headers=headers(maker))
    assert response.status_code == 204
    response = await client.get(f"/api/v1/contests/{first['id']}", headers=headers(maker))
    assert response.status_code == 404

    second = await _create(client, maker)
    response = await client.post(
        f"/api/v1/contests/{second['id']}/cancel",
        json={"reason": "Duplicate of another contest"},
        headers=headers(maker),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    response = await client.post(f"/api/v1/contests/{second['id']}/submit", headers=headers(maker))
    assert response.status_code == 409


async def test_list_filters_and_role_guard(client: AsyncClient) -> None:
    maker, _, _ = await sub_admin_token()
    created = await _create(client, maker, title=f"Filter {uuid.uuid4().hex[:8]}")
    response = await client.get(
        "/api/v1/contests",
        params={"status": "draft", "mine": "true", "q": created["title"]},
        headers=headers(maker),
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["contests"]] == [created["id"]]

    telecaller_user, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    token = token_for(
        telecaller_user, "telecaller", business_line="loans", staff_profile=telecaller
    )
    response = await client.get("/api/v1/contests", headers=headers(token))
    assert response.status_code == 403


async def test_database_refuses_checker_equal_to_maker(client: AsyncClient) -> None:
    _, maker_user, _ = await sub_admin_token()
    async with db_session.AsyncSessionLocal() as db:
        contest = Contest(
            title="Constraint check",
            business_line="loans",
            audience="agent",
            metric="cases",
            criteria={"version": 1, "loans": {"counted_stage": "disbursed", "count_at_least": 1}},
            win_mode="threshold",
            prize_paise=100,
            starts_on=today_ist(),
            ends_on=today_ist(),
            status="draft",
            created_by_uuid=maker_user.id,
        )
        db.add(contest)
        await db.commit()
        with pytest.raises(IntegrityError):
            await db.execute(
                text("UPDATE contests SET checker_uuid = created_by_uuid WHERE id = :id"),
                {"id": contest.id},
            )
        await db.rollback()
