"""Closed catalogue of Sub Admin assignments and business-line actions."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AccessLine = Literal["loans", "real_estate"]
Assignment = Literal["team_manager", "media_sub_admin", "account_manager", "relationship_manager"]
AccessAction = Literal["view", "edit", "review", "prepare", "follow_up"]
AccessStatus = Literal["pending", "active", "inactive"]

ASSIGNMENT_ACTIONS: dict[Assignment, frozenset[AccessAction]] = {
    "team_manager": frozenset(("view", "edit", "review")),
    "media_sub_admin": frozenset(("view", "edit")),
    "account_manager": frozenset(("view", "prepare")),
    "relationship_manager": frozenset(("view", "follow_up")),
}


class SubAdminGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment: Assignment
    business_line: AccessLine
    actions: Annotated[list[AccessAction], Field(min_length=1, max_length=3)]
    agent_profile_ids: Annotated[list[UUID], Field(max_length=100)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_actions(self) -> Self:
        actions = set(self.actions)
        if len(actions) != len(self.actions) or not actions <= ASSIGNMENT_ACTIONS[self.assignment]:
            raise ValueError("Choose supported actions for this assignment.")
        if "view" not in actions:
            raise ValueError("Viewing the assignment is required for its other actions.")
        if self.agent_profile_ids and self.assignment != "relationship_manager":
            raise ValueError("Only Relationship Managers may be assigned Agents.")
        if len(set(self.agent_profile_ids)) != len(self.agent_profile_ids):
            raise ValueError("Choose each Agent only once per assignment.")
        self.agent_profile_ids.sort()
        self.actions = sorted(actions)
        return self


GrantList = Annotated[list[SubAdminGrant], Field(max_length=8)]


def validate_grants(grants: GrantList) -> GrantList:
    keys = [(grant.assignment, grant.business_line) for grant in grants]
    if len(set(keys)) != len(keys):
        raise ValueError("Each assignment and business line may be selected once.")
    return sorted(grants, key=lambda grant: (grant.assignment, grant.business_line))


class SubAdminAccess(BaseModel):
    status: AccessStatus
    grants: GrantList
    version: int

    def lines_for(self, assignment: Assignment, action: AccessAction) -> frozenset[AccessLine]:
        if self.status != "active":
            return frozenset()
        return frozenset(
            grant.business_line
            for grant in self.grants
            if grant.assignment == assignment and action in grant.actions
        )


class SubAdminAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "inactive"]
    grants: GrantList
    expected_version: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        self.grants = validate_grants(self.grants)
        if self.status == "inactive" and self.grants:
            raise ValueError("Deactivated accounts cannot retain dashboard grants.")
        return self


class SubAdminAccessHistory(BaseModel):
    actor_uuid: UUID | None
    created_at: datetime
    before: SubAdminAccess | None
    after: SubAdminAccess


class SubAdminTeamLink(BaseModel):
    id: UUID
    name: str
    business_line: AccessLine


class RelationshipAgent(BaseModel):
    id: UUID
    name: str
    agent_code: str
    business_line: AccessLine
    status: str
    kyc_status: str | None
    approved_at: datetime | None
    submitted_leads: int = 0


class RelationshipManagerRead(BaseModel):
    """An Agent's one Relationship Manager: display name and staff code."""

    staff_profile_id: UUID
    name: str | None
    staff_code: str


class AgentRelationshipManagerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A Sub Admin with an active Relationship Manager grant on the Agent's
    # line; null removes the Agent from every Relationship Manager.
    sub_admin_profile_id: UUID | None


class AgentRelationshipManagerRead(BaseModel):
    agent_profile_id: UUID
    relationship_manager: RelationshipManagerRead | None


class RelationshipManagerOption(BaseModel):
    staff_profile_id: UUID
    name: str | None
    staff_code: str
    business_line: AccessLine
    agent_count: int
    current: bool


class RelationshipLead(BaseModel):
    """A lead of an assigned Agent, read-only for their Relationship Manager.
    Never the lead's name, mobile, email, requirement or notes."""

    id: UUID
    lead_ref: str
    business_line: AccessLine
    status: str
    product_label: str | None
    created_at: datetime
    updated_at: datetime


class RelationshipActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["follow_up", "recommendation"]
    note: Annotated[str, Field(min_length=1, max_length=1000)]


class RelationshipActivity(RelationshipActivityInput):
    id: UUID
    created_at: datetime


class ScopedCommission(BaseModel):
    id: UUID
    business_line: AccessLine
    status: str
    agreed_amount_paise: int
    created_at: datetime
