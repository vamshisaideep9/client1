"""Agent dashboard refinements (2026-11-14).

- Lead name is required on introduction and cannot be cleared.
- Same-Agent resubmission of an expired lead (amends FR-4.6), enforced by the
  service and by the expiry trigger.
- 7-day expiry reminder job.
- Encrypted Agent payout details: owner-only API, masked reads, audited
  payout-maker prefill, and erasure.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core import field_crypto
from app.models.agent_payout_details import AgentPayoutDetails
from app.models.audit_log import AuditAction, AuditLog
from app.models.lead import Lead, LeadOrigin, LeadStatus
from app.models.notification import Notification, NotificationType
from app.services.leads import is_agent_lead_resubmittable
from app.tests.test_agent_api import _agent_token, _seed_agent
from conftest import full_registration, unique_mobile


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_expired_lead(
    agent_profile_uuid: str,
    *,
    status: LeadStatus = LeadStatus.RELEASED,
    mobile: str | None = None,
) -> tuple[str, str]:
    import app.db.session as _session_mod

    now = datetime.now(UTC)
    mobile = mobile or unique_mobile()
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=mobile,
            name="Expired Client",
            business_line="loans",
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=uuid.UUID(agent_profile_uuid),
            status=status,
            expires_at=now - timedelta(minutes=5),
            agent_expired_at=now - timedelta(minutes=1),
            released_at=now,
            release_reason="Agent ownership window expired.",
        )
        db.add(lead)
        await db.commit()
        return str(lead.id), mobile


async def _load_lead(lead_id: str) -> Lead:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        lead = await db.get(Lead, uuid.UUID(lead_id))
        assert lead is not None
        return lead


# ---------------------------------------------------------------------------
# 1. Lead name is required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"name": None}, {"name": ""}, {"name": "   "}])
async def test_introduce_lead_requires_a_name(client: AsyncClient, body: dict) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    res = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), **body},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_introduce_lead_trims_the_name(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    res = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), "name": "  Ravi Kumar  "},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Ravi Kumar"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "", "  "])
async def test_agent_cannot_clear_a_lead_name(client: AsyncClient, name: str | None) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    created = await client.post(
        "/api/v1/agent/leads",
        json={"mobile": unique_mobile(), "name": "Ravi"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    res = await client.patch(
        f"/api/v1/agent/leads/{created.json()['id']}", json={"name": name}, headers=headers
    )
    assert res.status_code == 422, res.text


# ---------------------------------------------------------------------------
# 2. Resubmit after expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_original_agent_can_resubmit_an_expired_lead(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    lead_id, _ = await _seed_expired_lead(agent_uuid)

    before = await client.get(f"/api/v1/agent/leads/{lead_id}", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["status"] == "expired"
    assert before.json()["resubmittable"] is True

    started = datetime.now(UTC)
    res = await client.post(f"/api/v1/agent/leads/{lead_id}/resubmit", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] != "expired"
    assert body["expired_at"] is None
    assert body["resubmittable"] is False
    new_deadline = datetime.fromisoformat(body["expires_at"])
    assert started + timedelta(days=29) < new_deadline < started + timedelta(days=31)

    lead = await _load_lead(lead_id)
    assert lead.agent_expired_at is None
    assert lead.resubmit_count == 1
    assert lead.expiry_reminder_sent_at is None

    async with _session_mod.AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.entity_uuid == uuid.UUID(lead_id),
                AuditLog.action == AuditAction.AGENT_LEAD_RESUBMITTED,
            )
        )
    assert audit is not None
    assert audit.actor_uuid == uuid.UUID(auth_uuid)
    assert audit.detail["resubmit_count"] == 1

    # A second resubmit while the new window is live is refused.
    again = await client.post(f"/api/v1/agent/leads/{lead_id}/resubmit", headers=headers)
    assert again.status_code == 409, again.text


@pytest.mark.asyncio
async def test_another_agent_cannot_resubmit(client: AsyncClient) -> None:
    _auth_uuid, agent_uuid = await _seed_agent("loans")
    lead_id, _ = await _seed_expired_lead(agent_uuid)
    other_auth, other_agent = await _seed_agent("loans")

    res = await client.post(
        f"/api/v1/agent/leads/{lead_id}/resubmit",
        headers=_headers(_agent_token(other_auth, other_agent)),
    )
    assert res.status_code == 404, res.text
    assert (await _load_lead(lead_id)).agent_expired_at is not None


@pytest.mark.asyncio
async def test_lead_that_has_not_expired_cannot_be_resubmitted(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))
    created = await client.post(
        "/api/v1/agent/leads", json={"mobile": unique_mobile(), "name": "Live"}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["resubmittable"] is False
    res = await client.post(f"/api/v1/agent/leads/{created.json()['id']}/resubmit", headers=headers)
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_converted_lead_cannot_be_resubmitted(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    lead_id, _ = await _seed_expired_lead(agent_uuid, status=LeadStatus.CONVERTED)
    res = await client.post(
        f"/api/v1/agent/leads/{lead_id}/resubmit",
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_registered_mobile_cannot_be_resubmitted(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.user import User

    auth_uuid, agent_uuid = await _seed_agent("loans")
    lead_id, mobile = await _seed_expired_lead(agent_uuid)
    async with _session_mod.AsyncSessionLocal() as db:
        db.add(
            User(
                first_name="Now",
                last_name="Registered",
                mobile=mobile,
                email=f"reg_{uuid.uuid4().hex[:12]}@example.com",
                password_hash="x",
            )
        )
        await db.commit()

    res = await client.post(
        f"/api/v1/agent/leads/{lead_id}/resubmit",
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 409, res.text
    assert (await _load_lead(lead_id)).agent_expired_at is not None


def test_resubmittable_requires_unregistered_open_expired_agent_lead() -> None:
    now = datetime.now(UTC)
    base = {
        "mobile": "+919999999999",
        "business_line": "loans",
        "origin_agent_profile_uuid": uuid.uuid4(),
        "status": LeadStatus.RELEASED,
        "agent_expired_at": now,
    }
    assert is_agent_lead_resubmittable(Lead(**base)) is True
    assert is_agent_lead_resubmittable(Lead(**{**base, "agent_expired_at": None})) is False
    assert (
        is_agent_lead_resubmittable(Lead(**{**base, "client_profile_uuid": uuid.uuid4()})) is False
    )
    assert is_agent_lead_resubmittable(Lead(**{**base, "status": LeadStatus.CLOSED})) is False
    assert is_agent_lead_resubmittable(Lead(**{**base, "origin_agent_profile_uuid": None})) is False


@pytest.mark.asyncio
async def test_trigger_still_blocks_expiry_reset_without_the_resubmit_contract() -> None:
    import app.db.session as _session_mod

    _auth_uuid, agent_uuid = await _seed_agent("loans")
    lead_id, _ = await _seed_expired_lead(agent_uuid)
    reset = (
        "UPDATE leads SET agent_expired_at = NULL, "
        "expires_at = now() + interval '30 days'{extra} WHERE id = :id"
    )

    # No flag: the original immutability rule applies.
    async with _session_mod.AsyncSessionLocal() as db:
        with pytest.raises(Exception, match="immutable"):
            await db.execute(
                text(reset.format(extra=", resubmit_count = resubmit_count + 1")),
                {"id": lead_id},
            )
        await db.rollback()

    # Flag set but the resubmission counter is not advanced: still refused.
    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.agent_lead_resubmit', 'on', true)"))
        with pytest.raises(Exception, match="immutable"):
            await db.execute(text(reset.format(extra="")), {"id": lead_id})
        await db.rollback()

    # Flag set but the origin Agent changes: still refused.
    other_auth, other_agent = await _seed_agent("loans")
    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.agent_lead_resubmit', 'on', true)"))
        with pytest.raises(Exception, match="immutable"):
            await db.execute(
                text(
                    reset.format(
                        extra=", resubmit_count = resubmit_count + 1, "
                        "origin_agent_profile_uuid = :other"
                    )
                ),
                {"id": lead_id, "other": other_agent},
            )
        await db.rollback()

    assert (await _load_lead(lead_id)).agent_expired_at is not None


# ---------------------------------------------------------------------------
# 2b. Seven-day reminder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reminder_fires_once_inside_the_last_seven_days() -> None:
    import app.db.session as _session_mod
    from app.jobs.remind_agent_lead_expiry import remind_agent_lead_expiry

    auth_uuid, agent_uuid = await _seed_agent("loans")
    now = datetime.now(UTC)

    async def seed(expires_in: timedelta) -> str:
        async with _session_mod.AsyncSessionLocal() as db:
            lead = Lead(
                mobile=unique_mobile(),
                name="Reminder",
                business_line="loans",
                origin=LeadOrigin.AGENT,
                origin_agent_profile_uuid=uuid.UUID(agent_uuid),
                status=LeadStatus.NEW,
                expires_at=now + expires_in,
            )
            db.add(lead)
            await db.commit()
            return str(lead.id)

    due_id = await seed(timedelta(days=6, hours=12))
    early_id = await seed(timedelta(days=10))

    await remind_agent_lead_expiry()
    due = await _load_lead(due_id)
    assert due.expiry_reminder_sent_at is not None
    assert (await _load_lead(early_id)).expiry_reminder_sent_at is None

    stamped = due.expiry_reminder_sent_at
    await remind_agent_lead_expiry()
    assert (await _load_lead(due_id)).expiry_reminder_sent_at == stamped

    async with _session_mod.AsyncSessionLocal() as db:
        reminders = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_uuid == uuid.UUID(auth_uuid),
                    Notification.type == NotificationType.AGENT_LEAD_EXPIRY_REMINDER,
                )
            )
        ).all()
    assert [n.href for n in reminders] == [f"/dashboard/leads/{due_id}"]


@pytest.mark.asyncio
async def test_reminder_skips_registered_clients_and_terminal_leads() -> None:
    import app.db.session as _session_mod
    from app.jobs.remind_agent_lead_expiry import remind_agent_lead_expiry

    _auth_uuid, agent_uuid = await _seed_agent("loans")
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=unique_mobile(),
            name="Converted",
            business_line="loans",
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=uuid.UUID(agent_uuid),
            status=LeadStatus.CONVERTED,
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        db.add(lead)
        await db.commit()
        lead_id = str(lead.id)

    await remind_agent_lead_expiry()
    assert (await _load_lead(lead_id)).expiry_reminder_sent_at is None


# ---------------------------------------------------------------------------
# 3. Payout details
# ---------------------------------------------------------------------------

_BANK = {
    "account_holder_name": "Test Agent",
    "account_number": "50100123456789",
    "ifsc": "hdfc0001234",
    "bank_name": "HDFC Bank",
}


@pytest.mark.asyncio
async def test_agent_saves_masked_payout_details(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    auth_uuid, agent_uuid = await _seed_agent("loans")
    headers = _headers(_agent_token(auth_uuid, agent_uuid))

    empty = await client.get("/api/v1/agent/payout-details", headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["saved"] is False
    assert empty.json()["available"] is True

    upi = await client.put(
        "/api/v1/agent/payout-details", json={"upi_id": "9876543210@okhdfc"}, headers=headers
    )
    assert upi.status_code == 200, upi.text
    assert upi.json()["upi_hint"] == "***@okhdfc"
    assert upi.json()["bank_hint"] is None
    assert "9876543210" not in upi.text

    both = await client.put("/api/v1/agent/payout-details", json={"bank": _BANK}, headers=headers)
    assert both.status_code == 200, both.text
    assert both.json()["upi_hint"] == "***@okhdfc"
    assert both.json()["bank_hint"] == "HDFC ****6789"
    assert "50100123456789" not in both.text

    async with _session_mod.AsyncSessionLocal() as db:
        row = await db.get(AgentPayoutDetails, uuid.UUID(agent_uuid))
    assert row is not None
    assert row.auth_user_uuid == uuid.UUID(auth_uuid)
    assert b"9876543210" not in row.upi_ciphertext
    assert b"50100123456789" not in row.bank_ciphertext

    # Removing one keeps the other; removing the last one is refused.
    no_upi = await client.put(
        "/api/v1/agent/payout-details", json={"upi_id": None}, headers=headers
    )
    assert no_upi.status_code == 200, no_upi.text
    assert no_upi.json()["upi_hint"] is None
    assert no_upi.json()["bank_hint"] == "HDFC ****6789"
    none_left = await client.put(
        "/api/v1/agent/payout-details", json={"bank": None}, headers=headers
    )
    assert none_left.status_code == 422, none_left.text

    deleted = await client.delete("/api/v1/agent/payout-details", headers=headers)
    assert deleted.status_code == 204, deleted.text
    after = await client.get("/api/v1/agent/payout-details", headers=headers)
    assert after.json()["saved"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"upi_id": "not-a-upi"},
        {"bank": {**_BANK, "ifsc": "HDFC1234567"}},
        {"bank": {**_BANK, "account_number": "12AB"}},
        {"bank": {**_BANK, "account_holder_name": "  "}},
    ],
)
async def test_payout_details_validation(client: AsyncClient, body: dict) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    res = await client.put(
        "/api/v1/agent/payout-details",
        json=body,
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_payout_details_are_isolated_between_agents(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    auth_a, agent_a = await _seed_agent("loans")
    auth_b, agent_b = await _seed_agent("loans")
    saved = await client.put(
        "/api/v1/agent/payout-details",
        json={"upi_id": "agenta@okaxis"},
        headers=_headers(_agent_token(auth_a, agent_a)),
    )
    assert saved.status_code == 200, saved.text

    other = await client.get(
        "/api/v1/agent/payout-details", headers=_headers(_agent_token(auth_b, agent_b))
    )
    assert other.json()["saved"] is False

    # RLS: Agent B's database context cannot read or delete Agent A's row.
    async with _session_mod.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL ROLE api_user"))
        await db.execute(
            text(
                "SELECT set_config('app.role', 'agent', true), "
                "set_config('app.auth_user_uuid', :u, true), "
                "set_config('app.agent_profile_uuid', :p, true)"
            ),
            {"u": auth_b, "p": agent_b},
        )
        visible = (await db.execute(text("SELECT count(*) FROM agent_payout_details"))).scalar()
        removed = (
            await db.execute(
                text("DELETE FROM agent_payout_details WHERE agent_profile_uuid = :a"),
                {"a": agent_a},
            )
        ).rowcount
        await db.rollback()
    assert visible == 0
    assert removed == 0


@pytest.mark.asyncio
async def test_non_agents_cannot_use_agent_payout_details(client: AsyncClient) -> None:
    token, _ = await full_registration(client, lines=["loans"])
    res = await client.get("/api/v1/agent/payout-details", headers=_headers(token))
    assert res.status_code == 403, res.text


async def _payout_maker(
    client: AsyncClient, *, role: str = "admin", staff_features: list[str] | None = None
) -> tuple[str, str]:
    from app.tests.test_payouts_api import _make_admin

    return await _make_admin(client, role=role, staff_features=staff_features)


@pytest.mark.asyncio
async def test_payout_maker_prefill_is_decrypted_and_audited(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    auth_uuid, agent_uuid = await _seed_agent("loans")
    await client.put(
        "/api/v1/agent/payout-details",
        json={"upi_id": "9876543210@okhdfc", "bank": _BANK},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    admin_token, admin_uid = await _payout_maker(client)

    res = await client.get(
        f"/api/v1/payouts/recipients/{auth_uuid}/saved-destination",
        headers=_headers(admin_token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["upi_id"] == "9876543210@okhdfc"
    assert res.json()["bank"]["account_number"] == "50100123456789"
    assert res.json()["bank"]["ifsc"] == "HDFC0001234"

    async with _session_mod.AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_uuid == uuid.UUID(agent_uuid),
                AuditLog.action == AuditAction.AGENT_PAYOUT_DETAILS_VIEWED,
            )
            .order_by(AuditLog.created_at.desc())
        )
    assert audit is not None
    assert audit.actor_uuid == uuid.UUID(admin_uid)
    assert sorted(audit.detail["fields"]) == ["bank", "upi"]
    assert "50100123456789" not in str(audit.detail)


@pytest.mark.asyncio
async def test_prefill_access_rules(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    agent_headers = _headers(_agent_token(auth_uuid, agent_uuid))
    await client.put(
        "/api/v1/agent/payout-details", json={"upi_id": "agent@okaxis"}, headers=agent_headers
    )
    url = f"/api/v1/payouts/recipients/{auth_uuid}/saved-destination"

    # The Agent themself, and a Sub Admin without the payout grant, are refused.
    assert (await client.get(url, headers=agent_headers)).status_code == 403
    plain_sub_admin, _ = await _payout_maker(client, role="sub_admin")
    assert (await client.get(url, headers=_headers(plain_sub_admin))).status_code == 403

    # A granted Sub Admin may prefill.
    granted, _ = await _payout_maker(client, role="sub_admin", staff_features=["payout_requests"])
    assert (await client.get(url, headers=_headers(granted))).status_code == 200

    # Nothing saved -> 404; self -> 403.
    admin_token, admin_uid = await _payout_maker(client)
    other_auth, _ = await _seed_agent("loans")
    missing = await client.get(
        f"/api/v1/payouts/recipients/{other_auth}/saved-destination", headers=_headers(admin_token)
    )
    assert missing.status_code == 404, missing.text
    self_read = await client.get(
        f"/api/v1/payouts/recipients/{admin_uid}/saved-destination", headers=_headers(admin_token)
    )
    assert self_read.status_code == 403, self_read.text


@pytest.mark.asyncio
async def test_account_erasure_function_removes_payout_details(client: AsyncClient) -> None:
    import app.db.session as _session_mod

    auth_uuid, agent_uuid = await _seed_agent("loans")
    await client.put(
        "/api/v1/agent/payout-details",
        json={"upi_id": "erase@okaxis"},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )

    async def call_as(role: str, user_uuid: str, platform_scope: str = "false"):
        async with _session_mod.AsyncSessionLocal() as db:
            await db.execute(text("SET LOCAL ROLE api_user"))
            await db.execute(
                text(
                    "SELECT set_config('app.role', :r, true), "
                    "set_config('app.auth_user_uuid', :u, true), "
                    "set_config('app.platform_scope', :s, true)"
                ),
                {"r": role, "u": user_uuid, "s": platform_scope},
            )
            result = await db.scalar(
                text("SELECT erase_agent_payout_details(CAST(:t AS uuid))"), {"t": auth_uuid}
            )
            await db.commit()
            return result

    # Another non-admin user is refused.
    with pytest.raises(Exception, match="not authorized"):
        await call_as("client", str(uuid.uuid4()))
    # The owner, from any role, can erase.
    assert await call_as("client", auth_uuid) is True

    async with _session_mod.AsyncSessionLocal() as db:
        assert await db.get(AgentPayoutDetails, uuid.UUID(agent_uuid)) is None


def test_field_cipher_round_trip_and_tamper_detection() -> None:
    aad = b"agent-payout-details:test:upi"
    blob = field_crypto.encrypt("someone@okaxis", associated_data=aad)
    assert field_crypto.decrypt(blob, associated_data=aad) == "someone@okaxis"
    assert b"someone" not in blob

    with pytest.raises(field_crypto.FieldDecryptionError):
        field_crypto.decrypt(blob, associated_data=b"agent-payout-details:other:upi")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(field_crypto.FieldDecryptionError):
        field_crypto.decrypt(tampered, associated_data=aad)


def test_field_cipher_fails_closed_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "PAYOUT_DETAILS_ENCRYPTION_KEY", "")
    assert field_crypto.is_available() is False
    with pytest.raises(field_crypto.FieldCipherUnavailable):
        field_crypto.encrypt("x@y", associated_data=b"a")

    monkeypatch.setattr(
        settings, "PAYOUT_DETAILS_ENCRYPTION_KEY", base64.b64encode(b"k" * 32).decode()
    )
    assert field_crypto.is_available() is True


def test_settings_reject_a_malformed_encryption_key() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="32 bytes"):
        Settings(PAYOUT_DETAILS_ENCRYPTION_KEY=base64.b64encode(b"short").decode())
    with pytest.raises(ValueError, match="base64"):
        Settings(PAYOUT_DETAILS_ENCRYPTION_KEY="not base64!!")


@pytest.mark.asyncio
async def test_commission_prefill_by_agent_profile(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    await client.put(
        "/api/v1/agent/payout-details",
        json={"bank": _BANK},
        headers=_headers(_agent_token(auth_uuid, agent_uuid)),
    )
    admin_token, _ = await _payout_maker(client)

    res = await client.get(
        f"/api/v1/payouts/agents/{agent_uuid}/saved-destination", headers=_headers(admin_token)
    )
    assert res.status_code == 200, res.text
    assert res.json()["upi_id"] is None
    assert res.json()["bank"]["account_holder_name"] == "Test Agent"

    unknown = await client.get(
        f"/api/v1/payouts/agents/{uuid.uuid4()}/saved-destination", headers=_headers(admin_token)
    )
    assert unknown.status_code == 404, unknown.text


@pytest.mark.asyncio
async def test_payout_detail_reads_are_not_cacheable(client: AsyncClient) -> None:
    auth_uuid, agent_uuid = await _seed_agent("loans")
    agent_headers = _headers(_agent_token(auth_uuid, agent_uuid))
    await client.put(
        "/api/v1/agent/payout-details", json={"upi_id": "cache@okaxis"}, headers=agent_headers
    )
    own = await client.get("/api/v1/agent/payout-details", headers=agent_headers)
    assert own.headers["cache-control"] == "private, no-store"

    admin_token, _ = await _payout_maker(client)
    for url in (
        f"/api/v1/payouts/recipients/{auth_uuid}/saved-destination",
        f"/api/v1/payouts/agents/{agent_uuid}/saved-destination",
    ):
        res = await client.get(url, headers=_headers(admin_token))
        assert res.status_code == 200, res.text
        assert res.headers["cache-control"] == "private, no-store"
