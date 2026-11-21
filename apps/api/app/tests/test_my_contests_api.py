"""CS-027 participant contest pages and Admin standings (live standings)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import app.db.session as db_session
from app.models.field_visibility import FieldTargetRole, FieldVisibilityConfig, FieldVisibilityMode
from app.models.loan import LoanStatus
from app.models.profile import StaffRole
from app.services.contests import today_ist
from app.tests.contest_support import (
    admin_token,
    headers,
    seed_agent,
    seed_call,
    seed_contest,
    seed_lead,
    seed_loan,
    seed_loan_type,
    seed_staff,
    seed_team,
    seed_user,
    sub_admin_token,
    token_for,
)

pytestmark = pytest.mark.asyncio

_FORBIDDEN_KEYS = {"mobile", "email", "agent_code", "auth_user_uuid", "user_uuid", "last_name"}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


async def _agent_contest(maker, loan_type, **fields):
    return await seed_contest(
        created_by=maker,
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "disbursed",
                "count_at_least": 1,
            },
        },
        **fields,
    )


async def test_agent_sees_rules_progress_and_minimal_leaderboard(client: AsyncClient) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Leaderboard loan")
    me_user, me = await seed_agent("loans", first_name="Asha")
    _, leader = await seed_agent("loans", first_name="Bhavna")
    for agent, cases in ((me, 1), (leader, 2)):
        for _ in range(cases):
            await seed_loan(await seed_lead("loans", agent=agent), loan_type=loan_type)
    contest = await _agent_contest(maker, loan_type)
    draft = await _agent_contest(maker, loan_type, status="draft")
    real_estate = await seed_contest(
        created_by=maker,
        business_line="real_estate",
        criteria={"version": 1, "real_estate": {"counted_stage": "closed", "count_at_least": 1}},
    )
    token = token_for(me_user, "agent", business_line="loans", agent_profile=me)

    response = await client.get("/api/v1/my-contests", headers=headers(token))
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["contests"]}
    assert str(contest.id) in rows
    assert str(draft.id) not in rows and str(real_estate.id) not in rows
    assert rows[str(contest.id)]["me"]["metric_value"] == 1
    assert rows[str(contest.id)]["eligible"] is True

    response = await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(token))
    assert response.status_code == 200
    detail = response.json()
    assert detail["criteria"]["loans"]["counted_stage"] == "disbursed"
    assert detail["me"]["rank"] == 2 and detail["me"]["qualified"] is True
    top = detail["leaderboard"][0]
    assert (top["name"], top["rank"], top["achieved"], top["is_me"]) == ("Bhavna A.", 1, 2, False)
    mine = next(entry for entry in detail["leaderboard"] if entry["is_me"])
    assert (mine["name"], mine["rank"], mine["achieved"]) == ("Asha A.", 2, 1)
    assert set(top) == {"rank", "name", "achieved", "qualified", "is_me"}
    assert not _keys(detail) & _FORBIDDEN_KEYS

    for hidden in (draft, real_estate):
        response = await client.get(f"/api/v1/my-contests/{hidden.id}", headers=headers(token))
        assert response.status_code == 404


async def test_admin_can_hide_other_names_and_amounts(client: AsyncClient) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Hidden loan")
    me_user, me = await seed_agent("loans", first_name="Chitra")
    _, other = await seed_agent("loans", first_name="Deepa")
    for agent in (me, other):
        await seed_loan(await seed_lead("loans", agent=agent), loan_type=loan_type)
    contest = await _agent_contest(maker, loan_type, metric="amount")
    async with db_session.AsyncSessionLocal() as db:
        for field_key in ("names", "amounts"):
            db.add(
                FieldVisibilityConfig(
                    target_role=FieldTargetRole.AGENT,
                    entity="contest_leaderboard",
                    field_key=field_key,
                    mode=FieldVisibilityMode.DENY,
                )
            )
        await db.commit()
    try:
        token = token_for(me_user, "agent", business_line="loans", agent_profile=me)
        detail = (
            await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(token))
        ).json()
        mine = [e for e in detail["leaderboard"] if e["is_me"]]
        others = [e for e in detail["leaderboard"] if not e["is_me"]]
        assert mine[0]["name"] == "Chitra A." and mine[0]["achieved"] == 10_00_000_00
        assert others and all(e["name"] is None and e["achieved"] is None for e in others)
    finally:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(
                delete(FieldVisibilityConfig).where(
                    FieldVisibilityConfig.entity == "contest_leaderboard"
                )
            )
            await db.commit()


async def test_team_member_and_manager_views(client: AsyncClient) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Team view loan")
    manager_user, manager = await seed_staff(StaffRole.SUB_ADMIN, first_name="Mira")
    ravi_user, ravi = await seed_staff(
        StaffRole.TELECALLER, business_line="loans", first_name="Ravi"
    )
    _, sam = await seed_staff(StaffRole.TELECALLER, business_line="loans", first_name="Sam")
    loner_user, loner = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    await seed_team(manager, "loans", "telecaller", [ravi, sam])
    for person in (ravi, sam, sam):
        lead = await seed_lead("loans", telecaller=person)
        # Telecaller credit needs a call before the counted stage.
        await seed_call(person, lead, at=datetime.now(UTC) - timedelta(minutes=30))
        await seed_loan(lead, loan_type=loan_type, status=LoanStatus.SANCTIONED)
    contest = await seed_contest(
        created_by=maker,
        audience="team",
        team_member_role="telecaller",
        criteria={
            "version": 1,
            "loans": {
                "loan_type_ids": [str(loan_type.id)],
                "counted_stage": "sanctioned",
                "count_at_least": 3,
            },
        },
        prize_paise=None,
        manager_prize_paise=500_00,
        member_prize_paise=100_00,
        member_min_contribution=2,
    )

    member_token = token_for(ravi_user, "telecaller", business_line="loans", staff_profile=ravi)
    detail = (
        await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(member_token))
    ).json()
    assert detail["my_role"] == "team_member"
    assert detail["team"]["metric_value"] == 3 and detail["team"]["qualified"] is True
    assert [m["name"] for m in detail["team"]["members"]] == ["Ravi Telecaller"]
    assert detail["team"]["members"][0]["meets_member_minimum"] is False

    manager_token = token_for(
        manager_user, "sub_admin", platform_scope="true", staff_profile=manager
    )
    response = await client.get("/api/v1/my-contests", headers=headers(manager_token))
    assert str(contest.id) in {row["id"] for row in response.json()["contests"]}
    detail = (
        await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(manager_token))
    ).json()
    assert detail["my_role"] == "team_manager"
    names = [m["name"] for m in detail["team"]["members"]]
    assert names == ["Sam Telecaller", "Ravi Telecaller"]

    loner_token = token_for(loner_user, "telecaller", business_line="loans", staff_profile=loner)
    response = await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(loner_token))
    assert response.status_code == 404
    other_manager, _, _ = await sub_admin_token()
    response = await client.get(f"/api/v1/my-contests/{contest.id}", headers=headers(other_manager))
    assert response.status_code == 404


async def test_admin_standings_and_role_guards(client: AsyncClient) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Standings loan")
    _, agent = await seed_agent("loans", first_name="Esha")
    await seed_loan(await seed_lead("loans", agent=agent), loan_type=loan_type)
    contest = await _agent_contest(maker, loan_type)
    admin, _ = await admin_token()
    response = await client.get(f"/api/v1/contests/{contest.id}/standings", headers=headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "live"
    row = next(r for r in body["rows"] if r["name"] == "Esha Agent")
    assert row["achieved_count"] == 1 and row["qualified"] is True and row["rank"] == 1

    sub_admin, _, _ = await sub_admin_token()
    response = await client.get(
        f"/api/v1/contests/{contest.id}/standings", headers=headers(sub_admin)
    )
    assert response.status_code == 403
    client_user = await seed_user("A", "Client")
    response = await client.get(
        "/api/v1/my-contests", headers=headers(token_for(client_user, "client"))
    )
    assert response.status_code == 403


async def test_upcoming_contest_shows_rules_without_standings(client: AsyncClient) -> None:
    maker = await seed_user("Maker", "Sub")
    loan_type = await seed_loan_type("Upcoming loan")
    me_user, me = await seed_agent("loans")
    upcoming = await _agent_contest(
        maker,
        loan_type,
        status="approved",
        starts_on=today_ist() + timedelta(days=2),
        ends_on=today_ist() + timedelta(days=9),
    )
    token = token_for(me_user, "agent", business_line="loans", agent_profile=me)
    detail = (await client.get(f"/api/v1/my-contests/{upcoming.id}", headers=headers(token))).json()
    assert detail["status"] == "approved"
    assert detail["me"] is None and detail["leaderboard"] == []
    assert detail["eligible"] is True
