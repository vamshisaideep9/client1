"""CS-025 mandatory email: the enforcement gate, adding an email, registration.

Covers the EMAIL_REQUIRED_ENFORCED gate on and off (which endpoints stay
reachable, that logout/refresh/password change are never locked out), the
add-email journey (password, code bound to one change and one address, replay,
expiry, address conflicts, staff limits), the registration email step, the
permanent history row with its Admin-only RLS, and erasure with the account.
Requires Postgres + Redis (Docker stack).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import settings
from app.tests.contact_change_support import (
    as_api_user,
    execute,
    fetch_all,
    fetch_one,
    headers,
    make_admin,
    make_staff,
    role_token,
    user_id,
)
from conftest import (
    PASSWORD,
    add_verified_email,
    full_registration,
    initiate_and_get_otp,
    unique_email,
    unique_mobile,
)


@pytest.fixture
def enforce(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Switch enforcement on later, once the test has created its accounts."""

    def _on() -> None:
        monkeypatch.setattr(settings, "EMAIL_REQUIRED_ENFORCED", True)

    return _on


async def _start_add(client: AsyncClient, token: str, email: str, password: str = PASSWORD):  # noqa: ANN202
    return await client.post(
        "/api/v1/auth/email/add",
        headers=headers(token),
        json={"email": email, "current_password": password},
    )


async def _verify_add(client: AsyncClient, token: str, change_id: str, otp: str):  # noqa: ANN202
    return await client.post(
        "/api/v1/auth/email/add/verify",
        headers=headers(token),
        json={"change_id": change_id, "otp": otp},
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


async def test_gate_off_by_default_leaves_accounts_without_email_working(
    client: AsyncClient,
) -> None:
    assert settings.EMAIL_REQUIRED_ENFORCED is False
    token, _ = await full_registration(client)
    me = await client.get("/api/v1/auth/me", headers=headers(token))
    assert me.status_code == 200
    assert me.json()["email_required"] is False
    assert (await client.get("/api/v1/notifications", headers=headers(token))).status_code == 200


async def test_gate_on_blocks_business_endpoints_until_email_is_verified(
    client: AsyncClient, enforce
) -> None:
    token, mobile = await full_registration(client)
    enforce()
    login = await client.post("/api/v1/auth/login", json={"mobile": mobile, "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["email_required"] is True

    me = await client.get("/api/v1/auth/me", headers=headers(token))
    assert me.status_code == 200
    assert me.json()["email_required"] is True

    for method, path in (
        ("GET", "/api/v1/notifications"),
        ("GET", "/api/v1/referrals/me"),
        ("PATCH", "/api/v1/auth/me"),
    ):
        blocked = await client.request(
            method,
            path,
            headers=headers(token),
            json={"first_name": "A", "last_name": "B"} if method == "PATCH" else None,
        )
        assert blocked.status_code == 403, (path, blocked.text)
        assert blocked.headers.get("x-email-required") == "1"

    # Adding the email clears the gate for the SAME session.
    await add_verified_email(client, token)
    me = await client.get("/api/v1/auth/me", headers=headers(token))
    assert me.json()["email_required"] is False
    assert (await client.get("/api/v1/notifications", headers=headers(token))).status_code == 200


async def test_gate_never_locks_out_logout_refresh_or_password_change(
    client: AsyncClient, enforce
) -> None:
    _, mobile = await full_registration(client)
    enforce()
    login = await client.post("/api/v1/auth/login", json={"mobile": mobile, "password": PASSWORD})
    token = login.json()["access_token"]

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["email_required"] is True
    token = refreshed.json()["access_token"]

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=headers(token),
        json={
            "current_password": PASSWORD,
            "new_password": "Newer@12345",
            "confirm_password": "Newer@12345",
        },
    )
    assert changed.status_code == 200, changed.text

    login = await client.post(
        "/api/v1/auth/login", json={"mobile": mobile, "password": "Newer@12345"}
    )
    out = await client.post("/api/v1/auth/logout", headers=headers(login.json()["access_token"]))
    assert out.status_code == 200


async def test_gate_allows_account_deletion(client: AsyncClient, enforce) -> None:
    token, _ = await full_registration(client)
    enforce()
    deleted = await client.request(
        "DELETE",
        "/api/v1/auth/me",
        headers=headers(token),
        json={"current_password": PASSWORD},
    )
    assert deleted.status_code == 200, deleted.text


async def test_staff_can_verify_the_admin_set_email_on_file(client: AsyncClient, enforce) -> None:
    on_file = unique_email()
    token, uid, _ = await make_staff(client, "telecaller", email=on_file)
    enforce()
    assert (await client.get("/api/v1/notifications", headers=headers(token))).status_code == 403

    # A different address needs an Admin; the address on file can be verified.
    refused = await _start_add(client, token, unique_email())
    assert refused.status_code == 403
    assert "Admin" in refused.json()["detail"]

    init = await client.post("/api/v1/auth/email/verify/initiate", headers=headers(token))
    assert init.status_code == 200, init.text
    confirm = await client.post(
        "/api/v1/auth/email/verify/confirm",
        headers=headers(token),
        json={"otp": init.json()["otp_hint"]},
    )
    assert confirm.status_code == 200, confirm.text
    assert (await client.get("/api/v1/notifications", headers=headers(token))).status_code == 200
    row = await fetch_one("SELECT email FROM auth_users WHERE id = :id", {"id": uid})
    assert row == {"email": on_file}


# ---------------------------------------------------------------------------
# Adding an email
# ---------------------------------------------------------------------------


async def test_add_email_requires_the_current_password(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    wrong = await _start_add(client, token, unique_email(), password="Wrong@1234")
    assert wrong.status_code == 403
    assert wrong.json()["detail"] == "Current password is incorrect."


async def test_add_email_budget_limits_password_guessing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONTACT_CHANGE_START_LIMIT_PER_ACCOUNT", 2)
    token, _ = await full_registration(client)
    for _ in range(2):
        assert (
            await _start_add(client, token, unique_email(), password="Wrong@1234")
        ).status_code == 403
    limited = await _start_add(client, token, unique_email())
    assert limited.status_code == 429


async def test_add_email_stores_a_verified_address_and_history(client: AsyncClient) -> None:
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    email = unique_email()
    started = await _start_add(client, token, email.upper())
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["kind"] == "email_add"
    assert body["status"] == "awaiting_new_otp"
    assert body["destination_hint"].endswith(email.split("@")[1])
    assert email not in body["destination_hint"]

    verified = await _verify_add(client, token, body["change_id"], body["otp_hint"])
    assert verified.status_code == 200, verified.text
    assert verified.json()["email"] == email
    assert verified.json()["email_verified"] is True

    request = await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id",
        {"id": body["change_id"]},
    )
    assert request == {"status": "completed", "new_value": None}
    history = await fetch_all(
        "SELECT field, old_value, new_value, method FROM contact_change_history "
        "WHERE auth_user_uuid = :uid",
        {"uid": uid},
    )
    assert history == [
        {"field": "email", "old_value": None, "new_value": email, "method": "email_added"}
    ]
    audit = await fetch_one(
        "SELECT action::text AS action, detail FROM audit_log WHERE entity_uuid = :id",
        {"id": body["change_id"]},
    )
    assert audit["action"] == "contact_changed"
    assert email not in str(audit["detail"])


async def test_add_email_code_is_single_use_and_bound_to_its_change(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    other_token, _ = await full_registration(client)
    started = (await _start_add(client, token, unique_email())).json()

    # Another account cannot use (or even see) this change.
    stolen = await _verify_add(client, other_token, started["change_id"], started["otp_hint"])
    assert stolen.status_code == 404
    # A wrong code is refused; the right one works once.
    wrong = "000000" if started["otp_hint"] != "000000" else "111111"
    assert (await _verify_add(client, token, started["change_id"], wrong)).status_code == 400
    ok = await _verify_add(client, token, started["change_id"], started["otp_hint"])
    assert ok.status_code == 200
    replay = await _verify_add(client, token, started["change_id"], started["otp_hint"])
    assert replay.status_code == 409  # the change is completed, not at that step


async def test_resubmitting_another_address_invalidates_the_first_code(
    client: AsyncClient,
) -> None:
    token, _ = await full_registration(client)
    first = (await _start_add(client, token, unique_email())).json()
    second_email = unique_email()
    second = (await _start_add(client, token, second_email)).json()
    assert second["change_id"] == first["change_id"]  # one active row, value replaced

    if first["otp_hint"] != second["otp_hint"]:
        stale = await _verify_add(client, token, first["change_id"], first["otp_hint"])
        assert stale.status_code == 400
    done = await _verify_add(client, token, second["change_id"], second["otp_hint"])
    assert done.status_code == 200, done.text
    assert done.json()["email"] == second_email


async def test_a_login_or_registration_code_never_verifies_an_email_add(
    client: AsyncClient,
) -> None:
    token, mobile = await full_registration(client)
    started = (await _start_add(client, token, unique_email())).json()
    # A fresh registration-purpose code for an unrelated number.
    register_code = await initiate_and_get_otp(client, unique_mobile())
    if register_code != started["otp_hint"]:
        refused = await _verify_add(client, token, started["change_id"], register_code)
        assert refused.status_code == 400


async def test_expired_add_is_refused_and_the_sweep_clears_its_value(
    client: AsyncClient,
) -> None:
    from app.services.contact_change import expire_stale_changes

    token, _ = await full_registration(client)
    started = (await _start_add(client, token, unique_email())).json()
    past = datetime.now(UTC) - timedelta(minutes=1)
    await execute(
        "UPDATE contact_change_requests SET expires_at = :t WHERE id = :id",
        {"t": past, "id": started["change_id"]},
    )
    late = await _verify_add(client, token, started["change_id"], started["otp_hint"])
    assert late.status_code == 409
    assert "expired" in late.json()["detail"]
    assert await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id",
        {"id": started["change_id"]},
    ) == {"status": "expired", "new_value": None}

    other_token, _ = await full_registration(client)
    other = (await _start_add(client, other_token, unique_email())).json()
    await execute(
        "UPDATE contact_change_requests SET expires_at = :t WHERE id = :id",
        {"t": past, "id": other["change_id"]},
    )
    assert await expire_stale_changes() >= 1
    assert await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id",
        {"id": other["change_id"]},
    ) == {"status": "expired", "new_value": None}


async def test_add_email_refuses_while_another_change_is_active(client: AsyncClient) -> None:
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    await execute(
        "INSERT INTO contact_change_requests (auth_user_uuid, kind, field, status, expires_at) "
        "VALUES (:uid, 'self_service', 'mobile', 'awaiting_current_otp', :exp)",
        {"uid": uid, "exp": datetime.now(UTC) + timedelta(minutes=10)},
    )
    blocked = await _start_add(client, token, unique_email())
    assert blocked.status_code == 409
    assert "in progress" in blocked.json()["detail"]


async def test_already_verified_account_cannot_add_another_email(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    await add_verified_email(client, token)
    again = await _start_add(client, token, unique_email())
    assert again.status_code == 409


async def test_a_verified_address_elsewhere_is_a_conflict_after_the_code(
    client: AsyncClient,
) -> None:
    owner_token, _ = await full_registration(client)
    taken = await add_verified_email(client, owner_token)
    token, _ = await full_registration(client)
    started = (await _start_add(client, token, taken)).json()
    refused = await _verify_add(client, token, started["change_id"], started["otp_hint"])
    assert refused.status_code == 409
    assert "another account" in refused.json()["detail"]
    assert await fetch_one(
        "SELECT status, new_value FROM contact_change_requests WHERE id = :id",
        {"id": started["change_id"]},
    ) == {"status": "cancelled", "new_value": None}


async def test_an_unverified_copy_elsewhere_is_released_to_the_proven_owner(
    client: AsyncClient,
) -> None:
    contested = unique_email()
    _, squatter_mobile = await full_registration(client, email=contested)
    token, _ = await full_registration(client)
    started = (await _start_add(client, token, contested)).json()
    done = await _verify_add(client, token, started["change_id"], started["otp_hint"])
    assert done.status_code == 200, done.text
    squatter = await fetch_one(
        "SELECT email, email_verified_at FROM auth_users WHERE mobile = :m",
        {"m": squatter_mobile},
    )
    assert squatter == {"email": None, "email_verified_at": None}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def _registration_token(client: AsyncClient, mobile: str) -> dict:
    otp = await initiate_and_get_otp(client, mobile)
    verified = await client.post(
        "/api/v1/auth/register/verify-otp", json={"mobile": mobile, "otp": otp}
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


async def _set_password(client: AsyncClient, token: str):  # noqa: ANN202
    return await client.post(
        "/api/v1/auth/register/set-password",
        json={"registration_token": token, "password": PASSWORD, "confirm_password": PASSWORD},
    )


async def _email_step(client: AsyncClient, reg_token: str, email: str) -> str:
    sent = await client.post(
        "/api/v1/auth/register/email/initiate",
        json={"registration_token": reg_token, "email": email},
    )
    assert sent.status_code == 200, sent.text
    verified = await client.post(
        "/api/v1/auth/register/email/verify",
        json={"registration_token": reg_token, "email": email, "otp": sent.json()["otp_hint"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()["registration_token"]


async def test_registration_without_enforcement_needs_no_email(client: AsyncClient) -> None:
    body = await _registration_token(client, unique_mobile())
    assert body["email_required"] is False
    created = await _set_password(client, body["registration_token"])
    assert created.status_code == 201
    assert created.json()["email_required"] is False


async def test_enforced_registration_requires_a_verified_email(
    client: AsyncClient, enforce
) -> None:
    enforce()
    mobile = unique_mobile()
    body = await _registration_token(client, mobile)
    assert body["email_required"] is True
    refused = await _set_password(client, body["registration_token"])
    assert refused.status_code == 400
    assert "email" in refused.json()["detail"]

    email = unique_email()
    upgraded = await _email_step(client, body["registration_token"], email)
    created = await _set_password(client, upgraded)
    assert created.status_code == 201, created.text
    assert created.json()["email_verified"] is True
    assert created.json()["email_required"] is False
    me = await client.get("/api/v1/auth/me", headers=headers(created.json()["access_token"]))
    assert me.json()["email"] == email


async def test_registration_email_code_is_bound_to_the_address(client: AsyncClient) -> None:
    body = await _registration_token(client, unique_mobile())
    sent = await client.post(
        "/api/v1/auth/register/email/initiate",
        json={"registration_token": body["registration_token"], "email": unique_email()},
    )
    other = await client.post(
        "/api/v1/auth/register/email/verify",
        json={
            "registration_token": body["registration_token"],
            "email": unique_email(),
            "otp": sent.json()["otp_hint"],
        },
    )
    assert other.status_code == 400


async def test_registration_email_steps_need_a_registration_token(client: AsyncClient) -> None:
    session_token, _ = await full_registration(client)
    for path in ("/api/v1/auth/register/email/initiate", "/api/v1/auth/register/email/verify"):
        refused = await client.post(
            path,
            json={"registration_token": session_token, "email": unique_email(), "otp": "123456"},
        )
        assert refused.status_code == 400, path


async def test_registration_with_an_address_verified_elsewhere_is_refused(
    client: AsyncClient,
) -> None:
    owner_token, _ = await full_registration(client)
    taken = await add_verified_email(client, owner_token)
    body = await _registration_token(client, unique_mobile())
    upgraded = await _email_step(client, body["registration_token"], taken)
    refused = await _set_password(client, upgraded)
    assert refused.status_code == 400
    assert "another account" in refused.json()["detail"]


# ---------------------------------------------------------------------------
# History access and erasure
# ---------------------------------------------------------------------------


async def test_history_is_platform_admin_only_and_never_the_owners(
    client: AsyncClient,
) -> None:
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    await add_verified_email(client, token)
    sql = "SELECT id FROM contact_change_history WHERE auth_user_uuid = :uid"
    assert (
        len(
            await as_api_user(
                sql,
                {"uid": uid},
                auth_user_uuid=str(uuid.uuid4()),
                role="admin",
                platform_scope="true",
            )
        )
        == 1
    )  # noqa: E501
    assert await as_api_user(sql, {"uid": uid}, auth_user_uuid=uid, role="client") == []
    for role, scope in (("admin", "false"), ("sub_admin", "true"), ("telecaller", "false")):
        assert (
            await as_api_user(
                sql, {"uid": uid}, auth_user_uuid=str(uuid.uuid4()), role=role, platform_scope=scope
            )
            == []
        ), role
    # The owner may read their own request rows, nobody but an Admin anyone else's.
    req_sql = "SELECT id FROM contact_change_requests WHERE auth_user_uuid = :uid"
    assert len(await as_api_user(req_sql, {"uid": uid}, auth_user_uuid=uid, role="client")) == 1
    assert (
        await as_api_user(req_sql, {"uid": uid}, auth_user_uuid=str(uuid.uuid4()), role="client")
        == []
    )


async def test_api_user_cannot_write_or_erase_history_outside_deletion(
    client: AsyncClient,
) -> None:
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    await add_verified_email(client, token)
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_api_user(
            "INSERT INTO contact_change_history (auth_user_uuid, field, new_value, method) "
            "VALUES (:uid, 'email', 'x@example.com', 'email_added')",
            {"uid": uid},
            auth_user_uuid=str(uuid.uuid4()),
            role="admin",
            platform_scope="true",
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        await as_api_user(
            "DELETE FROM contact_change_history WHERE auth_user_uuid = :uid",
            {"uid": uid},
            auth_user_uuid=uid,
            role="client",
        )
    # Even the owner or an Admin cannot erase it while the account is live.
    for actor, role, scope in ((uid, "client", "false"), (str(uuid.uuid4()), "admin", "true")):
        with pytest.raises(DBAPIError, match="only with the account"):
            await as_api_user(
                "SELECT erase_contact_change_data(:uid)",
                {"uid": uid},
                auth_user_uuid=actor,
                role=role,
                platform_scope=scope,
            )
    with pytest.raises(DBAPIError, match="not authorized"):
        await as_api_user(
            "SELECT erase_contact_change_data(:uid)",
            {"uid": uid},
            auth_user_uuid=str(uuid.uuid4()),
            role="client",
        )
    assert (
        len(
            await fetch_all(
                "SELECT id FROM contact_change_history WHERE auth_user_uuid = :uid", {"uid": uid}
            )
        )
        == 1
    )


async def test_contact_data_is_erased_with_the_account(client: AsyncClient) -> None:
    # Self-deletion.
    token, mobile = await full_registration(client)
    uid = await user_id(mobile)
    await add_verified_email(client, token)
    deleted = await client.request(
        "DELETE", "/api/v1/auth/me", headers=headers(token), json={"current_password": PASSWORD}
    )
    assert deleted.status_code == 200, deleted.text
    for table in ("contact_change_history", "contact_change_requests"):
        assert (
            await fetch_all(
                f"SELECT id FROM {table} WHERE auth_user_uuid = :uid",
                {"uid": uid},  # noqa: S608
            )
            == []
        )

    # Removal by a platform Admin.
    admin_token, _, _ = await make_admin(client)
    victim_token, victim_mobile = await full_registration(client)
    victim = await user_id(victim_mobile)
    await add_verified_email(client, victim_token)
    removed = await client.post(
        f"/api/v1/admin/users/{victim}/delete",
        json={"reason": "requested erasure"},
        headers=headers(admin_token),
    )
    assert removed.status_code == 200, removed.text
    assert (
        await fetch_all(
            "SELECT id FROM contact_change_history WHERE auth_user_uuid = :uid", {"uid": victim}
        )
        == []
    )


async def test_database_forbids_a_terminal_row_that_keeps_its_value(
    client: AsyncClient,
) -> None:
    _, mobile = await full_registration(client)
    uid = await user_id(mobile)
    with pytest.raises(IntegrityError):
        await execute(
            "INSERT INTO contact_change_requests "
            "(auth_user_uuid, kind, field, status, new_value, expires_at) VALUES "
            "(:uid, 'email_add', 'email', 'completed', 'kept@example.com', now())",
            {"uid": uid},
        )
    with pytest.raises(IntegrityError):  # a step from another journey
        await execute(
            "INSERT INTO contact_change_requests (auth_user_uuid, kind, field, status, expires_at) "
            "VALUES (:uid, 'email_add', 'email', 'pending_approval', now())",
            {"uid": uid},
        )
    with pytest.raises(IntegrityError):  # one active change per account
        for _ in range(2):
            await execute(
                "INSERT INTO contact_change_requests "
                "(auth_user_uuid, kind, field, status, expires_at) VALUES "
                "(:uid, 'self_service', 'email', 'awaiting_current_otp', now())",
                {"uid": uid},
            )


def test_role_token_helper_signs_claims_only() -> None:
    assert role_token(str(uuid.uuid4()), "client")
