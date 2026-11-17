"""CS-025 self-service phone and email change (Client, Agent, Admin).

Covers the state machine (password, code to the current value, new value,
code to the new value, atomic update), step skipping, expiry, codes bound to
one change and one stage, wrong passwords and budgets, the one-active-change
rule (409, including a lost-number request), uniqueness conflicts, session
version bump and refresh-token revocation, notices to the old and new
contact, the permanent history (Admin-only read, audited), and that the
lost-number recovery still works and now records history.
Requires Postgres + Redis (Docker stack).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import contact_change as service
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
from conftest import PASSWORD, add_verified_email, full_registration, unique_email, unique_mobile

_BASE = "/api/v1/auth/contact-change"


async def _start(client: AsyncClient, token: str, field: str, password: str = PASSWORD):  # noqa: ANN202
    return await client.post(
        f"{_BASE}/start",
        headers=headers(token),
        json={"field": field, "current_password": password},
    )


async def _step(client: AsyncClient, token: str, step: str, body: dict):  # noqa: ANN202
    return await client.post(f"{_BASE}/{step}", headers=headers(token), json=body)


async def _to_new_value(client: AsyncClient, token: str, field: str) -> dict:
    started = await _start(client, token, field)
    assert started.status_code == 200, started.text
    body = started.json()
    verified = await _step(
        client, token, "verify-current", {"change_id": body["change_id"], "otp": body["otp_hint"]}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "awaiting_new_value"
    return body


async def _change(client: AsyncClient, token: str, field: str, value: str) -> dict:
    body = await _to_new_value(client, token, field)
    sent = await _step(client, token, "new-value", {"change_id": body["change_id"], "value": value})
    assert sent.status_code == 200, sent.text
    done = await _step(
        client,
        token,
        "verify-new",
        {"change_id": body["change_id"], "otp": sent.json()["otp_hint"]},
    )
    assert done.status_code == 200, done.text
    return {"change_id": body["change_id"], "response": done.json()}


async def test_client_changes_phone_and_every_session_ends(client: AsyncClient) -> None:
    token, old_mobile = await full_registration(client)
    uid = await user_id(old_mobile)
    login = await client.post(
        "/api/v1/auth/login", json={"mobile": old_mobile, "password": PASSWORD}
    )
    assert login.status_code == 200
    new_mobile = unique_mobile()

    result = await _change(client, token, "mobile", new_mobile)
    assert result["response"]["signed_out"] is True

    # Every refresh token was revoked and the session version moved on.
    live = await fetch_one(
        "SELECT count(*) AS live FROM refresh_tokens "
        "WHERE auth_user_uuid = :id AND revoked = false",
        {"id": uid},
    )
    assert live == {"live": 0}
    user = await fetch_one(
        "SELECT mobile, session_version FROM auth_users WHERE id = :id", {"id": uid}
    )
    assert user == {"mobile": new_mobile, "session_version": 2}

    # Old access token, old refresh cookie and old login number are all dead.
    assert (await client.get("/api/v1/auth/me", headers=headers(token))).status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    old_login = await client.post(
        "/api/v1/auth/login", json={"mobile": old_mobile, "password": PASSWORD}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"mobile": new_mobile, "password": PASSWORD}
    )
    assert new_login.status_code == 200
    history = await fetch_all(
        "SELECT field, old_value, new_value, method, approved_by_user_uuid "
        "FROM contact_change_history WHERE auth_user_uuid = :id",
        {"id": uid},
    )
    assert history == [
        {
            "field": "mobile",
            "old_value": old_mobile,
            "new_value": new_mobile,
            "method": "self_service",
            "approved_by_user_uuid": None,
        }
    ]
    row = await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id",
        {"id": result["change_id"]},
    )
    assert row == {"status": "completed", "new_value": None}
    audit = await fetch_one(
        "SELECT action::text AS action, detail FROM audit_log WHERE entity_uuid = :id",
        {"id": result["change_id"]},
    )
    assert audit["action"] == "contact_changed"
    assert old_mobile not in str(audit["detail"]) and new_mobile not in str(audit["detail"])
    event = await fetch_one(
        "SELECT mobile, detail FROM auth_events WHERE auth_user_uuid = :id "
        "AND event_type = 'contact_changed'",
        {"id": uid},
    )
    assert event["mobile"] is None
    assert new_mobile not in str(event["detail"])


async def test_agent_changes_email_and_notices_go_to_old_and_new(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []

    async def _capture(to: str, subject: str, body: str) -> bool:
        sent.append((to, subject))
        return True

    monkeypatch.setattr(service, "send_email", _capture)
    _, mobile = await full_registration(client)
    uid = await user_id(mobile)
    old_email = await add_verified_email(client, role_token(uid, "client"))
    agent_token = role_token(uid, "agent")
    new_email = unique_email()

    await _change(client, agent_token, "email", new_email)

    recipients = {to for to, _subject in sent}
    assert recipients == {old_email, new_email}
    assert new_email not in next(subject for to, subject in sent if to == old_email)
    me = await client.post("/api/v1/auth/login", json={"mobile": mobile, "password": PASSWORD})
    assert me.json()["email_verified"] is True
    user = await fetch_one("SELECT email FROM auth_users WHERE id = :id", {"id": uid})
    assert user == {"email": new_email}
    notification = await fetch_one(
        "SELECT type::text AS type FROM notifications WHERE user_uuid = :id "
        "AND type = 'contact_changed'",
        {"id": uid},
    )
    assert notification == {"type": "contact_changed"}


async def test_phone_change_notice_goes_to_the_verified_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    async def _capture(to: str, subject: str, body: str) -> bool:
        sent.append(to)
        return True

    monkeypatch.setattr(service, "send_email", _capture)
    token, _ = await full_registration(client)
    email = await add_verified_email(client, token)
    await _change(client, token, "mobile", unique_mobile())
    assert sent == [email]


async def test_admin_may_change_their_own_contact_details(client: AsyncClient) -> None:
    token, uid, _ = await make_admin(client)
    new_mobile = unique_mobile()
    await _change(client, token, "mobile", new_mobile)
    assert await fetch_one("SELECT mobile FROM auth_users WHERE id = :id", {"id": uid}) == {
        "mobile": new_mobile
    }


@pytest.mark.parametrize("role", ["telecaller", "employee", "sub_admin"])
async def test_staff_cannot_self_serve(client: AsyncClient, role: str) -> None:
    scope = "platform" if role == "sub_admin" else "line"
    token, _, _ = await make_staff(client, role, scope=scope)
    refused = await _start(client, token, "mobile")
    assert refused.status_code == 403
    assert "request" in refused.json()["detail"].lower()


async def test_wrong_password_is_refused_and_counts_toward_the_login_lock(
    client: AsyncClient,
) -> None:
    token, mobile = await full_registration(client)
    for _ in range(5):
        wrong = await _start(client, token, "mobile", password="Wrong@1234")
        assert wrong.status_code in (403, 429)
    locked = await client.post("/api/v1/auth/login", json={"mobile": mobile, "password": PASSWORD})
    assert locked.status_code == 429


async def test_start_budget_per_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONTACT_CHANGE_START_LIMIT_PER_ACCOUNT", 1)
    token, _ = await full_registration(client)
    first = await _start(client, token, "mobile")
    assert first.status_code == 200
    cancel = await _step(client, token, "cancel", {"change_id": first.json()["change_id"]})
    assert cancel.status_code == 200
    assert (await _start(client, token, "mobile")).status_code == 429


async def test_steps_cannot_be_skipped(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    started = (await _start(client, token, "mobile")).json()
    change_id = started["change_id"]
    # New value before the current-value code.
    early = await _step(
        client, token, "new-value", {"change_id": change_id, "value": unique_mobile()}
    )
    assert early.status_code == 409
    # Completion before anything.
    skipped = await _step(client, token, "verify-new", {"change_id": change_id, "otp": "123456"})
    assert skipped.status_code == 409
    # Verify-current twice.
    ok = await _step(
        client, token, "verify-current", {"change_id": change_id, "otp": started["otp_hint"]}
    )
    assert ok.status_code == 200
    again = await _step(
        client, token, "verify-current", {"change_id": change_id, "otp": started["otp_hint"]}
    )
    assert again.status_code == 409


async def test_current_value_code_never_verifies_the_new_value(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    body = await _to_new_value(client, token, "mobile")
    sent = (
        await _step(
            client, token, "new-value", {"change_id": body["change_id"], "value": unique_mobile()}
        )
    ).json()
    if body["otp_hint"] != sent["otp_hint"]:
        reused = await _step(
            client, token, "verify-new", {"change_id": body["change_id"], "otp": body["otp_hint"]}
        )
        assert reused.status_code == 400


async def test_a_code_from_another_change_or_account_is_refused(client: AsyncClient) -> None:
    token_a, _ = await full_registration(client)
    token_b, _ = await full_registration(client)
    a = (await _start(client, token_a, "mobile")).json()
    b = (await _start(client, token_b, "mobile")).json()
    # B cannot see or drive A's change.
    stolen = await _step(
        client, token_b, "verify-current", {"change_id": a["change_id"], "otp": a["otp_hint"]}
    )
    assert stolen.status_code == 404
    if a["otp_hint"] != b["otp_hint"]:
        crossed = await _step(
            client, token_b, "verify-current", {"change_id": b["change_id"], "otp": a["otp_hint"]}
        )
        assert crossed.status_code == 400


async def test_resubmitting_the_new_value_rebinds_the_code(client: AsyncClient) -> None:
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    body = await _to_new_value(client, token, "mobile")
    first = (
        await _step(
            client, token, "new-value", {"change_id": body["change_id"], "value": unique_mobile()}
        )
    ).json()
    final_mobile = unique_mobile()
    second = (
        await _step(
            client, token, "new-value", {"change_id": body["change_id"], "value": final_mobile}
        )
    ).json()
    if first["otp_hint"] != second["otp_hint"]:
        stale = await _step(
            client, token, "verify-new", {"change_id": body["change_id"], "otp": first["otp_hint"]}
        )
        assert stale.status_code == 400
    done = await _step(
        client, token, "verify-new", {"change_id": body["change_id"], "otp": second["otp_hint"]}
    )
    assert done.status_code == 200, done.text
    assert await fetch_one("SELECT mobile FROM auth_users WHERE id = :id", {"id": uid}) == {
        "mobile": final_mobile
    }


async def test_expired_change_is_refused(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    started = (await _start(client, token, "mobile")).json()
    await execute(
        "UPDATE contact_change_requests SET expires_at = :t WHERE id = :id",
        {"t": datetime.now(UTC) - timedelta(seconds=1), "id": started["change_id"]},
    )
    late = await _step(
        client,
        token,
        "verify-current",
        {"change_id": started["change_id"], "otp": started["otp_hint"]},
    )
    assert late.status_code == 409
    assert "expired" in late.json()["detail"]
    # A new change can start straight away.
    assert (await _start(client, token, "mobile")).status_code == 200


async def test_phone_and_email_are_never_changed_together(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    await add_verified_email(client, token)
    first = await _start(client, token, "mobile")
    assert first.status_code == 200
    second = await _start(client, token, "email")
    assert second.status_code == 409
    assert "in progress" in second.json()["detail"]
    active = await client.get(f"{_BASE}/active", headers=headers(token))
    assert active.status_code == 200
    assert active.json()["change"]["field"] == "mobile"


async def test_an_open_lost_number_request_blocks_a_self_service_change(
    client: AsyncClient,
) -> None:
    token, mobile = await full_registration(client)
    challenge = await client.post(
        "/api/v1/mobile-change/initiate",
        json={"current_mobile": mobile, "requested_mobile": unique_mobile(), "company": ""},
    )
    body = challenge.json()
    await client.post(
        "/api/v1/mobile-change/verify",
        json={"challenge_token": body["challenge_token"], "otp": body["otp_hint"]},
    )
    blocked = await _start(client, token, "mobile")
    assert blocked.status_code == 409


async def test_email_change_needs_a_verified_email(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    refused = await _start(client, token, "email")
    assert refused.status_code == 409
    assert "Add" in refused.json()["detail"]


async def test_new_value_must_differ_and_be_free(client: AsyncClient) -> None:
    token, mobile = await full_registration(client)
    _, other_mobile = await full_registration(client)
    body = await _to_new_value(client, token, "mobile")
    same = await _step(
        client, token, "new-value", {"change_id": body["change_id"], "value": mobile}
    )
    assert same.status_code == 409
    taken = await _step(
        client, token, "new-value", {"change_id": body["change_id"], "value": other_mobile}
    )
    assert taken.status_code == 409
    bad = await _step(
        client, token, "new-value", {"change_id": body["change_id"], "value": "12345"}
    )
    assert bad.status_code == 422


async def test_email_taken_by_a_verified_account_is_refused_after_the_code(
    client: AsyncClient,
) -> None:
    owner, _ = await full_registration(client)
    taken = await add_verified_email(client, owner)
    token, mobile = await full_registration(client)
    mine = await add_verified_email(client, token)
    body = await _to_new_value(client, token, "email")
    sent = (
        await _step(client, token, "new-value", {"change_id": body["change_id"], "value": taken})
    ).json()
    refused = await _step(
        client, token, "verify-new", {"change_id": body["change_id"], "otp": sent["otp_hint"]}
    )
    assert refused.status_code == 409
    assert await fetch_one("SELECT email FROM auth_users WHERE mobile = :m", {"m": mobile}) == {
        "email": mine
    }


async def test_current_value_changing_mid_flow_cancels_the_change(client: AsyncClient) -> None:
    token, mobile = await full_registration(client)
    started = (await _start(client, token, "mobile")).json()
    await execute(
        "UPDATE auth_users SET mobile = :new WHERE mobile = :old",
        {"new": unique_mobile(), "old": mobile},
    )
    stale = await _step(
        client,
        token,
        "verify-current",
        {"change_id": started["change_id"], "otp": started["otp_hint"]},
    )
    assert stale.status_code == 409


async def test_target_budget_caps_codes_to_one_new_number(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONTACT_CHANGE_TARGET_DAILY_LIMIT", 1)
    target = unique_mobile()
    token, _ = await full_registration(client)
    body = await _to_new_value(client, token, "mobile")
    assert (
        await _step(client, token, "new-value", {"change_id": body["change_id"], "value": target})
    ).status_code == 200
    again = await _step(
        client, token, "new-value", {"change_id": body["change_id"], "value": target}
    )
    assert again.status_code == 429


async def test_history_endpoint_is_platform_admin_only_and_audited(client: AsyncClient) -> None:
    token, old_mobile = await full_registration(client)
    uid = await user_id(old_mobile)
    new_mobile = unique_mobile()
    await _change(client, token, "mobile", new_mobile)
    admin_token, admin_uid, _ = await make_admin(client)

    response = await client.get(
        f"/api/v1/admin/users/{uid}/contact-history", headers=headers(admin_token)
    )
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert [(e["field"], e["old_value"], e["new_value"], e["method"]) for e in entries] == [
        ("mobile", old_mobile, new_mobile, "self_service")
    ]
    viewed = await fetch_all(
        "SELECT actor_uuid FROM audit_log WHERE action = 'contact_history_viewed' "
        "AND entity_uuid = :uid",
        {"uid": uid},
    )
    assert [str(row["actor_uuid"]) for row in viewed] == [admin_uid]

    login = await client.post(
        "/api/v1/auth/login", json={"mobile": new_mobile, "password": PASSWORD}
    )
    own = await client.get(
        f"/api/v1/admin/users/{uid}/contact-history",
        headers=headers(login.json()["access_token"]),
    )
    assert own.status_code == 403
    sub_admin_token, _, _ = await make_staff(client, "sub_admin", scope="platform")
    assert (
        await client.get(
            f"/api/v1/admin/users/{uid}/contact-history", headers=headers(sub_admin_token)
        )
    ).status_code == 403


async def test_lost_number_recovery_still_needs_two_admins_and_records_history(
    client: AsyncClient,
) -> None:
    _, current = await full_registration(client)
    uid = await user_id(current)
    requested = unique_mobile()
    challenge = (
        await client.post(
            "/api/v1/mobile-change/initiate",
            json={"current_mobile": current, "requested_mobile": requested, "company": ""},
        )
    ).json()
    await client.post(
        "/api/v1/mobile-change/verify",
        json={"challenge_token": challenge["challenge_token"], "otp": challenge["otp_hint"]},
    )
    maker, _, _ = await make_admin(client)
    checker, checker_uid, _ = await make_admin(client)
    queue = await client.get("/api/v1/admin/mobile-change-requests", headers=headers(maker))
    request = next(r for r in queue.json()["requests"] if r["auth_user_uuid"] == uid)
    verified = await client.post(
        f"/api/v1/admin/mobile-change-requests/{request['id']}/verify",
        headers=headers(maker),
        json={
            "proof_method": "staff_confirmation",
            "proof_attestation": "Branch visit ref BV-ALPHA",
            "current_password": PASSWORD,
        },
    )
    assert verified.status_code == 200, verified.text
    same_admin = await client.post(
        f"/api/v1/admin/mobile-change-requests/{request['id']}/complete",
        headers=headers(maker),
        json={"current_password": PASSWORD},
    )
    assert same_admin.status_code == 409
    completed = await client.post(
        f"/api/v1/admin/mobile-change-requests/{request['id']}/complete",
        headers=headers(checker),
        json={"current_password": PASSWORD},
    )
    assert completed.status_code == 200, completed.text
    history = await fetch_all(
        "SELECT old_value, new_value, method, proof_category, proof_reference, "
        "approved_by_user_uuid FROM contact_change_history WHERE auth_user_uuid = :id",
        {"id": uid},
    )
    assert len(history) == 1
    entry = history[0]
    assert (entry["old_value"], entry["new_value"]) == (current, requested)
    assert entry["method"] == "lost_number_recovery"
    assert entry["proof_category"] == "staff_confirmation"
    assert entry["proof_reference"] == "Branch visit ref BV-ALPHA"
    assert str(entry["approved_by_user_uuid"]) == checker_uid
    # The request row still clears both numbers on completion.
    assert await fetch_one(
        "SELECT current_mobile, requested_mobile FROM mobile_change_requests WHERE id = :id",
        {"id": request["id"]},
    ) == {"current_mobile": None, "requested_mobile": None}
