"""CS-022 optional cancelled cheque on an Agent's payout details.

Upload type/size/ownership checks, replacement and removal, the bank-account
change rule, the audited payout-maker view, account erasure and the orphan
sweep. Storage is mocked: these tests never PUT real bytes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.cache.redis_keys import RedisCache
from app.models.agent_payout_details import AgentPayoutDetails
from app.models.audit_log import AuditAction, AuditLog
from app.services import agent_payout_cheque, storage
from app.tests.test_agent_api import _agent_token, _seed_agent
from app.tests.test_payouts_api import _admin_token, _make_admin

pytestmark = pytest.mark.asyncio

_BANK = {
    "account_holder_name": "Test Agent",
    "account_number": "50100123456789",
    "ifsc": "HDFC0001234",
    "bank_name": "HDFC Bank",
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session():
    import app.db.session as _session_mod

    return _session_mod.AsyncSessionLocal()


class _Storage:
    """Records deletes and answers head/sniff/canonicalize like a healthy store."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, size: int = 2048) -> None:
        self.deleted: list[str] = []
        self.size = size
        self.matches = True
        self.copies: list[tuple[str, str]] = []
        monkeypatch.setattr(storage, "head_object", lambda _key: self.size)
        monkeypatch.setattr(
            storage, "content_matches_declared_type", lambda _key, _ct: self.matches
        )
        monkeypatch.setattr(storage, "delete_object", self.deleted.append)

        def canonicalize(source: str, destination: str, _ct: str, *, max_bytes: int) -> int:
            assert max_bytes == 5 * 1024 * 1024
            self.copies.append((source, destination))
            return self.size

        monkeypatch.setattr(agent_payout_cheque, "canonicalize_object", canonicalize)


async def _agent_with_details(client: AsyncClient, *, bank: bool = True) -> tuple[str, str, str]:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    token = _agent_token(auth_uuid, agent_uuid)
    body: dict = {"upi_id": "agent@okhdfc"}
    if bank:
        body["bank"] = _BANK
    res = await client.put("/api/v1/agent/payout-details", json=body, headers=_headers(token))
    assert res.status_code == 200, res.text
    return auth_uuid, agent_uuid, token


async def _upload(client: AsyncClient, token: str, content_type: str = "image/jpeg") -> dict:
    presign = await client.post(
        "/api/v1/agent/payout-details/cheque/presign",
        json={"content_type": content_type},
        headers=_headers(token),
    )
    assert presign.status_code == 200, presign.text
    key = presign.json()["object_key"]
    res = await client.put(
        "/api/v1/agent/payout-details/cheque",
        json={"object_key": key, "content_type": content_type},
        headers=_headers(token),
    )
    assert res.status_code == 200, res.text
    return {"key": key, "body": res.json()}


async def _row(agent_uuid: str) -> AgentPayoutDetails | None:
    async with _session() as db:
        return await db.get(AgentPayoutDetails, uuid.UUID(agent_uuid))


async def test_presign_requires_saved_details_and_an_allowed_type(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    token = _agent_token(auth_uuid, agent_uuid)
    url = "/api/v1/agent/payout-details/cheque/presign"
    missing = await client.post(url, json={"content_type": "image/png"}, headers=_headers(token))
    assert missing.status_code == 409, missing.text

    _, agent_uuid, token = await _agent_with_details(client)
    for bad in ("image/webp", "image/gif", "text/html", "video/mp4"):
        res = await client.post(url, json={"content_type": bad}, headers=_headers(token))
        assert res.status_code == 422, bad
    ok = await client.post(url, json={"content_type": "application/pdf"}, headers=_headers(token))
    assert ok.status_code == 200, ok.text
    assert ok.headers["cache-control"] == "private, no-store"
    body = ok.json()
    assert body["max_bytes"] == 5 * 1024 * 1024
    assert body["object_key"].startswith(f"private/agent-payout-cheques/staging/{agent_uuid}/")
    assert body["object_key"].endswith("/cheque.pdf")


async def test_presign_is_rate_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, token = await _agent_with_details(client)

    async def over_limit(self, key: str, ttl: int) -> int:
        return agent_payout_cheque.PRESIGN_LIMIT_PER_HOUR + 1

    monkeypatch.setattr(RedisCache, "incr_with_expire", over_limit)
    res = await client.post(
        "/api/v1/agent/payout-details/cheque/presign",
        json={"content_type": "image/png"},
        headers=_headers(token),
    )
    assert res.status_code == 429, res.text


async def test_confirm_checks_ownership_size_and_bytes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    _, agent_uuid, token = await _agent_with_details(client)
    _, other_agent_uuid, _ = await _agent_with_details(client)
    url = "/api/v1/agent/payout-details/cheque"

    async def confirm(key: str, content_type: str = "image/jpeg") -> int:
        res = await client.put(
            url, json={"object_key": key, "content_type": content_type}, headers=_headers(token)
        )
        return res.status_code

    media = uuid.uuid4()
    # A key issued to another Agent, a wrong extension, or another prefix.
    assert (
        await confirm(f"private/agent-payout-cheques/staging/{other_agent_uuid}/{media}/cheque.jpg")
        == 400
    )
    assert (
        await confirm(f"private/agent-payout-cheques/staging/{agent_uuid}/{media}/cheque.png")
        == 400
    )
    assert (
        await confirm(f"private/loan-applications/staging/{agent_uuid}/{media}/cheque.jpg") == 400
    )
    assert (
        await confirm(
            f"private/agent-payout-cheques/staging/{agent_uuid}/{media}/cheque.jpg", "image/webp"
        )
        == 422
    )

    own_key = f"private/agent-payout-cheques/staging/{agent_uuid}/{media}/cheque.jpg"
    store.size = None  # type: ignore[assignment]
    assert await confirm(own_key) == 422
    store.size = 5 * 1024 * 1024 + 1
    assert await confirm(own_key) == 422
    store.size = 2048
    store.matches = False
    assert await confirm(own_key) == 422
    # A polyglot is removed at once rather than waiting for the sweep.
    assert own_key in store.deleted
    assert store.copies == []
    row = await _row(agent_uuid)
    assert row is not None and row.cheque_object_key is None


async def test_upload_replace_and_remove(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    _, agent_uuid, token = await _agent_with_details(client)

    first = await _upload(client, token, "image/jpeg")
    body = first["body"]
    assert body["cheque_content_type"] == "image/jpeg"
    assert body["cheque_uploaded_at"] is not None
    assert "cheque_object_key" not in body and "object_key" not in body
    staging, canonical = store.copies[-1]
    assert staging == first["key"]
    assert canonical.startswith(f"private/agent-payout-cheques/canonical/{agent_uuid}/")
    assert first["key"] in store.deleted  # staging removed after commit
    row = await _row(agent_uuid)
    assert row.cheque_object_key == canonical

    # Replaying the confirmed upload is refused.
    replay = await client.put(
        "/api/v1/agent/payout-details/cheque",
        json={"object_key": first["key"], "content_type": "image/jpeg"},
        headers=_headers(token),
    )
    assert replay.status_code == 400, replay.text

    # Replacing deletes the previous canonical object.
    second = await _upload(client, token, "application/pdf")
    assert second["body"]["cheque_content_type"] == "application/pdf"
    assert canonical in store.deleted
    new_canonical = (await _row(agent_uuid)).cheque_object_key
    assert new_canonical.endswith("/cheque.pdf")

    read = await client.get("/api/v1/agent/payout-details", headers=_headers(token))
    assert read.json()["cheque_content_type"] == "application/pdf"

    removed = await client.delete("/api/v1/agent/payout-details/cheque", headers=_headers(token))
    assert removed.status_code == 204, removed.text
    assert new_canonical in store.deleted
    row = await _row(agent_uuid)
    assert row.cheque_object_key is None and row.cheque_uploaded_at is None
    # The bank account and UPI ID stay.
    assert row.bank_hint is not None and row.upi_hint is not None
    again = await client.delete("/api/v1/agent/payout-details/cheque", headers=_headers(token))
    assert again.status_code == 404

    async with _session() as db:
        details = [
            audit.detail
            for audit in await db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.entity_uuid == uuid.UUID(agent_uuid),
                    AuditLog.action == AuditAction.AGENT_PAYOUT_DETAILS_UPDATED,
                )
                .order_by(AuditLog.created_at)
            )
        ]
    cheque_events = [d.get("cheque") for d in details if d and "cheque" in d]
    assert cheque_events == ["set", "replaced", "removed"]
    # Object keys never enter the audit trail.
    assert all("private/" not in str(d) for d in details)


async def test_bank_change_removes_the_cheque_but_upi_change_keeps_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    _, agent_uuid, token = await _agent_with_details(client)
    await _upload(client, token)
    canonical = (await _row(agent_uuid)).cheque_object_key

    upi = await client.put(
        "/api/v1/agent/payout-details", json={"upi_id": "new@okaxis"}, headers=_headers(token)
    )
    assert upi.status_code == 200
    assert upi.json()["cheque_uploaded_at"] is not None

    bank = await client.put(
        "/api/v1/agent/payout-details",
        json={"bank": {**_BANK, "account_number": "50100999999999"}},
        headers=_headers(token),
    )
    assert bank.status_code == 200, bank.text
    assert bank.json()["cheque_uploaded_at"] is None
    assert canonical in store.deleted
    assert (await _row(agent_uuid)).cheque_object_key is None


async def test_removing_payout_details_deletes_the_cheque(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    _, agent_uuid, token = await _agent_with_details(client)
    await _upload(client, token)
    canonical = (await _row(agent_uuid)).cheque_object_key
    res = await client.delete("/api/v1/agent/payout-details", headers=_headers(token))
    assert res.status_code == 204
    assert canonical in store.deleted


async def test_payout_maker_view_is_gated_and_audited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Storage(monkeypatch)
    auth_uuid, agent_uuid, token = await _agent_with_details(client)
    url = f"/api/v1/payouts/agents/{agent_uuid}/cancelled-cheque"
    admin_token, admin_uid = await _make_admin(client)

    # Nothing uploaded yet.
    assert (await client.get(url, headers=_headers(admin_token))).status_code == 404
    await _upload(client, token, "image/png")

    # The Agent, a plain Sub Admin and a client cannot open it.
    assert (await client.get(url, headers=_headers(token))).status_code == 403
    plain_sub_admin, _ = await _make_admin(client, role="sub_admin")
    assert (await client.get(url, headers=_headers(plain_sub_admin))).status_code == 403

    res = await client.get(url, headers=_headers(admin_token))
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "private, no-store"
    body = res.json()
    assert body["content_type"] == "image/png"
    assert body["url"].startswith("http")
    assert body["expires_in_seconds"] == 300

    granted, _ = await _make_admin(client, role="sub_admin", staff_features=["payout_requests"])
    by_recipient = await client.get(
        f"/api/v1/payouts/recipients/{auth_uuid}/cancelled-cheque", headers=_headers(granted)
    )
    assert by_recipient.status_code == 200, by_recipient.text

    prefill = await client.get(
        f"/api/v1/payouts/agents/{agent_uuid}/saved-destination", headers=_headers(admin_token)
    )
    assert prefill.json()["cheque_uploaded_at"] is not None

    # A maker asking for their own cheque is refused.
    own = await client.get(
        f"/api/v1/payouts/recipients/{auth_uuid}/cancelled-cheque",
        headers=_headers(_admin_token(auth_uuid)),
    )
    assert own.status_code == 403, own.text

    async with _session() as db:
        views = list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.entity_uuid == uuid.UUID(agent_uuid),
                    AuditLog.action == AuditAction.AGENT_PAYOUT_DETAILS_VIEWED,
                )
            )
        )
    cheque_views = [v for v in views if v.detail.get("purpose") == "cheque_view"]
    assert len(cheque_views) == 2
    assert {str(v.actor_uuid) for v in cheque_views} >= {admin_uid}
    assert all(v.detail["fields"] == ["cheque"] for v in cheque_views)
    assert all("private/" not in str(v.detail) for v in cheque_views)


async def test_cheque_is_erased_with_the_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    auth_uuid, agent_uuid, token = await _agent_with_details(client)
    await _upload(client, token)
    canonical = (await _row(agent_uuid)).cheque_object_key
    admin_token, _ = await _make_admin(client)
    res = await client.post(
        f"/api/v1/admin/users/{auth_uuid}/delete",
        json={"reason": "requested erasure"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 200, res.text
    assert await _row(agent_uuid) is None
    assert canonical in store.deleted


async def test_orphan_sweep_keeps_referenced_cheques(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _Storage(monkeypatch)
    _, agent_uuid, token = await _agent_with_details(client)
    await _upload(client, token)
    referenced = (await _row(agent_uuid)).cheque_object_key
    old = datetime.now(UTC) - timedelta(hours=3)
    fresh = datetime.now(UTC)
    orphan = f"private/agent-payout-cheques/staging/{agent_uuid}/{uuid.uuid4()}/cheque.jpg"
    in_flight = f"private/agent-payout-cheques/staging/{agent_uuid}/{uuid.uuid4()}/cheque.png"
    monkeypatch.setattr(
        storage,
        "list_objects",
        lambda prefix: (
            [
                {"key": referenced, "last_modified": old},
                {"key": orphan, "last_modified": old},
                {"key": in_flight, "last_modified": fresh},
            ]
            if prefix == "private/agent-payout-cheques/"
            else []
        ),
    )
    store.deleted.clear()
    summary = await agent_payout_cheque.purge_orphaned_uploads()
    assert summary == {"scanned": 3, "deleted": 1}
    assert store.deleted == [orphan]
