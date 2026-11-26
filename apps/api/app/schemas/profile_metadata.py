"""Minimal role identifiers shared by own-profile and authorized staff views."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileTeamRead(BaseModel):
    business_line: Literal["loans", "real_estate"]
    name: str


class RoleProfileRead(BaseModel):
    profile_uuid: UUID
    role: Literal["admin", "sub_admin", "telecaller", "employee", "agent"]
    code: str
    business_line: Literal["loans", "real_estate", "both"] | None
    teams: list[ProfileTeamRead] = Field(default_factory=list)
    loan_specialty_id: UUID | None = None
    loan_specialty_label: str | None = None


class TaskStaffRead(BaseModel):
    raised_by_telecaller_name: str | None = None
    raised_by_telecaller_code: str | None = None
    assigned_employee_name: str | None = None
    assigned_employee_code: str | None = None
