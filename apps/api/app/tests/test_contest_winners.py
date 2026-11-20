"""CS-027 winner rules (pure): threshold vs top-N, ties, budget cap, teams."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.models.contest import Contest
from app.schemas.contests import ContestCriteria
from app.services.contest_scoring import (
    Participant,
    Standings,
    Tally,
    decide_winners,
    meets_targets,
    rank_in_place,
)


def _contest(**fields) -> Contest:
    values = {
        "id": uuid.uuid4(),
        "audience": "agent",
        "metric": "cases",
        "win_mode": "threshold",
        "top_n": None,
        "prize_paise": 1_000,
        "manager_prize_paise": None,
        "member_prize_paise": None,
        "member_min_contribution": None,
        "budget_cap_paise": None,
        "starts_on": date(2030, 1, 1),
        "ends_on": date(2030, 1, 31),
    }
    values.update(fields)
    return Contest(**values)


def _person(
    name: str, value: int, *, qualified: bool = True, kind: str = "individual"
) -> Participant:
    return Participant(
        kind=kind,
        user_uuid=uuid.uuid4(),
        first_name=name,
        last_name="",
        agent_profile_uuid=uuid.uuid4() if kind == "individual" else None,
        metric_value=value,
        qualified=qualified,
    )


def _standings(
    people: list[Participant], team_people: list[Participant] | None = None
) -> Standings:
    return Standings(uuid.uuid4(), datetime.now(UTC), rank_in_place(people), team_people or [])


def _winners(standings: Standings) -> list[str]:
    return sorted(p.first_name for p in standings.ranked if p.won)


def test_competition_ranking_keeps_ties_together() -> None:
    people = rank_in_place([_person("a", 5), _person("b", 9), _person("c", 5), _person("d", 1)])
    assert [(p.first_name, p.rank) for p in people] == [("b", 1), ("a", 2), ("c", 2), ("d", 4)]


def test_threshold_pays_everyone_who_qualified() -> None:
    standings = _standings([_person("a", 3), _person("b", 1), _person("c", 7, qualified=False)])
    decide_winners(_contest(), standings)
    assert _winners(standings) == ["a", "b"]
    assert all(p.prize_paise == 1_000 for p in standings.ranked if p.won)
    assert all(p.prize_paise == 0 for p in standings.ranked if not p.won)


def test_top_n_keeps_a_tie_at_the_cut_off_whole() -> None:
    standings = _standings(
        [_person("a", 9), _person("b", 7), _person("c", 7), _person("d", 3), _person("e", 0)]
    )
    decide_winners(_contest(win_mode="top_n", top_n=2), standings)
    assert _winners(standings) == ["a", "b", "c"]


def test_top_n_ignores_unqualified_and_zero_results() -> None:
    standings = _standings(
        [_person("a", 9, qualified=False), _person("b", 4), _person("c", 0), _person("d", 0)]
    )
    decide_winners(_contest(win_mode="top_n", top_n=3), standings)
    assert _winners(standings) == ["b"]


def test_budget_cap_pays_in_rank_order_and_drops_a_crossing_tie_group() -> None:
    standings = _standings([_person("a", 9), _person("b", 7), _person("c", 7), _person("d", 5)])
    decide_winners(_contest(budget_cap_paise=2_500), standings)
    assert _winners(standings) == ["a"]
    capped = sorted(p.first_name for p in standings.ranked if p.excluded_reason == "budget_cap")
    assert capped == ["b", "c", "d"]


def test_team_prizes_follow_member_minimum() -> None:
    team_id = uuid.uuid4()
    team = Participant(
        kind="team",
        user_uuid=None,
        first_name="",
        last_name="",
        team_uuid=team_id,
        team_name="North",
        metric_value=120,
        qualified=True,
    )
    manager = Participant(
        kind="team_manager",
        user_uuid=uuid.uuid4(),
        first_name="Mira",
        last_name="",
        staff_profile_uuid=uuid.uuid4(),
        team_uuid=team_id,
        metric_value=120,
    )
    strong = Participant(
        kind="team_member",
        user_uuid=uuid.uuid4(),
        first_name="Ravi",
        last_name="",
        staff_profile_uuid=uuid.uuid4(),
        team_uuid=team_id,
        metric_value=80,
    )
    weak = Participant(
        kind="team_member",
        user_uuid=uuid.uuid4(),
        first_name="Sam",
        last_name="",
        staff_profile_uuid=uuid.uuid4(),
        team_uuid=team_id,
        metric_value=40,
    )
    standings = _standings([team], [manager, strong, weak])
    decide_winners(
        _contest(
            audience="team",
            team_member_role="telecaller",
            prize_paise=None,
            manager_prize_paise=5_000,
            member_prize_paise=1_000,
            member_min_contribution=50,
        ),
        standings,
    )
    assert team.won and team.prize_paise == 0
    assert (manager.won, manager.prize_paise) == (True, 5_000)
    assert (strong.won, strong.prize_paise) == (True, 1_000)
    assert (weak.won, weak.prize_paise, weak.excluded_reason) == (
        False,
        0,
        "below_member_minimum",
    )


def test_targets_including_at_most_and_connect_rate() -> None:
    loans = ContestCriteria.model_validate(
        {
            "version": 1,
            "loans": {
                "counted_stage": "disbursed",
                "count_at_least": 1,
                "count_at_most": 5,
                "amount_at_least_paise": 5_000_000_00,
            },
        }
    )
    six = Tally(cases={uuid.uuid4(): 1_000_000_00 for _ in range(6)})
    five = Tally(cases={uuid.uuid4(): 1_000_000_00 for _ in range(5)})
    four = Tally(cases={uuid.uuid4(): 1_000_000_00 for _ in range(4)})
    assert not meets_targets(loans, six)  # more than five cases
    assert meets_targets(loans, five)  # ₹50 lakh in five cases
    assert not meets_targets(loans, four)  # ₹40 lakh is short

    calls = ContestCriteria.model_validate(
        {
            "version": 1,
            "activity": {"connect_rate_at_least_percent": 50, "connect_rate_min_calls": 10},
        }
    )
    assert not meets_targets(calls, Tally(calls=4, connected=4))  # too few calls
    assert meets_targets(calls, Tally(calls=10, connected=5))
    assert not meets_targets(calls, Tally(calls=10, connected=4))
