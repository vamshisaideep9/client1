"""Contest contracts (CS-027).

``ContestCriteria`` is the closed, versioned grammar stored in
``contests.criteria``. Like ``AudienceRules`` it is never arbitrary JSON:
unknown keys, duplicate values, inverted ranges and dimensions that do not
belong to the contest's line or audience fail closed, on authoring and again
before scoring.

Targets are "at least" conditions, with one exception the product asked for:
a case or deal count may also carry an "at most" bound ("5 cases or fewer"),
but only beside an "at least" bound, because an at-most rule on its own would
reward doing less. Every populated target must be met to qualify.

Always-on eligibility, not expressed in the grammar: an active account and
profile on the contest's line (an Agent's line, a Telecaller or Employee
assigned to it or to both lines, or a team on it).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.contest import (
    ContestAudience,
    ContestMetric,
    ContestPrizeKind,
    ContestStatus,
    ContestTeamMemberRole,
    ContestWinMode,
)
from app.models.property import PROPERTY_CATEGORY_BY_SUBTYPE, PropertySubtype

CRITERIA_VERSION = 1
MAX_FILTER_VALUES = 50
MAX_COUNT_TARGET = 100_000
MAX_AMOUNT_PAISE = 10_000_000_000_000  # ₹1 lakh crore; bounds arithmetic only
MAX_PRIZE_PAISE = 1_000_000_000  # ₹1 crore per prize (matches the DB CHECK)
MAX_BUDGET_PAISE = 100_000_000_000  # ₹100 crore
MAX_DURATION_DAYS = 366
MAX_TOP_N = 100

LoanStage = Literal["submitted", "sanctioned", "disbursed"]
DealStage = Literal["site_visit_done", "booked", "agreement_signed", "closed"]
PropertyCategoryValue = Literal["houses", "apartments", "villas", "plots", "commercial"]
PropertySubtypeValue = Literal[
    "individual_house",
    "standalone_apartment",
    "gated_community_apartment",
    "villa",
    "locked_space",
    "unlocked_space",
    "plot",
    "farmland",
    "agriland",
]
ListingIntentValue = Literal["sale", "rent"]
CityName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

CountTarget = Annotated[int, Field(ge=1, le=MAX_COUNT_TARGET)]
AmountPaise = Annotated[int, Field(ge=1, le=MAX_AMOUNT_PAISE)]
AmountBound = Annotated[int, Field(ge=0, le=MAX_AMOUNT_PAISE)]


def _unique(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("Contest filter values must be unique.")
    return values


class _CaseTargets(BaseModel):
    """Count and total targets shared by the loan and real-estate blocks."""

    model_config = ConfigDict(extra="forbid")

    count_at_least: CountTarget | None = None
    count_at_most: CountTarget | None = None

    def _check_counts(self) -> None:
        if self.count_at_most is not None:
            if self.count_at_least is None:
                # Product decision (CS-027): "N or fewer" alone rewards doing less.
                raise ValueError("An at-most case count needs an at-least case count as well.")
            if self.count_at_most < self.count_at_least:
                raise ValueError("The at-most case count is below the at-least case count.")


class LoanCriteria(_CaseTargets):
    """Which loan cases count, at which stage, and the case targets.

    A case's true amount is read live at the counted stage: the requested
    amount when submitted, the sanctioned amount once sanctioned or disbursed.
    """

    loan_type_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILTER_VALUES)
    bank_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILTER_VALUES)
    case_amount_min_paise: AmountBound | None = None
    case_amount_max_paise: AmountPaise | None = None
    counted_stage: LoanStage
    amount_at_least_paise: AmountPaise | None = None

    @field_validator("loan_type_ids", "bank_ids")
    @classmethod
    def values_are_unique(cls, values: list[UUID]) -> list[UUID]:
        return _unique(values)

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> LoanCriteria:
        if (
            self.case_amount_min_paise is not None
            and self.case_amount_max_paise is not None
            and self.case_amount_max_paise < self.case_amount_min_paise
        ):
            raise ValueError("The per-case maximum amount is below the minimum.")
        self._check_counts()
        return self

    @property
    def has_target(self) -> bool:
        return self.count_at_least is not None or self.amount_at_least_paise is not None


class RealEstateCriteria(_CaseTargets):
    """Which property deals count, at which stage, and the deal targets.

    A deal's true value is its quoted price, or the listing price until a
    price is quoted (quotes start at booking).
    """

    property_categories: list[PropertyCategoryValue] = Field(default_factory=list, max_length=5)
    property_subtypes: list[PropertySubtypeValue] = Field(default_factory=list, max_length=9)
    listing_intents: list[ListingIntentValue] = Field(default_factory=list, max_length=2)
    cities: list[CityName] = Field(default_factory=list, max_length=MAX_FILTER_VALUES)
    deal_value_min_paise: AmountBound | None = None
    deal_value_max_paise: AmountPaise | None = None
    counted_stage: DealStage
    value_at_least_paise: AmountPaise | None = None

    @field_validator("property_categories", "property_subtypes", "listing_intents")
    @classmethod
    def values_are_unique(cls, values: list[str]) -> list[str]:
        return _unique(values)

    @field_validator("cities")
    @classmethod
    def cities_are_unique(cls, values: list[str]) -> list[str]:
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("Contest filter values must be unique.")
        return values

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> RealEstateCriteria:
        if (
            self.deal_value_min_paise is not None
            and self.deal_value_max_paise is not None
            and self.deal_value_max_paise < self.deal_value_min_paise
        ):
            raise ValueError("The per-deal maximum value is below the minimum.")
        if self.property_categories and self.property_subtypes:
            categories = set(self.property_categories)
            for subtype in self.property_subtypes:
                if PROPERTY_CATEGORY_BY_SUBTYPE[PropertySubtype(subtype)].value not in categories:
                    raise ValueError("A property type does not belong to a chosen category.")
        self._check_counts()
        return self

    @property
    def has_target(self) -> bool:
        return self.count_at_least is not None or self.value_at_least_paise is not None


class ActivityCriteria(BaseModel):
    """Staff activity targets inside the contest window.

    Telecallers: calls logged, connect rate (with a minimum number of calls),
    follow-ups kept on time, site visits completed on leads they hold.
    Employees: tasks completed, tasks completed on time, site visits completed
    (property-visit tasks). Site visits exist on the real-estate line only.
    """

    model_config = ConfigDict(extra="forbid")

    calls_logged_at_least: CountTarget | None = None
    connect_rate_at_least_percent: Annotated[int, Field(ge=1, le=100)] | None = None
    connect_rate_min_calls: CountTarget | None = None
    follow_ups_on_time_at_least: CountTarget | None = None
    tasks_completed_at_least: CountTarget | None = None
    tasks_on_time_at_least: CountTarget | None = None
    site_visits_completed_at_least: CountTarget | None = None

    @model_validator(mode="after")
    def connect_rate_needs_minimum_calls(self) -> ActivityCriteria:
        if (self.connect_rate_at_least_percent is None) != (self.connect_rate_min_calls is None):
            raise ValueError(
                "A connect-rate target needs a minimum number of calls, and only then."
            )
        if not self.populated:
            raise ValueError("Add at least one activity target or remove the activity section.")
        return self

    @property
    def populated(self) -> set[str]:
        return {
            name
            for name in (
                "calls_logged_at_least",
                "connect_rate_at_least_percent",
                "follow_ups_on_time_at_least",
                "tasks_completed_at_least",
                "tasks_on_time_at_least",
                "site_visits_completed_at_least",
            )
            if getattr(self, name) is not None
        }


class EligibilityCriteria(BaseModel):
    """Who may take part, beyond the always-on active-profile and line rule."""

    model_config = ConfigDict(extra="forbid")

    min_tenure_days: Annotated[int, Field(ge=0, le=3650)] = 0
    kyc_verified: bool = False


class ContestCriteria(BaseModel):
    """Version 1 of the contest criteria grammar."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = CRITERIA_VERSION
    loans: LoanCriteria | None = None
    real_estate: RealEstateCriteria | None = None
    activity: ActivityCriteria | None = None
    eligibility: EligibilityCriteria = Field(default_factory=EligibilityCriteria)

    @model_validator(mode="before")
    @classmethod
    def requires_explicit_version(cls, data: object) -> object:
        if isinstance(data, dict) and "version" not in data:
            raise ValueError("Contest criteria require an explicit version.")
        return data

    @model_validator(mode="after")
    def one_business_block(self) -> ContestCriteria:
        if self.loans is not None and self.real_estate is not None:
            raise ValueError("A contest counts loan cases or property deals, not both.")
        return self

    @property
    def business(self) -> LoanCriteria | RealEstateCriteria | None:
        return self.loans or self.real_estate

    @property
    def has_target(self) -> bool:
        business = self.business
        return bool((business is not None and business.has_target) or self.activity is not None)


# Which activity targets each staff role can be measured on.
TELECALLER_ACTIVITY = frozenset(
    {
        "calls_logged_at_least",
        "connect_rate_at_least_percent",
        "follow_ups_on_time_at_least",
        "site_visits_completed_at_least",
    }
)
EMPLOYEE_ACTIVITY = frozenset(
    {"tasks_completed_at_least", "tasks_on_time_at_least", "site_visits_completed_at_least"}
)
_ACTIVITY_METRIC_TARGET = {
    ContestMetric.CALLS_LOGGED: "calls_logged_at_least",
    ContestMetric.FOLLOW_UPS_ON_TIME: "follow_ups_on_time_at_least",
    ContestMetric.TASKS_COMPLETED: "tasks_completed_at_least",
    ContestMetric.TASKS_ON_TIME: "tasks_on_time_at_least",
    ContestMetric.SITE_VISITS_COMPLETED: "site_visits_completed_at_least",
}


def participant_role(audience: str, team_member_role: str | None) -> str:
    """The person role whose work is scored: the audience, or a team's members."""
    if audience == ContestAudience.TEAM:
        return team_member_role or ""
    return audience


def validate_definition(
    *,
    business_line: str,
    audience: str,
    team_member_role: str | None,
    metric: str,
    criteria: ContestCriteria,
    win_mode: str,
) -> None:
    """Cross-field rules between a contest and its criteria. Raises ValueError."""
    role = participant_role(audience, team_member_role)

    if criteria.loans is not None and business_line != "loans":
        raise ValueError("Loan case conditions apply only to a Loans contest.")
    if criteria.real_estate is not None and business_line != "real_estate":
        raise ValueError("Property deal conditions apply only to a Real estate contest.")

    if role == "agent":
        if criteria.business is None:
            raise ValueError("An Agent contest counts loan cases or property deals.")
        if criteria.activity is not None:
            raise ValueError("Activity targets apply to Telecallers and Employees only.")
    if criteria.eligibility.kyc_verified and role != "agent":
        raise ValueError("The KYC condition applies to Agent contests only.")

    if criteria.activity is not None:
        allowed = TELECALLER_ACTIVITY if role == "telecaller" else EMPLOYEE_ACTIVITY
        unsupported = criteria.activity.populated - allowed
        if unsupported:
            label = "Telecallers" if role == "employee" else "Employees"
            raise ValueError(f"Those activity targets apply to {label} only.")
        if (
            criteria.activity.site_visits_completed_at_least is not None
            and business_line != "real_estate"
        ):
            raise ValueError("Site visit targets apply to Real estate contests only.")

    if metric in (ContestMetric.CASES, ContestMetric.AMOUNT):
        if criteria.business is None:
            raise ValueError("Ranking by cases or amount needs loan case or deal conditions.")
    else:
        target = _ACTIVITY_METRIC_TARGET[ContestMetric(metric)]
        allowed = TELECALLER_ACTIVITY if role == "telecaller" else EMPLOYEE_ACTIVITY
        if role == "agent" or target not in allowed:
            raise ValueError("That ranking metric does not apply to this audience.")
        if metric == ContestMetric.SITE_VISITS_COMPLETED and business_line != "real_estate":
            raise ValueError("Site visit targets apply to Real estate contests only.")

    if win_mode == ContestWinMode.THRESHOLD and not criteria.has_target:
        raise ValueError("Everyone-who-hits-the-target contests need at least one target.")


class ContestItemPrize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    estimated_value_paise: Annotated[int, Field(ge=1, le=MAX_PRIZE_PAISE)] | None = None


class ContestScheduleAndPrize(BaseModel):
    start_time: time = time.min
    end_time: time = time(23, 59)
    prize_kind: ContestPrizeKind = ContestPrizeKind.CASH
    item_prize: ContestItemPrize | None = None
    manager_item_prize: ContestItemPrize | None = None
    member_item_prize: ContestItemPrize | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def local_minute(cls, value: time) -> time:
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Use an IST time at minute precision, without an offset.")
        return value


class ContestDefinition(ContestScheduleAndPrize):
    """What a Sub Admin authors. Shared by create and full update."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None
    ) = None
    terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    business_line: Literal["loans", "real_estate"]
    audience: ContestAudience
    team_member_role: ContestTeamMemberRole | None = None
    metric: ContestMetric
    criteria: ContestCriteria
    win_mode: ContestWinMode
    top_n: Annotated[int, Field(ge=1, le=MAX_TOP_N)] | None = None
    prize_paise: Annotated[int, Field(ge=1, le=MAX_PRIZE_PAISE)] | None = None
    manager_prize_paise: Annotated[int, Field(ge=0, le=MAX_PRIZE_PAISE)] | None = None
    member_prize_paise: Annotated[int, Field(ge=0, le=MAX_PRIZE_PAISE)] | None = None
    member_min_contribution: Annotated[int, Field(ge=1, le=MAX_AMOUNT_PAISE)] | None = None
    budget_cap_paise: Annotated[int, Field(ge=1, le=MAX_BUDGET_PAISE)] | None = None
    starts_on: date
    ends_on: date

    @model_validator(mode="after")
    def definition_is_consistent(self) -> ContestDefinition:
        if (self.audience == ContestAudience.TEAM) != (self.team_member_role is not None):
            raise ValueError("Choose the member role for a team contest, and only then.")
        if (self.win_mode == ContestWinMode.TOP_N) != (self.top_n is not None):
            raise ValueError("Set how many winners for a top-N contest, and only then.")
        if self.prize_kind == ContestPrizeKind.ITEM:
            if any(
                value is not None
                for value in (
                    self.prize_paise,
                    self.manager_prize_paise,
                    self.member_prize_paise,
                    self.budget_cap_paise,
                )
            ):
                raise ValueError("Cash amounts and budget caps apply to cash prizes only.")
            if self.audience == ContestAudience.TEAM:
                if self.item_prize or not (self.manager_item_prize or self.member_item_prize):
                    raise ValueError("Set an item for the manager, members or both.")
            elif not self.item_prize or self.manager_item_prize or self.member_item_prize:
                raise ValueError("Set an item for each individual winner.")
            if bool(self.member_item_prize) != (self.member_min_contribution is not None):
                raise ValueError("A minimum contribution applies only with a member prize.")
        else:
            self._validate_cash_prizes()
        if self.ends_on < self.starts_on:
            raise ValueError("The end date is before the start date.")
        if self.ends_on == self.starts_on and self.end_time < self.start_time:
            raise ValueError("The end time is before the start time.")
        if (self.ends_on - self.starts_on).days > MAX_DURATION_DAYS:
            raise ValueError("A contest can run for at most 366 days.")
        validate_definition(
            business_line=self.business_line,
            audience=self.audience.value,
            team_member_role=self.team_member_role.value if self.team_member_role else None,
            metric=self.metric.value,
            criteria=self.criteria,
            win_mode=self.win_mode.value,
        )
        return self

    def _validate_cash_prizes(self) -> None:
        if self.item_prize or self.manager_item_prize or self.member_item_prize:
            raise ValueError("Item details apply to item prizes only.")
        if self.audience == ContestAudience.TEAM:
            if self.prize_paise is not None:
                raise ValueError("A team contest pays a manager prize and a member prize.")
            manager = self.manager_prize_paise or 0
            member = self.member_prize_paise or 0
            if self.manager_prize_paise is None or self.member_prize_paise is None:
                raise ValueError("Set the manager prize and the member prize (either may be 0).")
            if manager + member <= 0:
                raise ValueError("A team contest needs a manager or member prize.")
            if member > 0 and self.member_min_contribution is None:
                raise ValueError("A member prize needs a minimum contribution per member.")
            if member == 0 and self.member_min_contribution is not None:
                raise ValueError("A minimum contribution applies only with a member prize.")
            smallest_win = manager + member
        else:
            if self.prize_paise is None:
                raise ValueError("Set the prize for each winner.")
            if (
                self.manager_prize_paise is not None
                or self.member_prize_paise is not None
                or self.member_min_contribution is not None
            ):
                raise ValueError("Manager and member prizes apply to team contests only.")
            smallest_win = self.prize_paise
        if self.budget_cap_paise is not None and self.budget_cap_paise < smallest_win:
            raise ValueError("The budget cap is below a single prize.")


class ContestAdminUpdate(ContestDefinition):
    expected_version: Annotated[int, Field(ge=1)]


class ContestCancel(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class ContestReject(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ContestPrizeMarkPaid(BaseModel):
    """How a staff prize was paid (for example "November payroll"). No
    personal or bank details."""

    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]

    @field_validator("reference")
    @classmethod
    def no_long_numbers(cls, value: str) -> str:
        # Security review: keep account, phone and ID numbers out of a record
        # Admins and auditors read; seven or more digits in a row is refused.
        if re.search(r"\d{7,}", value):
            raise ValueError("Leave out account, phone or ID numbers.")
        return value


class ContestPrizePayoutResponse(BaseModel):
    payout_id: UUID


class ContestResultPayment(BaseModel):
    result_id: UUID
    payment_status: str
    paid_marked_at: datetime | None
    paid_reference: str | None


class ContestRead(ContestScheduleAndPrize):
    id: UUID
    title: str
    description: str | None
    terms: str | None
    business_line: Literal["loans", "real_estate"]
    audience: ContestAudience
    team_member_role: ContestTeamMemberRole | None
    metric: ContestMetric
    criteria: ContestCriteria
    win_mode: ContestWinMode
    top_n: int | None
    prize_paise: int | None
    manager_prize_paise: int | None
    member_prize_paise: int | None
    member_min_contribution: int | None
    budget_cap_paise: int | None
    starts_on: date
    ends_on: date
    status: ContestStatus
    created_by_uuid: UUID
    created_by_name: str | None
    is_mine: bool
    submitted_at: datetime | None
    checker_name: str | None
    reviewed_at: datetime | None
    review_note: str | None
    live_at: datetime | None
    ended_at: datetime | None
    finalized_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ContestListResponse(BaseModel):
    contests: list[ContestRead]
    total: int


class ContestProgress(BaseModel):
    """Achieved numbers for the populated targets (absent ones are null)."""

    count: int | None = None
    amount_paise: int | None = None
    calls_logged: int | None = None
    connect_rate_percent: int | None = None
    follow_ups_on_time: int | None = None
    tasks_completed: int | None = None
    tasks_on_time: int | None = None
    site_visits_completed: int | None = None


ContestRole = Literal["participant", "team_member", "team_manager"]


class MyStanding(BaseModel):
    """The caller's own standing (or their team's, for a manager)."""

    rank: int | None
    metric_value: int
    progress: ContestProgress
    qualified: bool
    won: bool | None = None
    prize_paise: int | None = None
    item_prize: ContestItemPrize | None = None
    payment_status: str | None = None
    excluded_reason: str | None = None


class LeaderboardEntry(BaseModel):
    """Display name, rank and achieved value only. A name or amount the Admin
    hides from this role is null for everyone but the caller."""

    rank: int | None
    name: str | None
    achieved: int | None
    qualified: bool
    is_me: bool


class TeamMemberStanding(BaseModel):
    name: str
    metric_value: int
    progress: ContestProgress
    meets_member_minimum: bool | None
    won: bool | None = None
    prize_paise: int | None = None
    item_prize: ContestItemPrize | None = None
    payment_status: str | None = None
    is_me: bool = False


class TeamStanding(BaseModel):
    team_name: str
    rank: int | None
    metric_value: int
    progress: ContestProgress
    qualified: bool
    won: bool | None = None
    members: list[TeamMemberStanding]


class MyContestSummary(ContestScheduleAndPrize):
    id: UUID
    title: str
    business_line: Literal["loans", "real_estate"]
    audience: ContestAudience
    team_member_role: ContestTeamMemberRole | None
    metric: ContestMetric
    win_mode: ContestWinMode
    top_n: int | None
    prize_paise: int | None
    manager_prize_paise: int | None
    member_prize_paise: int | None
    member_min_contribution: int | None
    starts_on: date
    ends_on: date
    status: ContestStatus
    my_role: ContestRole
    eligible: bool
    participants: int | None
    me: MyStanding | None


class MyContestListResponse(BaseModel):
    contests: list[MyContestSummary]


class MyContestDetail(MyContestSummary):
    description: str | None
    terms: str | None
    criteria: ContestCriteria
    budget_cap_paise: int | None
    computed_at: datetime | None
    leaderboard: list[LeaderboardEntry]
    team: TeamStanding | None


class StandingRow(BaseModel):
    """One row of the Admin's full standings (names in full)."""

    result_id: UUID | None
    kind: str
    participant_type: Literal["agent", "staff", "team"]
    # Lets the Admin's prize payout dialog offer the Agent's saved destination.
    agent_profile_uuid: UUID | None = None
    name: str
    team_name: str | None
    rank: int | None
    metric_value: int
    achieved_count: int
    achieved_amount_paise: int
    progress: ContestProgress
    qualified: bool
    won: bool
    prize_paise: int
    item_prize: ContestItemPrize | None = None
    excluded_reason: str | None
    payment_status: str
    payout_uuid: UUID | None
    paid_reference: str | None
    paid_marked_at: datetime | None


class ContestStandingsResponse(BaseModel):
    contest: ContestRead
    source: Literal["live", "snapshot", "none"]
    computed_at: datetime | None
    rows: list[StandingRow]
    team_people: list[StandingRow]
    winners: int
    prize_total_paise: int
    paid_total_paise: int
