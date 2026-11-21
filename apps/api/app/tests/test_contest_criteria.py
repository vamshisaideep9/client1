"""CS-027 contest criteria grammar and definition rules (no database)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.contests import ContestCriteria, ContestDefinition

START = date(2030, 1, 1)


def _definition(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Personal loan sprint",
        "business_line": "loans",
        "audience": "agent",
        "metric": "amount",
        "criteria": {
            "version": 1,
            "loans": {"counted_stage": "disbursed", "count_at_least": 1},
        },
        "win_mode": "threshold",
        "prize_paise": 1_000_00,
        "starts_on": START.isoformat(),
        "ends_on": (START + timedelta(days=30)).isoformat(),
    }
    body.update(overrides)
    return body


def _invalid(match: str, **overrides: Any) -> None:
    with pytest.raises(ValidationError, match=match):
        ContestDefinition.model_validate(_definition(**overrides))


def test_reference_example_is_valid() -> None:
    """Personal loan, ₹50 lakh total, 5 cases or fewer (with an at-least)."""
    contest = ContestDefinition.model_validate(
        _definition(
            criteria={
                "version": 1,
                "loans": {
                    "loan_type_ids": ["0b6a1c2e-3d4f-4a5b-8c6d-7e8f9a0b1c2d"],
                    "counted_stage": "sanctioned",
                    "count_at_least": 1,
                    "count_at_most": 5,
                    "amount_at_least_paise": 50_00_000_00,
                },
                "eligibility": {"min_tenure_days": 30, "kyc_verified": True},
            }
        )
    )
    assert contest.criteria.loans is not None
    assert contest.criteria.loans.count_at_most == 5


def test_at_most_requires_at_least() -> None:
    _invalid(
        "at-most case count needs an at-least",
        criteria={"version": 1, "loans": {"counted_stage": "disbursed", "count_at_most": 5}},
    )


def test_at_most_below_at_least_is_rejected() -> None:
    _invalid(
        "below the at-least",
        criteria={
            "version": 1,
            "loans": {"counted_stage": "disbursed", "count_at_least": 6, "count_at_most": 5},
        },
    )


def test_inverted_amount_range_is_rejected() -> None:
    _invalid(
        "maximum amount is below",
        criteria={
            "version": 1,
            "loans": {
                "counted_stage": "disbursed",
                "count_at_least": 1,
                "case_amount_min_paise": 500,
                "case_amount_max_paise": 100,
            },
        },
    )


def test_line_mismatched_dimensions_are_rejected() -> None:
    _invalid(
        "apply only to a Loans contest",
        business_line="real_estate",
        criteria={"version": 1, "loans": {"counted_stage": "disbursed", "count_at_least": 1}},
    )
    _invalid(
        "apply only to a Real estate contest",
        criteria={
            "version": 1,
            "real_estate": {"counted_stage": "closed", "count_at_least": 1},
        },
    )


def test_loans_and_real_estate_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not both"):
        ContestCriteria.model_validate(
            {
                "version": 1,
                "loans": {"counted_stage": "disbursed", "count_at_least": 1},
                "real_estate": {"counted_stage": "closed", "count_at_least": 1},
            }
        )


def test_unknown_keys_and_missing_version_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ContestCriteria.model_validate({"version": 1, "anything": True})
    with pytest.raises(ValidationError, match="explicit version"):
        ContestCriteria.model_validate({"loans": {"counted_stage": "disbursed"}})
    with pytest.raises(ValidationError):
        ContestCriteria.model_validate({"version": 2})
    with pytest.raises(ValidationError):
        ContestCriteria.model_validate(
            {"version": 1, "loans": {"counted_stage": "approved", "count_at_least": 1}}
        )


def test_duplicate_filter_values_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ContestCriteria.model_validate(
            {
                "version": 1,
                "real_estate": {
                    "counted_stage": "closed",
                    "count_at_least": 1,
                    "cities": ["Hyderabad", "hyderabad"],
                },
            }
        )


def test_subtype_outside_chosen_category_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not belong"):
        ContestCriteria.model_validate(
            {
                "version": 1,
                "real_estate": {
                    "counted_stage": "closed",
                    "count_at_least": 1,
                    "property_categories": ["villas"],
                    "property_subtypes": ["plot"],
                },
            }
        )


def test_agent_contest_needs_business_and_no_activity() -> None:
    _invalid(
        "counts loan cases or property deals",
        metric="cases",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 10}},
    )
    _invalid(
        "Telecallers and Employees only",
        criteria={
            "version": 1,
            "loans": {"counted_stage": "disbursed", "count_at_least": 1},
            "activity": {"calls_logged_at_least": 10},
        },
    )


def test_activity_targets_follow_the_role() -> None:
    _invalid(
        "apply to Employees only",
        audience="telecaller",
        metric="calls_logged",
        criteria={"version": 1, "activity": {"tasks_completed_at_least": 3}},
    )
    _invalid(
        "apply to Telecallers only",
        audience="employee",
        metric="tasks_completed",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 3}},
    )
    _invalid(
        "Real estate contests only",
        audience="employee",
        metric="tasks_completed",
        criteria={"version": 1, "activity": {"site_visits_completed_at_least": 3}},
    )


def test_connect_rate_needs_minimum_calls() -> None:
    _invalid(
        "minimum number of calls",
        audience="telecaller",
        metric="calls_logged",
        criteria={"version": 1, "activity": {"connect_rate_at_least_percent": 40}},
    )


def test_kyc_condition_is_for_agents_only() -> None:
    _invalid(
        "KYC condition",
        audience="telecaller",
        metric="calls_logged",
        criteria={
            "version": 1,
            "activity": {"calls_logged_at_least": 10},
            "eligibility": {"kyc_verified": True},
        },
    )


def test_metric_must_fit_the_audience_and_criteria() -> None:
    _invalid(
        "does not apply to this audience",
        metric="calls_logged",
    )
    _invalid(
        "needs loan case or deal conditions",
        audience="telecaller",
        metric="cases",
        criteria={"version": 1, "activity": {"calls_logged_at_least": 10}},
    )


def test_threshold_mode_needs_a_target() -> None:
    _invalid(
        "need at least one target",
        criteria={"version": 1, "loans": {"counted_stage": "disbursed"}},
    )
    # A top-N contest may rank on the metric alone.
    ContestDefinition.model_validate(
        _definition(
            criteria={"version": 1, "loans": {"counted_stage": "disbursed"}},
            win_mode="top_n",
            top_n=3,
        )
    )


def test_top_n_shape() -> None:
    _invalid("how many winners", win_mode="top_n")
    _invalid("how many winners", top_n=3)


def test_team_prize_shape() -> None:
    team = {
        "audience": "team",
        "team_member_role": "telecaller",
        "metric": "calls_logged",
        "criteria": {"version": 1, "activity": {"calls_logged_at_least": 500}},
        "prize_paise": None,
        "manager_prize_paise": 5_000_00,
        "member_prize_paise": 1_000_00,
        "member_min_contribution": 50,
    }
    ContestDefinition.model_validate(_definition(**team))
    _invalid("minimum contribution per member", **{**team, "member_min_contribution": None})
    _invalid(
        "manager or member prize", **{**team, "manager_prize_paise": 0, "member_prize_paise": 0}
    )
    _invalid("member role", **{**team, "team_member_role": None})
    _invalid("team contests only", member_prize_paise=1_000_00)


def test_budget_cap_below_one_prize_is_rejected() -> None:
    _invalid("below a single prize", budget_cap_paise=999_00)


def test_dates_are_ordered_and_bounded() -> None:
    _invalid("before the start date", ends_on=(START - timedelta(days=1)).isoformat())
    _invalid("at most 366 days", ends_on=(START + timedelta(days=400)).isoformat())
