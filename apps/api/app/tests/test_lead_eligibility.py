"""Lead and referral eligibility (CS-024, batch D).

Covers the derived eligibility of accepted Agent leads and referrals, the
``lead_intake_attempts`` record of rejected introductions and referral
sign-ups (written outside the rejected transaction, never the raw number),
owner-only RLS, the summary counts, the "Not accepted" lists, and erasure with
the owner's account. Requires Postgres + Redis (Docker stack).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token
from app.models.lead_intake_attempt import IntakeActorType
from app.models.referral import ReferralStatus
from app.schemas.eligibility import EligibilityReasonLiteral
from app.services.eligibility import (
    ATTEMPT_OUTCOME,
    REASON_LABEL,
    EligibilityReason,
    agent_lead_eligibility,
    referral_eligibility,
)
from app.services.lead_intake_attempts import mobile_fingerprint, mobile_last4, record_attempt
from conftest import PASSWORD, full_registration, unique_mobile

_CONFLICT_DETAIL = "This mobile number is already linked to an existing enquiry."


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_every_reason_has_one_label_and_matches_the_contract() -> None:
    assert set(REASON_LABEL) == set(EligibilityReason)
    assert all(label.strip() for label in REASON_LABEL.values())
    assert {reason.value for reason in EligibilityReason} == set(get_args(EligibilityReasonLiteral))
    assert set(ATTEMPT_OUTCOME) == {
        EligibilityReason.ALREADY_LINKED,
        EligibilityReason.OWN_LEAD_WINDOW_ENDED,
        EligibilityReason.ALREADY_REFERRED,
        EligibilityReason.SELF_REFERRAL,
    }


def test_agent_lead_is_not_eligible_only_once_its_window_expired() -> None:
    assert agent_lead_eligibility(None) == ("eligible", None)
    assert agent_lead_eligibility(datetime.now(UTC)) == (
        "not_eligible",
        EligibilityReason.ATTRIBUTION_EXPIRED,
    )


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (ReferralStatus.PENDING, None, ("eligible", None)),
        (ReferralStatus.CONVERTED, "no_active_config", ("eligible", None)),
        (ReferralStatus.ACCRUED, "accrued", ("eligible", None)),
        (ReferralStatus.PAID, "accrued", ("eligible", None)),
        (ReferralStatus.VOID, "self_referral", ("not_eligible", EligibilityReason.SELF_REFERRAL)),
        (
            ReferralStatus.VOID,
            "referrer_not_client",
            ("not_eligible", EligibilityReason.REFERRER_NOT_CLIENT),
        ),
        (
            ReferralStatus.CONVERTED,
            "below_min_conversion",
            ("not_eligible", EligibilityReason.BELOW_MIN_CONVERSION),
        ),
        (ReferralStatus.CONVERTED, "cap_reached", ("not_eligible", EligibilityReason.CAP_REACHED)),
        (ReferralStatus.VOID, None, ("not_eligible", EligibilityReason.VOIDED)),
    ],
)
def test_referral_eligibility_mapping(status, reason, expected) -> None:  # noqa: ANN001
    assert referral_eligibility(status, reason) == expected


def test_mobile_fingerprint_is_keyed_and_purpose_bound() -> None:
    mobile = "+919876543210"
    fingerprint = mobile_fingerprint(mobile)
    assert len(fingerprint) == 64
    assert fingerprint == mobile_fingerprint(mobile)
    assert fingerprint != hashlib.sha256(mobile.encode()).hexdigest()
    assert (
        fingerprint
        == hmac.new(
            settings.SECRET_KEY.encode(), f"lead-intake-mobile:{mobile}".encode(), hashlib.sha256
        ).hexdigest()
    )
    assert mobile_last4(mobile) == "3210"
    assert mobile_last4("12") is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _auth_user_uuid(mobile: str) -> str:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        row = (
            await db.execute(text("SELECT id FROM auth_users WHERE mobile = :m"), {"m": mobile})
        ).fetchone()
        assert row is not None
        return str(row[0])


async def _seed_agent(business_line: str = "loans") -> tuple[str, str, str]:
    """Returns (auth_user_uuid, agent_profile_uuid, token)."""
    import app.db.session as _session_mod
    from app.models.profile import AgentProfile, ProfileStatus
    from app.models.user import User

    async with _session_mod.AsyncSessionLocal() as db:
        user = User(
            first_name="Test",
            last_name="Agent",
            mobile=unique_mobile(),
            email=f"ag_{uuid.uuid4().hex[:12]}@example.com",
            password_hash="x",
        )
        db.add(user)
        await db.flush()
        profile = AgentProfile(
            auth_user_uuid=user.id,
            agent_code=f"AG-{uuid.uuid4().hex[:8]}",
            business_line=business_line,
            status=ProfileStatus.ACTIVE,
        )
        db.add(profile)
        await db.commit()
        auth_uuid, agent_uuid = str(user.id), str(profile.id)
    token = create_access_token(
        {
            "sub": auth_uuid,
            "role": "agent",
            "business_line": business_line,
            "agent_profile_uuid": agent_uuid,
            "platform_scope": "false",
        }
    )
    return auth_uuid, agent_uuid, token


async def _seed_expired_lead(agent_profile_uuid: str, mobile: str) -> str:
    import app.db.session as _session_mod
    from app.models.lead import Lead, LeadOrigin, LeadStatus

    now = datetime.now(UTC)
    async with _session_mod.AsyncSessionLocal() as db:
        lead = Lead(
            mobile=mobile,
            name="Expired Client",
            business_line="loans",
            origin=LeadOrigin.AGENT,
            origin_agent_profile_uuid=uuid.UUID(agent_profile_uuid),
            status=LeadStatus.RELEASED,
            expires_at=now - timedelta(minutes=5),
            agent_expired_at=now - timedelta(minutes=1),
            released_at=now,
            release_reason="Agent ownership window expired.",
        )
        db.add(lead)
        await db.commit()
        return str(lead.id)


async def _attempt_rows(where: str, params: dict) -> list[dict]:
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        rows = await db.execute(text(f"SELECT * FROM lead_intake_attempts WHERE {where}"), params)
        return [dict(row) for row in rows.mappings()]


async def _agent_rows(agent_profile_uuid: str) -> list[dict]:
    return await _attempt_rows(
        "actor_type = 'agent' AND actor_uuid = :a", {"a": agent_profile_uuid}
    )


async def _referrer_rows(auth_user_uuid: str) -> list[dict]:
    return await _attempt_rows("actor_type = 'referrer' AND actor_uuid = :a", {"a": auth_user_uuid})


async def _introduce(client: AsyncClient, token: str, mobile: str):  # noqa: ANN202
    return await client.post(
        "/api/v1/agent/leads",
        json={"mobile": mobile, "name": "Prospect"},
        headers=_headers(token),
    )


async def _my_code(client: AsyncClient, token: str) -> str:
    res = await client.get("/api/v1/referrals/me", headers=_headers(token))
    assert res.status_code == 200, res.text
    return res.json()["code"]


def _assert_no_raw_mobile(row: dict, mobile: str) -> None:
    national = mobile.removeprefix("+")
    for column, value in row.items():
        assert national[-10:] not in str(value), f"{column} holds the raw number"


# ---------------------------------------------------------------------------
# Agent introductions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_number_is_recorded_as_duplicate_without_the_raw_number(
    client: AsyncClient,
) -> None:
    _, registered_mobile = await full_registration(client, lines=["loans"])
    auth_uuid, agent_uuid, token = await _seed_agent()

    res = await _introduce(client, token, registered_mobile)
    assert res.status_code == 409
    assert res.json() == {"detail": _CONFLICT_DETAIL}

    rows = await _agent_rows(agent_uuid)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "duplicate"
    assert row["reason_code"] == "already_linked"
    assert str(row["auth_user_uuid"]) == auth_uuid
    assert row["business_line"] == "loans"
    assert row["mobile_last4"] == registered_mobile[-4:]
    assert row["mobile_fingerprint"] == mobile_fingerprint(registered_mobile)
    _assert_no_raw_mobile(row, registered_mobile)

    # The capture transaction itself was rolled back: no lead for the Agent.
    import app.db.session as _session_mod

    async with _session_mod.AsyncSessionLocal() as db:
        attributed = await db.scalar(
            text("SELECT count(*) FROM leads WHERE origin_agent_profile_uuid = :a"),
            {"a": agent_uuid},
        )
    assert attributed == 0


@pytest.mark.asyncio
async def test_another_agents_lead_is_a_duplicate_and_reveals_no_owner(
    client: AsyncClient,
) -> None:
    _, agent_a, token_a = await _seed_agent()
    _, agent_b, token_b = await _seed_agent()
    mobile = unique_mobile()
    assert (await _introduce(client, token_a, mobile)).status_code == 201

    res = await _introduce(client, token_b, mobile)
    assert res.status_code == 409
    assert res.json() == {"detail": _CONFLICT_DETAIL}

    assert await _agent_rows(agent_a) == []
    listed = await client.get("/api/v1/agent/lead-attempts", headers=_headers(token_b))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    (attempt,) = body["attempts"]
    assert attempt["outcome"] == "duplicate"
    assert attempt["reason"] == "already_linked"
    assert attempt["reason_label"] == REASON_LABEL[EligibilityReason.ALREADY_LINKED]
    assert attempt["mobile_masked"] == f"***{mobile[-4:]}"
    assert attempt["business_line"] == "loans"
    assert set(attempt) == {
        "id",
        "outcome",
        "reason",
        "reason_label",
        "mobile_masked",
        "business_line",
        "created_at",
    }
    assert agent_a not in str(body)

    own = await client.get("/api/v1/agent/lead-attempts", headers=_headers(token_a))
    assert own.json() == {"attempts": [], "total": 0}


@pytest.mark.asyncio
async def test_own_expired_lead_is_not_eligible_but_someone_elses_is_a_duplicate(
    client: AsyncClient,
) -> None:
    _, agent_a, token_a = await _seed_agent()
    _, agent_b, token_b = await _seed_agent()
    mobile = unique_mobile()
    await _seed_expired_lead(agent_a, mobile)

    assert (await _introduce(client, token_a, mobile)).status_code == 409
    assert (await _introduce(client, token_b, mobile)).status_code == 409

    (own,) = await _agent_rows(agent_a)
    assert (own["outcome"], own["reason_code"]) == ("not_eligible", "own_lead_window_ended")
    (other,) = await _agent_rows(agent_b)
    assert (other["outcome"], other["reason_code"]) == ("duplicate", "already_linked")


@pytest.mark.asyncio
async def test_a_repeat_within_a_day_is_stored_once(client: AsyncClient) -> None:
    _, agent_a, token_a = await _seed_agent()
    _, _, token_b = await _seed_agent()
    mobile = unique_mobile()
    assert (await _introduce(client, token_b, mobile)).status_code == 201

    for _ in range(3):
        assert (await _introduce(client, token_a, mobile)).status_code == 409
    assert len(await _agent_rows(agent_a)) == 1


@pytest.mark.asyncio
async def test_a_recording_failure_never_changes_the_response(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.lead_intake_attempts as attempts_mod

    def _boom(_mobile: str) -> str:
        raise RuntimeError("fingerprint unavailable")

    monkeypatch.setattr(attempts_mod, "mobile_fingerprint", _boom)
    _, registered_mobile = await full_registration(client, lines=["loans"])
    _, agent_uuid, token = await _seed_agent()

    res = await _introduce(client, token, registered_mobile)
    assert res.status_code == 409
    assert res.json() == {"detail": _CONFLICT_DETAIL}
    assert await _agent_rows(agent_uuid) == []


@pytest.mark.asyncio
async def test_agent_leads_list_and_summary_expose_eligibility(client: AsyncClient) -> None:
    _, agent_a, token_a = await _seed_agent()
    _, _, token_b = await _seed_agent()
    accepted = unique_mobile()
    assert (await _introduce(client, token_a, accepted)).status_code == 201
    expired_mobile = unique_mobile()
    expired_id = await _seed_expired_lead(agent_a, expired_mobile)

    # One own-window rejection and two duplicates on different numbers.
    assert (await _introduce(client, token_a, expired_mobile)).status_code == 409
    for _ in range(2):
        taken = unique_mobile()
        assert (await _introduce(client, token_b, taken)).status_code == 201
        assert (await _introduce(client, token_a, taken)).status_code == 409

    listed = await client.get("/api/v1/agent/leads", headers=_headers(token_a))
    assert listed.status_code == 200, listed.text
    by_mobile = {row["mobile"]: row for row in listed.json()}
    assert by_mobile[accepted]["eligibility"] == "eligible"
    assert by_mobile[accepted]["eligibility_reason"] is None
    assert by_mobile[accepted]["facets"] == {"loans": [], "deals": []}
    expired = by_mobile[expired_mobile]
    assert expired["id"] == expired_id
    assert expired["status"] == "expired"
    assert expired["eligibility"] == "not_eligible"
    assert expired["eligibility_reason"] == "attribution_expired"
    assert (
        expired["eligibility_reason_label"] == REASON_LABEL[EligibilityReason.ATTRIBUTION_EXPIRED]
    )

    # The single-lead read carries eligibility too, without list-only facets.
    detail = await client.get(f"/api/v1/agent/leads/{expired_id}", headers=_headers(token_a))
    assert detail.json()["eligibility"] == "not_eligible"
    assert "facets" not in detail.json()

    summary = await client.get("/api/v1/agent/lead-eligibility", headers=_headers(token_a))
    assert summary.status_code == 200, summary.text
    assert summary.json() == {"eligible": 1, "not_eligible": 2, "duplicate": 2, "not_accepted": 3}


@pytest.mark.asyncio
async def test_agent_eligibility_routes_are_agent_only(client: AsyncClient) -> None:
    client_token, _ = await full_registration(client, lines=["loans"])
    for path in ("/api/v1/agent/lead-eligibility", "/api/v1/agent/lead-attempts"):
        res = await client.get(path, headers=_headers(client_token))
        assert res.status_code == 403, path


# ---------------------------------------------------------------------------
# Referral sign-ups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_referred_is_recorded_for_the_later_referrer_only(
    client: AsyncClient,
) -> None:
    from app.services.referrals import attribute_signup

    token_a, mobile_a = await full_registration(client, lines=["loans"])
    token_c, mobile_c = await full_registration(client, lines=["loans"])
    code_a, code_c = await _my_code(client, token_a), await _my_code(client, token_c)
    uid_a, uid_c = await _auth_user_uuid(mobile_a), await _auth_user_uuid(mobile_c)
    _, mobile_referred = await full_registration(client, lines=["loans"])
    referred_uuid = uuid.UUID(await _auth_user_uuid(mobile_referred))
    referred_mobile = unique_mobile()

    for code in (code_a, code_c, code_a):
        await attribute_signup(
            code=code, referred_mobile=referred_mobile, referred_auth_user_uuid=referred_uuid
        )

    # A's own existing referral is already on A's list; nothing recorded.
    assert await _referrer_rows(uid_a) == []
    (row,) = await _referrer_rows(uid_c)
    assert (row["outcome"], row["reason_code"]) == ("duplicate", "already_referred")
    assert row["business_line"] is None
    assert row["mobile_last4"] == referred_mobile[-4:]
    _assert_no_raw_mobile(row, referred_mobile)

    listed = await client.get("/api/v1/referrals/attempts", headers=_headers(token_c))
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["attempts"][0]["mobile_masked"] == f"***{referred_mobile[-4:]}"
    assert (await client.get("/api/v1/referrals/attempts", headers=_headers(token_a))).json() == {
        "attempts": [],
        "total": 0,
    }


@pytest.mark.asyncio
async def test_self_referral_is_recorded_as_not_eligible(client: AsyncClient) -> None:
    from app.services.referrals import attribute_signup

    token_a, mobile_a = await full_registration(client, lines=["loans"])
    code = await _my_code(client, token_a)
    uid_a = await _auth_user_uuid(mobile_a)

    assert (
        await attribute_signup(
            code=code, referred_mobile=mobile_a, referred_auth_user_uuid=uuid.UUID(uid_a)
        )
        is None
    )
    (row,) = await _referrer_rows(uid_a)
    assert (row["outcome"], row["reason_code"]) == ("not_eligible", "self_referral")


@pytest.mark.asyncio
async def test_an_unmatched_code_records_nothing(client: AsyncClient) -> None:
    from app.services.referrals import attribute_signup

    mobile = unique_mobile()
    assert (
        await attribute_signup(
            code="ZZZZZZZZ", referred_mobile=mobile, referred_auth_user_uuid=uuid.uuid4()
        )
        == "ZZZZZZZZ"
    )
    assert await _attempt_rows("mobile_fingerprint = :f", {"f": mobile_fingerprint(mobile)}) == []


@pytest.mark.asyncio
async def test_referral_list_and_summary_expose_eligibility(client: AsyncClient) -> None:
    import app.db.session as _session_mod
    from app.models.referral import Referral

    token_a, mobile_a = await full_registration(client, lines=["loans"])
    uid_a = uuid.UUID(await _auth_user_uuid(mobile_a))
    _, mobile_b = await full_registration(client, lines=["loans"])
    uid_b = uuid.UUID(await _auth_user_uuid(mobile_b))

    shapes = [
        (ReferralStatus.PENDING, None),
        (ReferralStatus.ACCRUED, "accrued"),
        (ReferralStatus.CONVERTED, "cap_reached"),
        (ReferralStatus.VOID, "referrer_not_client"),
    ]
    async with _session_mod.AsyncSessionLocal() as db:
        for status, reason in shapes:
            db.add(
                Referral(
                    referrer_auth_user_uuid=uid_a,
                    referred_mobile=unique_mobile(),
                    referred_auth_user_uuid=uid_b,
                    # The line is set exactly once, at conversion.
                    business_line=None if status == ReferralStatus.PENDING else "loans",
                    conversion_status=status,
                    accrual_reason=reason,
                )
            )
        await db.commit()
    await record_attempt(
        actor_type=IntakeActorType.REFERRER,
        actor_uuid=uid_a,
        auth_user_uuid=uid_a,
        mobile=unique_mobile(),
        reason=EligibilityReason.ALREADY_REFERRED,
    )

    listed = await client.get("/api/v1/referrals", headers=_headers(token_a))
    assert listed.status_code == 200, listed.text
    got = sorted(
        (row["eligibility"], row["eligibility_reason"]) for row in listed.json()["referrals"]
    )
    assert got == [
        ("eligible", None),
        ("eligible", None),
        ("not_eligible", "cap_reached"),
        ("not_eligible", "referrer_not_client"),
    ]
    # The raw accrual reason stays Admin-only.
    assert all("accrual_reason" not in row for row in listed.json()["referrals"])

    summary = await client.get("/api/v1/referrals/eligibility", headers=_headers(token_a))
    assert summary.status_code == 200, summary.text
    assert summary.json() == {"eligible": 2, "not_eligible": 2, "duplicate": 1, "not_accepted": 1}


# ---------------------------------------------------------------------------
# RLS and erasure
# ---------------------------------------------------------------------------


def _engine():  # noqa: ANN202
    return create_async_engine(
        settings.DATABASE_URL.replace("pgbouncer:5432", "postgres:5432"),
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        },
    )


async def _as_api_user(
    sql: str,
    params: dict,
    *,
    auth_user_uuid: str,
    role: str,
    agent_profile_uuid: str = "",
    platform_scope: str = "false",
):  # noqa: ANN202
    engine = _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL ROLE api_user"))
            await conn.execute(
                text(
                    "SELECT set_config('app.auth_user_uuid', :uid, true),"
                    "set_config('app.role', :role, true),"
                    "set_config('app.business_line', 'loans', true),"
                    "set_config('app.client_profile_uuid', '', true),"
                    "set_config('app.agent_profile_uuid', :agent, true),"
                    "set_config('app.staff_profile_uuid', '', true),"
                    "set_config('app.platform_scope', :ps, true)"
                ),
                {
                    "uid": auth_user_uuid,
                    "role": role,
                    "agent": agent_profile_uuid,
                    "ps": platform_scope,
                },
            )
            return (await conn.execute(text(sql), params)).fetchall()
    finally:
        await engine.dispose()


async def _visible_ids(**context: str) -> set[str]:
    rows = await _as_api_user("SELECT id FROM lead_intake_attempts", {}, **context)
    return {str(row[0]) for row in rows}


@pytest.mark.asyncio
async def test_rls_shows_each_owner_only_their_own_attempts(client: AsyncClient) -> None:
    auth_a, agent_a, _ = await _seed_agent()
    auth_b, agent_b, _ = await _seed_agent()
    _, client_mobile = await full_registration(client, lines=["loans"])
    client_uid = await _auth_user_uuid(client_mobile)
    for actor in (agent_a, agent_b):
        await record_attempt(
            actor_type=IntakeActorType.AGENT,
            actor_uuid=uuid.UUID(actor),
            mobile=unique_mobile(),
            business_line="loans",
            reason=EligibilityReason.ALREADY_LINKED,
        )
    await record_attempt(
        actor_type=IntakeActorType.REFERRER,
        actor_uuid=uuid.UUID(client_uid),
        auth_user_uuid=uuid.UUID(client_uid),
        mobile=unique_mobile(),
        reason=EligibilityReason.ALREADY_REFERRED,
    )
    ids_a = {str(r["id"]) for r in await _agent_rows(agent_a)}
    ids_b = {str(r["id"]) for r in await _agent_rows(agent_b)}
    ids_client = {str(r["id"]) for r in await _referrer_rows(client_uid)}

    assert (
        await _visible_ids(auth_user_uuid=auth_a, role="agent", agent_profile_uuid=agent_a) == ids_a
    )
    assert (
        await _visible_ids(auth_user_uuid=auth_b, role="agent", agent_profile_uuid=agent_b) == ids_b
    )
    # The right account without the Agent profile (or role) sees no Agent rows.
    assert await _visible_ids(auth_user_uuid=auth_a, role="client") == set()
    assert (
        await _visible_ids(auth_user_uuid=auth_a, role="agent", agent_profile_uuid=agent_b) == set()
    )
    assert await _visible_ids(auth_user_uuid=client_uid, role="client") == ids_client
    # No staff read policy at all, platform Admin included.
    stranger = str(uuid.uuid4())
    for role, scope in (
        ("admin", "true"),
        ("admin", "false"),
        ("sub_admin", "true"),
        ("telecaller", "false"),
    ):
        assert (
            await _visible_ids(auth_user_uuid=stranger, role=role, platform_scope=scope) == set()
        ), role


@pytest.mark.asyncio
async def test_api_user_cannot_write_attempts_or_erase_someone_else(client: AsyncClient) -> None:
    from sqlalchemy.exc import DBAPIError

    auth_a, agent_a, _ = await _seed_agent()
    with pytest.raises(DBAPIError, match="permission denied"):
        await _as_api_user(
            "INSERT INTO lead_intake_attempts (actor_type, actor_uuid, auth_user_uuid, "
            "mobile_last4, mobile_fingerprint, outcome, reason_code) VALUES "
            "('agent', :a, :u, '1234', :f, 'duplicate', 'already_linked')",
            {"a": agent_a, "u": auth_a, "f": "0" * 64},
            auth_user_uuid=auth_a,
            role="agent",
            agent_profile_uuid=agent_a,
        )
    with pytest.raises(DBAPIError, match="not authorized"):
        await _as_api_user(
            "SELECT erase_lead_intake_attempts(:target)",
            {"target": auth_a},
            auth_user_uuid=str(uuid.uuid4()),
            role="client",
        )


@pytest.mark.asyncio
async def test_attempts_are_erased_with_the_owners_account(client: AsyncClient) -> None:
    # Agent account removed by a platform Admin.
    auth_a, agent_a, _ = await _seed_agent()
    await record_attempt(
        actor_type=IntakeActorType.AGENT,
        actor_uuid=uuid.UUID(agent_a),
        mobile=unique_mobile(),
        business_line="loans",
        reason=EligibilityReason.ALREADY_LINKED,
    )
    _, admin_mobile = await full_registration(client)
    admin_token = create_access_token(
        {
            "sub": await _auth_user_uuid(admin_mobile),
            "role": "admin",
            "business_line": "",
            "platform_scope": "true",
        }
    )
    other_auth, other_agent, _ = await _seed_agent()
    await record_attempt(
        actor_type=IntakeActorType.AGENT,
        actor_uuid=uuid.UUID(other_agent),
        mobile=unique_mobile(),
        business_line="loans",
        reason=EligibilityReason.ALREADY_LINKED,
    )
    assert len(await _agent_rows(agent_a)) == 1
    res = await client.post(
        f"/api/v1/admin/users/{auth_a}/delete",
        json={"reason": "requested erasure"},
        headers=_headers(admin_token),
    )
    assert res.status_code == 200, res.text
    assert await _agent_rows(agent_a) == []
    assert len(await _agent_rows(other_agent)) == 1

    # Client referrer deleting their own account.
    token_c, mobile_c = await full_registration(client, lines=["loans"])
    uid_c = await _auth_user_uuid(mobile_c)
    await record_attempt(
        actor_type=IntakeActorType.REFERRER,
        actor_uuid=uuid.UUID(uid_c),
        auth_user_uuid=uuid.UUID(uid_c),
        mobile=unique_mobile(),
        reason=EligibilityReason.ALREADY_REFERRED,
    )
    assert len(await _referrer_rows(uid_c)) == 1
    deleted = await client.request(
        "DELETE",
        "/api/v1/auth/me",
        headers=_headers(token_c),
        json={"current_password": PASSWORD},
    )
    assert deleted.status_code in (200, 204), deleted.text
    assert await _referrer_rows(uid_c) == []
