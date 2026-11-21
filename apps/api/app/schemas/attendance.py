"""Attendance API contracts. Leave balances use whole half-day units."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
LeaveType = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
LeaveUnits = Annotated[int, Field(ge=0, le=732)]
Weekday = Annotated[int, Field(ge=0, le=6)]


class AttendanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttendancePolicyInput(AttendanceInput):
    shift_start_minute: Annotated[int, Field(ge=0, le=1439)]
    shift_minutes: Annotated[int, Field(ge=1, le=1440)]
    grace_minutes: Annotated[int, Field(ge=0, le=1440)]
    half_day_minutes: Annotated[int, Field(ge=1, le=1440)]
    full_day_minutes: Annotated[int, Field(ge=1, le=1440)]
    weekly_off: Annotated[list[Weekday], Field(max_length=6)]
    leave_quotas: Annotated[dict[LeaveType, LeaveUnits], Field(max_length=12)]

    @model_validator(mode="after")
    def check_thresholds(self):
        if not self.half_day_minutes <= self.full_day_minutes <= self.shift_minutes:
            raise ValueError("Half-day and full-day thresholds must fit the shift duration.")
        if self.grace_minutes > self.shift_minutes:
            raise ValueError("Grace minutes must fit the shift duration.")
        if len(set(self.weekly_off)) != len(self.weekly_off):
            raise ValueError("Choose each weekly day off once.")
        return self


class AttendancePolicyRead(AttendancePolicyInput):
    model_config = ConfigDict(from_attributes=True)
    version: int
    effective_from: date


class AttendancePolicyState(BaseModel):
    active: AttendancePolicyRead | None
    scheduled: AttendancePolicyRead | None


class AttendanceHolidayInput(AttendanceInput):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class AttendanceHolidayRead(AttendanceHolidayInput):
    model_config = ConfigDict(from_attributes=True)
    day: date


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

    @model_validator(mode="after")
    def valid_period(self):
        if not 0 <= (self.end_day - self.start_day).days <= 30:
            raise ValueError("Choose a leave period of one to 31 days.")
        if self.half_day and self.end_day != self.start_day:
            raise ValueError("Half-day leave must be within one day.")
        return self


class AttendanceDecisionInput(AttendanceInput):
    status: Literal["approved", "rejected", "cancelled"]
    note: Reason
    expected_decisions: Annotated[int, Field(ge=0)]


class AttendanceDecisionRead(BaseModel):
    status: RequestStatus
    actor_id: UUID
    actor_role: str
    at: datetime
    note: str


class AttendanceRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    staff_profile_id: UUID
    kind: Literal["leave", "correction"]
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


class AttendanceBalance(BaseModel):
    leave_type: LeaveType
    allocated_units: int
    used_units: int


class MyAttendanceRead(BaseModel):
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
    role: Literal["telecaller", "employee"]


class AttendanceRosterRead(BaseModel):
    configured: bool
    members: list[AttendanceRosterMember]
    days: list[AttendanceDayRead]
    total: int


class AttendanceInboxRead(BaseModel):
    requests: list[AttendanceRequestRead]
    total: int
