"""CS-027 contests / contest_results RLS (migration a8d0f2b4c6e9).

Participants read only approved-or-later contests for their role and request
line, and only their own result row; a managing Sub Admin reads their team's
rows; nobody but the maker writes, and the maker can never set a checker or a
reviewed status through RLS.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DBAPIError

import app.db.session as db_session
from app.models.contest import ContestResult
from app.models.profile import StaffRole
from app.tests.contest_support import (
    as_role,
    seed_agent,
    seed_contest,
    seed_staff,
    seed_team,
    seed_user,
)

pytestmark = pytest.mark.asyncio

_IDS = "SELECT id FROM contests"


async def _visible(**context) -> set[uuid.UUID]:
    return {row[0] for row in await as_role(_IDS, **context)}


async def test_participants_see_only_targeted_contests(client) -> None:
    maker, _ = await seed_staff(StaffRole.SUB_ADMIN)
    agent_loans = await seed_contest(created_by=maker, status="live", audience="agent")
    agent_draft = await seed_contest(created_by=maker, status="draft", audience="agent")
    agent_pending = await seed_contest(
        created_by=maker, status="pending_approval", audience="agent"
    )
    agent_re = await seed_contest(
        created_by=maker,
        status="live",
        audience="agent",
        business_line="real_estate",
        criteria={"version": 1, "real_estate": {"counted_stage": "closed", "count_at_least": 1}},
    )
    telecaller_contest = await seed_contest(
        created_by=maker,
        status="approved",
        audience="telecaller",
        metric="calls_logged",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 10}},
    )
    team_contest = await seed_contest(
        created_by=maker,
        status="ended",
        audience="team",
        team_member_role="telecaller",
        metric="calls_logged",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 10}},
        prize_paise=None,
        manager_prize_paise=500,
        member_prize_paise=0,
    )
    cancelled = await seed_contest(created_by=maker, status="cancelled", audience="agent")

    agent_user, agent = await seed_agent("loans")
    seen = await _visible(
        user_uuid=agent_user.id,
        role="agent",
        business_line="loans",
        agent_profile_uuid=agent.id,
    )
    assert agent_loans.id in seen
    for hidden in (
        agent_draft,
        agent_pending,
        agent_re,
        telecaller_contest,
        team_contest,
        cancelled,
    ):
        assert hidden.id not in seen

    telecaller_user, telecaller = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    seen = await _visible(
        user_uuid=telecaller_user.id,
        role="telecaller",
        business_line="loans",
        staff_profile_uuid=telecaller.id,
    )
    assert {telecaller_contest.id, team_contest.id} <= seen
    assert agent_loans.id not in seen

    employee_user, employee = await seed_staff(StaffRole.EMPLOYEE, business_line="loans")
    seen = await _visible(
        user_uuid=employee_user.id,
        role="employee",
        business_line="loans",
        staff_profile_uuid=employee.id,
    )
    assert not seen & {agent_loans.id, telecaller_contest.id, team_contest.id}

    client_user = await seed_user("Some", "Client")
    assert not await _visible(user_uuid=client_user.id, role="client", business_line="loans")

    sub_admin_user, sub_admin = await seed_staff(StaffRole.SUB_ADMIN)
    seen = await _visible(
        user_uuid=sub_admin_user.id, role="sub_admin", staff_profile_uuid=sub_admin.id
    )
    assert {agent_draft.id, agent_pending.id, cancelled.id} <= seen

    admin_user = await seed_user("Platform", "Admin")
    seen = await _visible(user_uuid=admin_user.id, role="admin", platform_scope="true")
    assert agent_draft.id in seen
    line_admin_seen = await _visible(user_uuid=admin_user.id, role="admin", platform_scope="line")
    assert agent_draft.id not in line_admin_seen


async def test_maker_cannot_self_approve_or_touch_others(client) -> None:
    maker_user, maker = await seed_staff(StaffRole.SUB_ADMIN)
    contest = await seed_contest(created_by=maker_user, status="pending_approval")
    context = {
        "user_uuid": maker_user.id,
        "role": "sub_admin",
        "staff_profile_uuid": maker.id,
    }
    for sql in (
        "UPDATE contests SET status = 'approved', reviewed_at = now(), "
        "checker_uuid = :other WHERE id = :id",
        "UPDATE contests SET status = 'live' WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            await as_role(sql, params={"id": contest.id, "other": uuid.uuid4()}, **context)

    other_user, other = await seed_staff(StaffRole.SUB_ADMIN)
    rows = await as_role(
        "UPDATE contests SET status = 'draft' WHERE id = :id RETURNING id",
        params={"id": contest.id},
        user_uuid=other_user.id,
        role="sub_admin",
        staff_profile_uuid=other.id,
    )
    assert rows == []

    # The maker may withdraw it to draft through RLS.
    rows = await as_role(
        "UPDATE contests SET status = 'draft' WHERE id = :id RETURNING id",
        params={"id": contest.id},
        **context,
    )
    assert [row[0] for row in rows] == [contest.id]

    # Nobody else inserts, and a maker cannot insert a reviewed contest.
    agent_user, agent = await seed_agent()
    insert = (
        "INSERT INTO contests (title, business_line, audience, metric, criteria, win_mode, "
        "prize_paise, starts_on, ends_on, status, created_by_uuid) VALUES ('RLS insert', "
        "'loans', 'agent', 'cases', '{\"version\": 1}'::jsonb, 'threshold', 100, current_date, "
        "current_date, :status, :maker)"
    )
    with pytest.raises(DBAPIError):
        await as_role(
            insert,
            params={"status": "draft", "maker": agent_user.id},
            user_uuid=agent_user.id,
            role="agent",
            business_line="loans",
            agent_profile_uuid=agent.id,
        )
    with pytest.raises(DBAPIError):
        await as_role(
            insert,
            params={"status": "approved", "maker": maker_user.id},
            **context,
        )


async def test_results_are_own_row_or_managed_team(client) -> None:
    maker, _ = await seed_staff(StaffRole.SUB_ADMIN)
    contest = await seed_contest(created_by=maker, status="ended")
    agent_a_user, agent_a = await seed_agent("loans")
    agent_b_user, agent_b = await seed_agent("loans")
    manager_user, manager = await seed_staff(StaffRole.SUB_ADMIN)
    member_user, member = await seed_staff(StaffRole.TELECALLER, business_line="loans")
    team = await seed_team(manager, "loans", "telecaller", [member])
    team_contest = await seed_contest(
        created_by=maker,
        status="ended",
        audience="team",
        team_member_role="telecaller",
        metric="calls_logged",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 10}},
        prize_paise=None,
        manager_prize_paise=500,
        member_prize_paise=0,
    )
    async with db_session.AsyncSessionLocal() as db:
        rows = [
            ContestResult(
                contest_uuid=contest.id,
                business_line="loans",
                kind="individual",
                agent_profile_uuid=agent_a.id,
                recipient_user_uuid=agent_a_user.id,
            ),
            ContestResult(
                contest_uuid=contest.id,
                business_line="loans",
                kind="individual",
                agent_profile_uuid=agent_b.id,
                recipient_user_uuid=agent_b_user.id,
            ),
            ContestResult(
                contest_uuid=team_contest.id,
                business_line="loans",
                kind="team",
                team_uuid=team.id,
            ),
            ContestResult(
                contest_uuid=team_contest.id,
                business_line="loans",
                kind="team_member",
                team_uuid=team.id,
                staff_profile_uuid=member.id,
                recipient_user_uuid=member_user.id,
            ),
        ]
        db.add_all(rows)
        await db.commit()
    a_row, b_row, team_row, member_row = rows

    sql = "SELECT id FROM contest_results WHERE contest_uuid IN (:a, :b)"
    params = {"a": contest.id, "b": team_contest.id}
    seen = {
        row[0]
        for row in await as_role(
            sql,
            params=params,
            user_uuid=agent_a_user.id,
            role="agent",
            business_line="loans",
            agent_profile_uuid=agent_a.id,
        )
    }
    assert seen == {a_row.id}

    seen = {
        row[0]
        for row in await as_role(
            sql,
            params=params,
            user_uuid=member_user.id,
            role="telecaller",
            business_line="loans",
            staff_profile_uuid=member.id,
        )
    }
    assert seen == {member_row.id}

    seen = {
        row[0]
        for row in await as_role(
            sql,
            params=params,
            user_uuid=manager_user.id,
            role="sub_admin",
            staff_profile_uuid=manager.id,
        )
    }
    assert seen == {team_row.id, member_row.id}

    other_sub_user, other_sub = await seed_staff(StaffRole.SUB_ADMIN)
    assert not await as_role(
        sql,
        params=params,
        user_uuid=other_sub_user.id,
        role="sub_admin",
        staff_profile_uuid=other_sub.id,
    )
    admin_user = await seed_user("Platform", "Admin")
    seen = {
        row[0]
        for row in await as_role(
            sql, params=params, user_uuid=admin_user.id, role="admin", platform_scope="true"
        )
    }
    assert seen == {a_row.id, b_row.id, team_row.id, member_row.id}

    # No write grant for anyone on api_user.
    with pytest.raises(DBAPIError):
        await as_role(
            "UPDATE contest_results SET won = true WHERE id = :id",
            params={"id": a_row.id},
            user_uuid=admin_user.id,
            role="admin",
            platform_scope="true",
        )
