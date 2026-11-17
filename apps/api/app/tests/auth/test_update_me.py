"""PATCH /api/v1/auth/me — client edits their own profile.

Covers success (name + GET reflects it), auth failure, validation, and the
CS-025 rule that email is never edited, changed or cleared here.

Requires: running Postgres + Redis (docker compose up -d).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from conftest import add_verified_email, full_registration, unique_email


@pytest.mark.asyncio
async def test_update_requires_auth(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/auth/me", json={"first_name": "New", "last_name": "Name"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_name_reflected_in_me(client: AsyncClient) -> None:
    token, _ = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Aarav"
    assert resp.json()["last_name"] == "Sharma"

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["first_name"] == "Aarav"
    assert me.json()["last_name"] == "Sharma"


@pytest.mark.asyncio
async def test_blank_name_is_422(client: AsyncClient) -> None:
    token, _ = await full_registration(client, lines=["loans"])
    resp = await client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"first_name": "   ", "last_name": "Sharma"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_email_cannot_be_changed_through_profile_edit(client: AsyncClient) -> None:
    """CS-025: an address is added with a code and changed through the
    contact-change flow; PATCH /auth/me refuses any different address."""
    token, _ = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "email": unique_email()},
    )
    assert resp.status_code == 422, resp.text
    assert "Change email" in resp.json()["detail"]
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["email"] is None
    assert me.json()["first_name"] != "Aarav"


@pytest.mark.asyncio
async def test_verified_email_cannot_be_changed_or_cleared_through_profile_edit(
    client: AsyncClient,
) -> None:
    token, _ = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    email = await add_verified_email(client, token)

    changed = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "email": unique_email()},
    )
    assert changed.status_code == 422
    cleared = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "email": None},
    )
    assert cleared.status_code == 422
    assert "removed" in cleared.json()["detail"]

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["email"] == email
    assert me.json()["email_verified"] is True


@pytest.mark.asyncio
async def test_echoing_the_email_on_file_is_a_no_op(client: AsyncClient) -> None:
    """Older clients send the address back unchanged with every profile save."""
    token, _ = await full_registration(client, lines=["loans"])
    headers = {"Authorization": f"Bearer {token}"}
    email = await add_verified_email(client, token)

    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Aarav", "last_name": "Sharma", "email": email.upper()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == email
    assert resp.json()["email_verified"] is True
    assert resp.json()["first_name"] == "Aarav"


@pytest.mark.asyncio
async def test_optional_profile_fields_can_be_saved_and_cleared(client: AsyncClient) -> None:
    token, _ = await full_registration(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "first_name": "Aarav",
        "last_name": "Sharma",
        "gender": "self_described",
        "gender_self_description": "Agender",
        "income_source": "business_income",
        "income_amount_minor": 12_500_000,
        "income_period": "annual",
        "occupation": "Textile business owner",
        "location": "Kondapur, Hyderabad",
    }

    saved = await client.patch("/api/v1/auth/me", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    for key, value in payload.items():
        assert saved.json()[key] == value

    cleared = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={
            "first_name": "Aarav",
            "last_name": "Sharma",
            "gender": None,
            "gender_self_description": None,
            "income_source": None,
            "income_amount_minor": None,
            "income_period": None,
            "occupation": None,
            "location": None,
        },
    )
    assert cleared.status_code == 200, cleared.text
    for key in (
        "gender",
        "gender_self_description",
        "income_source",
        "income_amount_minor",
        "income_period",
        "occupation",
        "location",
    ):
        assert cleared.json()[key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile",
    [
        {"gender": "self_described", "gender_self_description": None},
        {"gender": "female", "gender_self_description": "unexpected"},
        {"gender_self_description": None},
        {"income_source": "salaried", "income_amount_minor": 100_000},
        {
            "income_source": "net_salary",
            "income_amount_minor": 100_000,
            "income_period": "monthly",
        },
        {"income_source": None, "income_amount_minor": 100_000, "income_period": None},
        {"occupation": "   "},
        {"location": "   "},
    ],
)
async def test_inconsistent_optional_profile_values_are_422(
    client: AsyncClient, profile: dict
) -> None:
    token, _ = await full_registration(client)
    resp = await client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"first_name": "Aarav", "last_name": "Sharma", **profile},
    )
    assert resp.status_code == 422


async def _role_token(mobile: str, role: str) -> dict[str, str]:
    """A signed session for the same account under another role (claims only)."""
    from sqlalchemy import text

    import app.db.session as _session_mod
    from app.core.security import create_access_token

    async with _session_mod.AsyncSessionLocal() as db:
        uid = await db.scalar(text("SELECT id FROM auth_users WHERE mobile = :m"), {"m": mobile})
    token = create_access_token(
        {
            "sub": str(uid),
            "role": role,
            "business_line": "loans",
            "platform_scope": "true" if role == "admin" else "false",
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["telecaller", "employee", "sub_admin"])
async def test_admin_managed_staff_cannot_edit_their_profile(
    client: AsyncClient, role: str
) -> None:
    """CS-021: Telecaller, Employee and Sub Admin profiles are read-only."""
    token, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_token(mobile, role)

    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"first_name": "Changed", "last_name": "Name", "email": unique_email()},
    )
    assert resp.status_code == 403, resp.text
    assert "Admin" in resp.json()["detail"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["first_name"] != "Changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agent", "admin"])
async def test_agents_and_admins_keep_editing_their_profile(client: AsyncClient, role: str) -> None:
    _, mobile = await full_registration(client, lines=["loans"])
    headers = await _role_token(mobile, role)
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"first_name": "Kept", "last_name": "Editable"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Kept"
