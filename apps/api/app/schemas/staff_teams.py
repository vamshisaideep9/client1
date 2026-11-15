"""Teams of Telecallers / Employees managed by a Sub Admin (CS-019).

Admin shapes manage teams; manager shapes are read-mostly views over the team's
work. No shape exposes another Sub Admin's teams, internal ownership ledgers or
the audit trail.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.staff_analytics import AnalyticsKpi
from app.schemas.telecaller import LeadActivityRead, LeadRequestSummary

TeamLine = Literal["loans", "real_estate"]
TeamMemberRoleLiteral = Literal["telecaller", "employee"]


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Team name is required.")
    return cleaned


class TeamPersonRead(BaseModel):
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


class TeamLastCall(BaseModel):
    disposition: str
    interest_level: str | None
    follow_up_at: datetime | None
    created_at: datetime


class TeamLeadRow(BaseModel):
    id: UUID
    name: str | None
    mobile: str
    status: str
    business_line: TeamLine
    created_at: datetime
    updated_at: datetime
    requests: list[LeadRequestSummary]
    last_call: TeamLastCall | None


class TeamTaskRow(BaseModel):
    id: UUID
    lead_uuid: UUID
    lead_name: str | None
    task_type: str
    status: str
    business_line: TeamLine
    notes: str | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TeamMemberWorkResponse(BaseModel):
    member: TeamMemberRead
    kind: Literal["leads", "tasks"]
    leads: list[TeamLeadRow]
    tasks: list[TeamTaskRow]


class TeamLeadDetailResponse(BaseModel):
    lead: TeamLeadRow
    assigned_to: TeamMemberRead
    activities: list[LeadActivityRead]


class TeamReassignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_staff_profile_uuid: UUID


class TeamReassignResponse(BaseModel):
    id: UUID
    assigned_staff_profile_uuid: UUID
    status: str
