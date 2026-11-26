"""Teams of Telecallers / Employees managed by a Sub Admin (CS-019).

Admin shapes manage teams; manager shapes are read-mostly views over the team's
work. No shape exposes another Sub Admin's teams, internal ownership ledgers or
the audit trail.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.lead_reference import LeadRef
from app.schemas.staff_analytics import AnalyticsKpi, StaffAnalyticsResponse
from app.schemas.telecaller import (
    STAFF_NOTE_MAX_CHARS,
    CallDispositionLiteral,
    InterestLevelLiteral,
    LeadActivityRead,
    LeadFacets,
    LeadReferrerRead,
    LeadRequestSummary,
    LeadTransactionSummary,
    LoanStatusLiteral,
    ManagerNoteRead,
)

TeamLine = Literal["loans", "real_estate"]
TeamMemberRoleLiteral = Literal["telecaller", "employee"]


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Team name is required.")
    return cleaned


class TeamPersonRead(BaseModel):
    loan_specialty_id: UUID | None = None
    loan_specialty_label: str | None = None
    staff_profile_uuid: UUID
    first_name: str
    last_name: str
    staff_code: str
    status: str
    business_line: str | None


class TeamMemberRead(TeamPersonRead):
    added_at: datetime


class StaffTeamRead(BaseModel):
    id: UUID
    name: str
    business_line: TeamLine
    member_role: TeamMemberRoleLiteral
    manager: TeamPersonRead
    members: list[TeamMemberRead]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StaffTeamListResponse(BaseModel):
    teams: list[StaffTeamRead]
    can_edit: bool


class StaffTeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    business_line: TeamLine
    member_role: TeamMemberRoleLiteral
    manager_staff_profile_uuid: UUID

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class StaffTeamUpdate(BaseModel):
    """Rename, hand to another manager, or archive. Archiving is final."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    manager_staff_profile_uuid: UUID | None = None
    archive: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class TeamEligibleResponse(BaseModel):
    """Pickers: Sub Admins free to manage a team in this line, and active staff
    of the member role who are not yet in a team in this line."""

    managers: list[TeamPersonRead]
    members: list[TeamPersonRead]


# --- Manager views ------------------------------------------------------------


class ManagerTeamsResponse(BaseModel):
    teams: list[StaffTeamRead]


class TeamMemberSummary(BaseModel):
    member: TeamMemberRead
    kpis: list[AnalyticsKpi]


class TeamOverviewResponse(BaseModel):
    team: StaffTeamRead
    date_from: date
    date_to: date
    range_days: int
    totals: list[AnalyticsKpi]
    members: list[TeamMemberSummary]
    # The chosen members' analytics summed into one report (KPIs, trend,
    # breakdowns, funnel); null when no member is selected.
    report: StaffAnalyticsResponse | None = None
    # Filters the Admin's field rules for the member role rule out (CS-023).
    hidden_filters: list[str] = Field(default_factory=list)


class TeamLastCall(BaseModel):
    disposition: str
    interest_level: str | None
    follow_up_at: datetime | None
    created_at: datetime


class TeamAssignee(BaseModel):
    staff_profile_uuid: UUID
    first_name: str
    last_name: str


class TeamLeadSignals(BaseModel):
    """What the Telecaller / Employee lists filter on, for the same filters."""

    loan_statuses: list[LoanStatusLiteral] = Field(default_factory=list)
    last_disposition: CallDispositionLiteral | None = None
    last_interest_level: InterestLevelLiteral | None = None
    referrer: LeadReferrerRead | None = None
    # Products, banks and property facts of the lead (CS-023).
    facets: LeadFacets = Field(default_factory=LeadFacets)
    # Telecaller teams on the loans line only, under the Telecaller field rules.
    transactions: LeadTransactionSummary | None = None


class TeamLeadRow(BaseModel):
    id: UUID
    lead_ref: LeadRef
    # Null when the Admin hides it from this team's member role; the key is
    # then listed in hidden_fields so the page can say so.
    name: str | None
    mobile: str
    status: str
    business_line: TeamLine
    created_at: datetime
    updated_at: datetime
    requests: list[LeadRequestSummary]
    last_call: TeamLastCall | None
    assigned_to: TeamAssignee | None = None
    signals: TeamLeadSignals = Field(default_factory=TeamLeadSignals)
    hidden_fields: list[str] = Field(default_factory=list)


class TeamTaskRow(BaseModel):
    id: UUID
    lead_uuid: UUID
    lead_name: str | None
    lead_mobile: str | None = None
    task_type: str
    status: str
    business_line: TeamLine
    notes: str | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    assigned_to: TeamAssignee | None = None
    signals: TeamLeadSignals = Field(default_factory=TeamLeadSignals)
    hidden_fields: list[str] = Field(default_factory=list)


class TeamMemberWorkResponse(BaseModel):
    member: TeamMemberRead
    kind: Literal["leads", "tasks"]
    leads: list[TeamLeadRow]
    tasks: list[TeamTaskRow]


class TeamWorkResponse(BaseModel):
    """Every member's work in one list, for the team-wide filters."""

    team_id: UUID
    kind: Literal["leads", "tasks"]
    leads: list[TeamLeadRow]
    tasks: list[TeamTaskRow]


TeamWorkNoteRead = ManagerNoteRead


class TeamLeadDetailResponse(BaseModel):
    lead: TeamLeadRow
    assigned_to: TeamMemberRead
    activities: list[LeadActivityRead]
    notes: list[TeamWorkNoteRead] = Field(default_factory=list)


class TeamTaskDetailResponse(BaseModel):
    task: TeamTaskRow
    assigned_to: TeamMemberRead
    notes: list[TeamWorkNoteRead] = Field(default_factory=list)


class TeamLeadStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["working", "converted", "closed"]


class TeamTaskUpdate(BaseModel):
    """Change the due date, or cancel with a reason; one at a time."""

    model_config = ConfigDict(extra="forbid")

    due_at: datetime | None = None
    cancel_reason: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def _one_change(self) -> TeamTaskUpdate:
        if (self.due_at is None) == (self.cancel_reason is None):
            raise ValueError("Send either due_at or cancel_reason.")
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone.")
        return self


class TeamNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=STAFF_NOTE_MAX_CHARS)
    follow_up_at: datetime | None = None

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Write a note.")
        return value


class TeamWorkUpdateResponse(BaseModel):
    id: UUID
    status: str
    due_at: datetime | None = None


class TeamReassignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_staff_profile_uuid: UUID


class TeamReassignResponse(BaseModel):
    id: UUID
    assigned_staff_profile_uuid: UUID
    status: str
