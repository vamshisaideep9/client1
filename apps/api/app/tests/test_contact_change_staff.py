"""CS-025 staff contact-change requests and one-Admin approval.

Telecallers, Employees and Sub Admins (team managers included) request a
phone or email change; the new value is proven by a code; one platform Admin,
never the requester, approves (applied like a self-service change: session
version bump, refresh tokens revoked, history with the approver) or rejects
with password re-entry. Requires Postgres + Redis (Docker stack).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.tests.contact_change_support import (
    execute,
    fetch_all,
    fetch_one,
    headers,
    make_admin,
    make_staff,
    role_token,
    user_id,
)
from conftest import PASSWORD, full_registration, unique_email, unique_mobile

_REQ = "/api/v1/auth/contact-change/requests"
_ADMIN = "/api/v1/admin/contact-change-requests"


async def _request(
    client: AsyncClient, token: str, field: str, value: str, password: str = PASSWORD
):  # noqa: ANN202
    return await client.post(
        _REQ,
        headers=headers(token),
        json={"field": field, "value": value, "current_password": password},
    )


async def _submitted(client: AsyncClient, token: str, field: str, value: str) -> str:
    started = await _request(client, token, field, value)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["kind"] == "staff_request"
    assert body["status"] == "awaiting_new_otp"
    verified = await client.post(
        f"{_REQ}/verify",
        headers=headers(token),
        json={"change_id": body["change_id"], "otp": body["otp_hint"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "pending_approval"
    return body["change_id"]


async def _approve(client: AsyncClient, admin: str, request_id: str, password: str = PASSWORD):  # noqa: ANN202
    return await client.post(
        f"{_ADMIN}/{request_id}/approve",
        headers=headers(admin),
        json={"current_password": password},
    )


@pytest.mark.parametrize(
    ("role", "scope"),
    [("telecaller", "line"), ("employee", "line"), ("sub_admin", "platform")],
)
async def test_staff_phone_change_needs_one_admin_and_ends_their_sessions(
    client: AsyncClient, role: str, scope: str
) -> None:
    token, uid, old_mobile = await make_staff(client, role, scope=scope)
    new_mobile = unique_mobile()
    request_id = await _submitted(client, token, "mobile", new_mobile)

    admin_token, admin_uid, _ = await make_admin(client)
    queue = await client.get(_ADMIN, headers=headers(admin_token))
    assert queue.status_code == 200, queue.text
    row = next(r for r in queue.json()["requests"] if r["id"] == request_id)
    assert row["requested_value"] == new_mobile
    assert row["current_value"] == old_mobile
    assert row["requester_role"] == role
    assert row["field"] == "mobile"

    approved = await _approve(client, admin_token, request_id)
    assert approved.status_code == 200, approved.text

    user = await fetch_one(
        "SELECT mobile, session_version FROM auth_users WHERE id = :id", {"id": uid}
    )
    assert user == {"mobile": new_mobile, "session_version": 2}
    assert (await client.get("/api/v1/auth/me", headers=headers(token))).status_code == 401
    history = await fetch_all(
        "SELECT old_value, new_value, method, approved_by_user_uuid "
        "FROM contact_change_history WHERE auth_user_uuid = :id",
        {"id": uid},
    )
    assert [
        (h["old_value"], h["new_value"], h["method"], str(h["approved_by_user_uuid"]))
        for h in history
    ] == [(old_mobile, new_mobile, "admin_approved", admin_uid)]
    assert await fetch_one(
        "SELECT status, new_value, decided_by_user_uuid::text AS decided "
        "FROM contact_change_requests WHERE id = :id",
        {"id": request_id},
    ) == {"status": "completed", "new_value": None, "decided": admin_uid}
    audits = await fetch_all(
        "SELECT action::text AS action, actor_uuid::text AS actor, detail "
        "FROM audit_log WHERE entity_uuid = :id ORDER BY created_at",
        {"id": request_id},
    )
    assert [(a["action"], a["actor"]) for a in audits] == [
        ("contact_change_requested", uid),
        ("contact_changed", admin_uid),
    ]
    assert all(new_mobile not in str(a["detail"]) for a in audits)


async def test_staff_email_change_unblocks_the_email_step(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_file = unique_email()
    token, uid, _ = await make_staff(client, "employee", email=on_file)
    admin_token, admin_uid, _ = await make_admin(client)
    await execute(
        "UPDATE auth_users SET email = :e, email_verified_at = now() WHERE id = :id",
        {"e": unique_email(), "id": admin_uid},
    )
    # Existing accounts, then enforcement: the employee is held on the email
    # step but can still send the request that fixes it.
    monkeypatch.setattr(settings, "EMAIL_REQUIRED_ENFORCED", True)
    assert (await client.get("/api/v1/notifications", headers=headers(token))).status_code == 403

    new_email = unique_email()
    request_id = await _submitted(client, token, "email", new_email)
    assert (await _approve(client, admin_token, request_id)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers(token))).status_code == 401
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "mobile": (
                await fetch_one("SELECT mobile FROM auth_users WHERE id = :id", {"id": uid})
            )["mobile"],
            "password": PASSWORD,
        },  # noqa: E501
    )
    assert login.json()["email_required"] is False

    user = await fetch_one(
        "SELECT email, email_verified_at IS NOT NULL AS verified FROM auth_users WHERE id = :id",
        {"id": uid},
    )
    assert user == {"email": new_email, "verified": True}
    history = await fetch_one(
        "SELECT old_value FROM contact_change_history WHERE auth_user_uuid = :id", {"id": uid}
    )
    # The Admin-set address was never verified, so it is not a previous email.
    assert history == {"old_value": None}


async def test_admin_never_approves_their_own_request(client: AsyncClient) -> None:
    # An Admin cannot file a staff request at all...
    admin_token, admin_uid, _ = await make_admin(client)
    refused = await _request(client, admin_token, "mobile", unique_mobile())
    assert refused.status_code == 403
    # ...and even a pending request on the Admin's own account (say, one filed
    # before a promotion) can never be decided by that Admin.
    request_id = (
        await fetch_one(
            "INSERT INTO contact_change_requests (auth_user_uuid, kind, field, status, "
            "new_value, new_verified_at, expires_at) VALUES (:uid, 'staff_request', "
            "'mobile', 'pending_approval', :value, now(), now() + interval '1 day') "
            "RETURNING id::text AS id",
            {"uid": admin_uid, "value": unique_mobile()},
            commit=True,
        )
    )["id"]
    own = await _approve(client, admin_token, request_id)
    assert own.status_code == 409
    assert "requester" in own.json()["detail"].lower()
    rejected = await client.post(
        f"{_ADMIN}/{request_id}/reject",
        headers=headers(admin_token),
        json={"current_password": PASSWORD, "reason": "Self review attempt"},
    )
    assert rejected.status_code == 409


async def test_approval_needs_the_admins_password_and_a_live_admin_profile(
    client: AsyncClient,
) -> None:
    token, _, _ = await make_staff(client, "telecaller")
    request_id = await _submitted(client, token, "mobile", unique_mobile())
    admin_token, _, _ = await make_admin(client)
    wrong = await _approve(client, admin_token, request_id, password="Wrong@1234")
    assert wrong.status_code == 403
    # A platform-admin token on an account without a live Admin profile.
    _, fake_mobile = await full_registration(client)
    forged = role_token(await user_id(fake_mobile), "admin", platform_scope="true")
    assert (await _approve(client, forged, request_id)).status_code == 403
    assert (await client.get(_ADMIN, headers=headers(forged))).status_code == 403
    # Non-Admin roles never reach the queue.
    sub_admin, _, _ = await make_staff(client, "sub_admin", scope="platform")
    assert (await client.get(_ADMIN, headers=headers(sub_admin))).status_code == 403


async def test_reject_with_password_and_a_pii_free_reason(client: AsyncClient) -> None:
    token, uid, mobile = await make_staff(client, "telecaller")
    request_id = await _submitted(client, token, "mobile", unique_mobile())
    admin_token, admin_uid, _ = await make_admin(client)
    leaky = await client.post(
        f"{_ADMIN}/{request_id}/reject",
        headers=headers(admin_token),
        json={"current_password": PASSWORD, "reason": "Use +919876543210 instead"},
    )
    assert leaky.status_code == 422
    rejected = await client.post(
        f"{_ADMIN}/{request_id}/reject",
        headers=headers(admin_token),
        json={"current_password": PASSWORD, "reason": "Not confirmed with the team lead"},
    )
    assert rejected.status_code == 200, rejected.text
    assert await fetch_one(
        "SELECT status, new_value, rejection_reason FROM contact_change_requests WHERE id = :id",
        {"id": request_id},
    ) == {
        "status": "rejected",
        "new_value": None,
        "rejection_reason": "Not confirmed with the team lead",
    }
    assert await fetch_one("SELECT mobile FROM auth_users WHERE id = :id", {"id": uid}) == {
        "mobile": mobile
    }
    notice = await fetch_one(
        "SELECT type::text AS type FROM notifications WHERE user_uuid = :id "
        "AND type = 'contact_change_rejected'",
        {"id": uid},
    )
    assert notice == {"type": "contact_change_rejected"}
    again = await _approve(client, admin_token, request_id)
    assert again.status_code == 409
    assert admin_uid


async def test_request_steps_and_binding(client: AsyncClient) -> None:
    token, _, _ = await make_staff(client, "employee")
    started = (await _request(client, token, "mobile", unique_mobile())).json()
    # Not reviewable before the code.
    admin_token, _, _ = await make_admin(client)
    early = await _approve(client, admin_token, started["change_id"])
    assert early.status_code == 409
    # A second request while one is active.
    second = await _request(client, token, "email", unique_email())
    assert second.status_code == 409
    # Another staff member cannot verify this request.
    other, _, _ = await make_staff(client, "employee")
    stolen = await client.post(
        f"{_REQ}/verify",
        headers=headers(other),
        json={"change_id": started["change_id"], "otp": started["otp_hint"]},
    )
    assert stolen.status_code == 404


async def test_staff_cannot_self_serve_and_clients_cannot_request(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    refused = await _request(client, token, "mobile", unique_mobile())
    assert refused.status_code == 403
    assert "yourself" in refused.json()["detail"]


async def test_wrong_password_and_registered_number_refused(client: AsyncClient) -> None:
    token, _, _ = await make_staff(client, "telecaller")
    assert (
        await _request(client, token, "mobile", unique_mobile(), password="Wrong@1234")
    ).status_code == 403
    _, taken = await full_registration(client)
    assert (await _request(client, token, "mobile", taken)).status_code == 409
    assert (await _request(client, token, "mobile", "123")).status_code == 422


async def test_pending_request_expires(client: AsyncClient) -> None:
    token, _, _ = await make_staff(client, "telecaller")
    request_id = await _submitted(client, token, "mobile", unique_mobile())
    await execute(
        "UPDATE contact_change_requests SET expires_at = :t WHERE id = :id",
        {"t": datetime.now(UTC) - timedelta(seconds=1), "id": request_id},
    )
    admin_token, _, _ = await make_admin(client)
    late = await _approve(client, admin_token, request_id)
    assert late.status_code == 409
    queue = await client.get(_ADMIN, headers=headers(admin_token))
    assert all(r["id"] != request_id for r in queue.json()["requests"])


async def test_staff_may_withdraw_a_pending_request(client: AsyncClient) -> None:
    token, _, _ = await make_staff(client, "telecaller")
    request_id = await _submitted(client, token, "mobile", unique_mobile())
    active = await client.get("/api/v1/auth/contact-change/active", headers=headers(token))
    assert active.json()["change"]["status"] == "pending_approval"
    cancelled = await client.post(
        "/api/v1/auth/contact-change/cancel",
        headers=headers(token),
        json={"change_id": request_id},
    )
    assert cancelled.status_code == 200
    assert await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id", {"id": request_id}
    ) == {"status": "cancelled", "new_value": None}


async def test_admins_are_notified_of_a_new_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # notify_admins caps its fan-out (a suite-wide database can hold more
    # active Admins than the cap), so assert the call rather than one row.
    from app.services import contact_change as service

    calls: list[dict] = []

    async def _capture(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(service, "notify_admins", _capture)
    token, uid, _ = await make_staff(client, "telecaller")
    await _submitted(client, token, "mobile", unique_mobile())
    assert len(calls) == 1
    assert calls[0]["notification_type"] == "contact_change_requested"
    assert str(calls[0]["exclude_user_uuid"]) == uid
    assert "+91" not in str(calls[0]["body"])
