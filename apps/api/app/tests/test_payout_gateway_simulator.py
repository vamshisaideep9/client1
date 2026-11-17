"""Development RazorpayX gateway simulator (PAYOUT_GATEWAY_SIMULATOR).

With the simulator on and payments in mock mode, approving a UPI/bank payout
stops at INITIATED with a synthetic gateway id. An Admin then chooses the
gateway outcome, which runs through the same settle_from_webhook state machine
as a real RazorpayX webhook: processed credits the ledger once, failed/rejected
release it, and a reversal posts the compensating clawback.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app.core.config import Settings, settings
from app.services import payments as payments_service
from app.tests.test_config import _GOOD_KEY, _REAL_SPACES
from app.tests.test_payouts_api import (
    _auth_user_id,
    _create_body,
    _headers,
    _make_admin,
)
from conftest import full_registration


@pytest.fixture
def simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PAYOUT_GATEWAY_SIMULATOR", True)
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "")


async def _approved_payout(
    client: AsyncClient, *, amount_paise: int = 75_000
) -> tuple[dict, str, str, str]:
    """Create and approve a VPA payout. Returns (body, checker, maker, recipient token)."""
    maker_token, _ = await _make_admin(client)
    checker_token, _ = await _make_admin(client)
    recipient_token, recipient_mobile = await full_registration(client, lines=["loans"])
    recipient_uid = await _auth_user_id(recipient_mobile)
    created = await client.post(
        "/api/v1/payouts",
        headers=_headers(maker_token),
        json=_create_body(recipient_uid, amount_paise=amount_paise),
    )
    assert created.status_code == 201, created.text
    approved = await client.post(
        f"/api/v1/payouts/{created.json()['id']}/approve", headers=_headers(checker_token)
    )
    assert approved.status_code == 200, approved.text
    return approved.json(), checker_token, maker_token, recipient_token


async def _simulate(client: AsyncClient, token: str, payout_id: str, event: str):
    return await client.post(
        f"/api/v1/payouts/{payout_id}/simulate-gateway",
        headers=_headers(token),
        json={"event": event},
    )


async def _ledger(client: AsyncClient, token: str) -> list[dict]:
    response = await client.get("/api/v1/transactions", headers=_headers(token))
    assert response.status_code == 200
    return response.json()["transactions"]


def test_simulator_is_refused_outside_development() -> None:
    # Known-good production settings, so only the simulator guard can fail.
    production = {"ENV": "production", "SECRET_KEY": _GOOD_KEY, **_REAL_SPACES}
    assert Settings(**production).PAYOUT_GATEWAY_SIMULATOR is False
    with pytest.raises(ValueError, match="PAYOUT_GATEWAY_SIMULATOR is development-only"):
        Settings(**production, PAYOUT_GATEWAY_SIMULATOR=True)


def test_simulator_is_inert_with_live_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PAYOUT_GATEWAY_SIMULATOR", True)
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "secret")
    assert payments_service.gateway_simulator_active() is False


@pytest.mark.asyncio
async def test_approval_waits_for_a_simulated_outcome(client: AsyncClient, simulator) -> None:
    body, checker_token, _, recipient_token = await _approved_payout(client)
    assert body["status"] == "initiated"
    assert body["gateway_payout_id"].startswith(payments_service.SIMULATED_GATEWAY_PREFIX)
    assert body["gateway_status"] == "queued"
    assert body["simulate_events"] == ["payout.processed", "payout.failed", "payout.rejected"]
    assert await _ledger(client, recipient_token) == []


@pytest.mark.asyncio
async def test_processed_credits_once_and_can_then_be_reversed(
    client: AsyncClient, simulator
) -> None:
    body, checker_token, _, recipient_token = await _approved_payout(client, amount_paise=98_700)

    paid = await _simulate(client, checker_token, body["id"], "payout.processed")
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"
    assert paid.json()["simulate_events"] == ["payout.reversed"]
    ledger = await _ledger(client, recipient_token)
    assert [(t["status"], t["amount_paise"]) for t in ledger] == [("paid", 98_700)]

    # A repeated success is no longer an available outcome (no double credit).
    again = await _simulate(client, checker_token, body["id"], "payout.processed")
    assert again.status_code == 409
    assert len(await _ledger(client, recipient_token)) == 1

    reversed_ = await _simulate(client, checker_token, body["id"], "payout.reversed")
    assert reversed_.status_code == 200, reversed_.text
    assert reversed_.json()["status"] == "reversed"
    assert reversed_.json()["simulate_events"] == []
    amounts = sorted(t["amount_paise"] for t in await _ledger(client, recipient_token))
    assert amounts == [-98_700, 98_700]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["payout.failed", "payout.rejected"])
async def test_failure_outcomes_never_credit(client: AsyncClient, simulator, event: str) -> None:
    body, checker_token, _, recipient_token = await _approved_payout(client)
    failed = await _simulate(client, checker_token, body["id"], event)
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["failure_reason"]
    assert failed.json()["simulate_events"] == []
    assert await _ledger(client, recipient_token) == []

    # A failed payout cannot later be reversed or paid by the simulator.
    late = await _simulate(client, checker_token, body["id"], "payout.processed")
    assert late.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_contradictory_outcomes_have_one_winner(
    client: AsyncClient, simulator
) -> None:
    body, checker_token, _, recipient_token = await _approved_payout(client, amount_paise=61_000)
    paid, failed = await asyncio.gather(
        _simulate(client, checker_token, body["id"], "payout.processed"),
        _simulate(client, checker_token, body["id"], "payout.failed"),
    )
    assert sorted([paid.status_code, failed.status_code]) == [200, 409]
    winner = paid if paid.status_code == 200 else failed
    ledger = await _ledger(client, recipient_token)
    if winner is paid:
        assert winner.json()["status"] == "paid"
        assert [t["amount_paise"] for t in ledger] == [61_000]
    else:
        assert winner.json()["status"] == "failed"
        assert ledger == []
    # The claim is never left behind.
    assert winner.json()["gateway_status"] != payments_service.SIMULATOR_CLAIM_STATUS


@pytest.mark.asyncio
async def test_only_platform_admins_may_simulate(client: AsyncClient, simulator) -> None:
    body, _, _, recipient_token = await _approved_payout(client)
    sub_admin_token, _ = await _make_admin(
        client, role="sub_admin", staff_features=["payout_requests"]
    )
    for token in (sub_admin_token, recipient_token):
        response = await _simulate(client, token, body["id"], "payout.processed")
        assert response.status_code == 403, response.text
    assert await _ledger(client, recipient_token) == []


@pytest.mark.asyncio
async def test_simulator_endpoint_is_hidden_when_off(client: AsyncClient) -> None:
    # Default configuration: mock mode auto-settles and the simulator is absent.
    assert settings.PAYOUT_GATEWAY_SIMULATOR is False
    body, checker_token, _, _ = await _approved_payout(client)
    assert body["status"] == "paid"
    assert body["simulate_events"] == []
    response = await _simulate(client, checker_token, body["id"], "payout.reversed")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unknown_event_is_rejected(client: AsyncClient, simulator) -> None:
    body, checker_token, _, _ = await _approved_payout(client)
    response = await _simulate(client, checker_token, body["id"], "payout.created")
    assert response.status_code == 422
