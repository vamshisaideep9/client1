"""Attendance API contracts. Leave balances use whole half-day units."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

AttendanceStatus = Literal[
    "checked_in",
    "present",
    "half_day",
    "short_day",
    "absent",
    "missing_checkout",
    "on_leave",
    "holiday",
    "week_off",
]
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]
AttendanceAdjustment = Literal["late_waiver", "early_exit", "on_duty", "holiday_work", "comp_off"]
LeaveSession = Literal["morning", "afternoon"]
AttendanceLeaveCode = Literal["CL", "SL"]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
LeaveType = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
LeaveUnits = Annotated[int, Field(ge=0, le=732)]
Weekday = Annotated[int, Field(ge=0, le=6)]
AttendanceLine = Literal["loans", "real_estate"]


class AttendanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttendanceMonthlyLeaveRule(AttendanceInput):
    accrual_units: Annotated[int, Field(gt=0, le=62)]
    carry_units: LeaveUnits = 0
    sandwich: bool = False
    certificate_after_days: Annotated[int, Field(ge=0, lt=31)] | None = None


class AttendancePolicyInput(AttendanceInput):
    shift_start_minute: Annotated[int, Field(ge=0, le=1439)]
    shift_minutes: Annotated[int, Field(ge=1, le=1440)]
    grace_minutes: Annotated[int, Field(ge=0, le=1440)]
    half_day_minutes: Annotated[int, Field(ge=1, le=1440)]
    full_day_minutes: Annotated[int, Field(ge=1, le=1440)]
    weekly_off: Annotated[list[Weekday], Field(max_length=6)]
    leave_quotas: Annotated[dict[LeaveType, LeaveUnits], Field(max_length=12)]
    session_clock: bool = False
    monthly_leave_rules: Annotated[
        dict[LeaveType, AttendanceMonthlyLeaveRule], Field(max_length=12)
    ] = Field(default_factory=dict)
    certificate_retention_days: Annotated[int, Field(ge=1, le=3660)] | None = None

    @model_validator(mode="after")
    def check_thresholds(self):
        if self.monthly_leave_rules and (
            not self.session_clock
            or not self.monthly_leave_rules.keys() <= self.leave_quotas.keys()
        ):
            raise ValueError("Configure monthly rules for leave types in the session clock.")
        if (
            any(
                rule.certificate_after_days is not None
                for rule in self.monthly_leave_rules.values()
            )
            and self.certificate_retention_days is None
        ):
            raise ValueError("Set certificate retention before requiring a certificate.")
        if not self.half_day_minutes <= self.full_day_minutes <= self.shift_minutes:
            raise ValueError("Half-day and full-day thresholds must fit the shift duration.")
        if self.grace_minutes > self.shift_minutes:
            raise ValueError("Grace minutes must fit the shift duration.")
        if len(set(self.weekly_off)) != len(self.weekly_off):
            raise ValueError("Choose each weekly day off once.")
        if self.session_clock and (
            self.shift_start_minute != 570
            or self.shift_minutes != 540
            or self.grace_minutes != 15
            or self.weekly_off != [6]
        ):
            raise ValueError("The session clock uses 9:30–18:30 IST and Sunday weekly off.")
        return self


class AttendancePolicyRead(AttendancePolicyInput):
    model_config = ConfigDict(from_attributes=True)
    version: int
    effective_from: date


class AttendancePolicyState(BaseModel):
    active: AttendancePolicyRead | None
    scheduled: AttendancePolicyRead | None
    can_configure_leave_rules: bool = False


class AttendanceHolidayInput(AttendanceInput):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class AttendanceHolidayRead(AttendanceHolidayInput):
    model_config = ConfigDict(from_attributes=True)
    day: date


class AttendanceEmploymentInput(AttendanceInput):
    start_day: Annotated[date, Field(ge=date(2000, 1, 1), le=date(9998, 12, 31))]
    end_day: Annotated[date, Field(le=date(9998, 12, 31))] | None = None
    business_line: AttendanceLine
    reviewer_id: UUID | None = None
    expected_version: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_day is not None and self.end_day < self.start_day:
            raise ValueError("The end date must be on or after the start date.")
        return self


class AttendanceEmploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    staff_profile_id: UUID
    start_day: date
    end_day: date | None
    business_line: AttendanceLine
    reviewer_id: UUID | None
    version: int


class AttendanceDayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    staff_profile_id: UUID
    day: date
    policy_version: int
    status: AttendanceStatus
    source: Literal["clock", "rollover", "leave", "correction"]
    original_check_in: datetime | None
    original_check_out: datetime | None
    check_in: datetime | None
    check_out: datetime | None
    worked_minutes: int
    late: bool
    leave_units: int
    system_check_out: datetime | None = None
    calendar_status: Literal["absent", "holiday", "week_off"] | None = None
    morning_covered: bool | None = None
    afternoon_covered: bool | None = None
    early_exit: bool = False
    lop_units: int | None = None
    adjustments: list[AttendanceAdjustment] = Field(default_factory=list)
    leave_sessions: list[LeaveSession] = Field(default_factory=list)
    leave_codes: list[AttendanceLeaveCode] = Field(default_factory=list)

    @field_validator("adjustments", "leave_sessions", mode="before")
    @classmethod
    def adjustment_names(cls, value):
        return sorted(value) if isinstance(value, dict) else value


class AttendanceCorrectionInput(AttendanceInput):
    day: date
    check_in: AwareDatetime
    check_out: AwareDatetime
    reason: Reason

    @model_validator(mode="after")
    def ordered(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in.")
        return self


class AttendanceLeaveInput(AttendanceInput):
    start_day: date
    end_day: date
    leave_type: LeaveType
    half_day: bool
    reason: Reason
    leave_session: LeaveSession | None = None

    @model_validator(mode="after")
    def valid_period(self):
        if not 0 <= (self.end_day - self.start_day).days <= 30:
            raise ValueError("Choose a leave period of one to 31 days.")
        if self.half_day and self.end_day != self.start_day:
            raise ValueError("Half-day leave must be within one day.")
        if self.leave_session and not self.half_day:
            raise ValueError("Choose a session only for half-day leave.")
        return self


class AttendanceAdjustmentInput(AttendanceInput):
    day: date
    adjustment_type: AttendanceAdjustment
    reason: Reason


class AttendanceDecisionInput(AttendanceInput):
    status: Literal["approved", "rejected", "cancelled"]
    note: Reason
    expected_decisions: Annotated[int, Field(ge=0)]
    stage: Literal["recommendation", "decision"] = "decision"


class AttendanceDecisionRead(BaseModel):
    status: RequestStatus
    actor_id: UUID
    actor_role: str
    at: datetime
    note: str
    stage: Literal["recommendation", "decision"] | None = None


class AttendanceRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    staff_profile_id: UUID
    kind: Literal["leave", "correction", "adjustment"]
    status: RequestStatus
    start_day: date
    end_day: date
    reason: str
    leave_type: LeaveType | None
    half_day: bool
    requested_check_in: datetime | None
    requested_check_out: datetime | None
    approved_units: dict[str, int]
    decisions: list[AttendanceDecisionRead]
    created_at: datetime
    two_stage: bool = False
    adjustment_type: AttendanceAdjustment | None = None
    leave_session: LeaveSession | None = None
    certificate_required: bool = False


class AttendanceBalance(BaseModel):
    leave_type: LeaveType
    allocated_units: int
    used_units: int
    month: date | None = None

    @model_serializer(mode="wrap")
    def serialize_period(self, handler: SerializerFunctionWrapHandler):
        result = handler(self)
        if self.month is None:
            result.pop("month", None)
        return result


class MyAttendanceRead(BaseModel):
    employment_start: date | None = None
    employment_end: date | None = None
    policy: AttendancePolicyRead | None
    server_time: datetime
    work_day: date
    today: AttendanceDayRead | None
    days: list[AttendanceDayRead]
    holidays: list[AttendanceHolidayRead]
    requests: list[AttendanceRequestRead]
    balance_year: int
    balances: list[AttendanceBalance]


class AttendanceRosterMember(BaseModel):
    staff_profile_id: UUID
    name: str
    staff_code: str
    role: Literal["telecaller", "employee", "sub_admin"]


class AttendanceRosterRead(BaseModel):
    configured: bool
    members: list[AttendanceRosterMember]
    days: list[AttendanceDayRead]
    total: int


class AttendanceInboxRead(BaseModel):
    requests: list[AttendanceRequestRead]
    total: int


class AttendanceMonthAction(AttendanceInput):
    expected_version: Annotated[int, Field(ge=0)]
    note: Reason


class AttendanceMonthTotal(BaseModel):
    business_line: AttendanceLine | None
    recorded_days: int
    worked_minutes: int
    leave_units: int
    sandwich_units: int = 0
    lop_units: int
    late_days: int
    absences: int


class AttendanceMonthRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    closed_at: datetime
    reopened_at: datetime | None
    totals: list[AttendanceMonthTotal]


class AttendanceMonthRead(BaseModel):
    month: date
    can_close: bool
    close_blocker: str | None = None
    totals: list[AttendanceMonthTotal]
    revisions: list[AttendanceMonthRevisionRead]
