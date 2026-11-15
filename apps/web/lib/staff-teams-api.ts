// Sub Admin–led Telecaller / Employee teams (CS-019).
// Admin: every platform Admin reads teams; only the Main Admin writes them.
// Manager: a Sub Admin sees and rebalances only their own team's work. The API
// and PostgreSQL RLS are the boundary; these wrappers carry no authorization.

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";
import type { DateRangeValue } from "@/lib/analytics-range";
import type { StaffAnalytics } from "@/lib/staff-analytics-api";

type Schemas = components["schemas"];

export type StaffTeam = Schemas["StaffTeamRead"];
export type StaffTeamList = Schemas["StaffTeamListResponse"];
export type TeamPerson = Schemas["TeamPersonRead"];
export type TeamMember = Schemas["TeamMemberRead"];
export type TeamEligible = Schemas["TeamEligibleResponse"];
export type StaffTeamCreate = Schemas["StaffTeamCreate"];
export type StaffTeamUpdate = Schemas["StaffTeamUpdate"];
export type TeamLine = StaffTeam["business_line"];
export type TeamMemberRole = StaffTeam["member_role"];

export type ManagerTeams = Schemas["ManagerTeamsResponse"];
export type TeamOverview = Schemas["TeamOverviewResponse"];
export type TeamMemberSummary = Schemas["TeamMemberSummary"];
export type TeamMemberWork = Schemas["TeamMemberWorkResponse"];
export type TeamLeadRow = Schemas["TeamLeadRow"];
export type TeamTaskRow = Schemas["TeamTaskRow"];
export type TeamLeadDetail = Schemas["TeamLeadDetailResponse"];
export type TeamReassignResult = Schemas["TeamReassignResponse"];

export const TEAM_LINE_LABEL: Record<TeamLine, string> = {
  loans: "Loans",
  real_estate: "Real Estate",
};

export const TEAM_ROLE_LABEL: Record<TeamMemberRole, string> = {
  telecaller: "Telecallers",
  employee: "Employees",
};

export function personName(person: Pick<TeamPerson, "first_name" | "last_name">): string {
  return `${person.first_name} ${person.last_name}`.trim();
}

export function teamLabel(team: Pick<StaffTeam, "business_line" | "member_role">): string {
  return `${TEAM_LINE_LABEL[team.business_line]} · ${TEAM_ROLE_LABEL[team.member_role]}`;
}

// --- Admin ---------------------------------------------------------------------

export function listTeams(includeArchived = false): Promise<ApiResponse<StaffTeamList>> {
  return apiRequest<StaffTeamList>(
    `/api/v1/admin/teams${includeArchived ? "?include_archived=true" : ""}`,
  );
}

export function getTeamEligible(
  businessLine: TeamLine,
  memberRole: TeamMemberRole,
): Promise<ApiResponse<TeamEligible>> {
  const params = new URLSearchParams({ business_line: businessLine, member_role: memberRole });
  return apiRequest<TeamEligible>(`/api/v1/admin/teams/eligible?${params.toString()}`);
}

export function createTeam(payload: StaffTeamCreate): Promise<ApiResponse<StaffTeam>> {
  return apiRequest<StaffTeam>("/api/v1/admin/teams", { method: "POST", body: payload });
}

export function updateTeam(
  teamId: string,
  payload: StaffTeamUpdate,
): Promise<ApiResponse<StaffTeam>> {
  return apiRequest<StaffTeam>(`/api/v1/admin/teams/${teamId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function addTeamMember(
  teamId: string,
  staffProfileUuid: string,
): Promise<ApiResponse<StaffTeam>> {
  return apiRequest<StaffTeam>(`/api/v1/admin/teams/${teamId}/members/${staffProfileUuid}`, {
    method: "POST",
  });
}

export function removeTeamMember(
  teamId: string,
  staffProfileUuid: string,
): Promise<ApiResponse<StaffTeam>> {
  return apiRequest<StaffTeam>(`/api/v1/admin/teams/${teamId}/members/${staffProfileUuid}`, {
    method: "DELETE",
  });
}

// --- Manager -------------------------------------------------------------------

function rangeQuery(range: DateRangeValue): string {
  return new URLSearchParams({ date_from: range.dateFrom, date_to: range.dateTo }).toString();
}

export function getMyTeams(): Promise<ApiResponse<ManagerTeams>> {
  return apiRequest<ManagerTeams>("/api/v1/manager/teams");
}

export function getTeamOverview(
  teamId: string,
  range: DateRangeValue,
): Promise<ApiResponse<TeamOverview>> {
  return apiRequest<TeamOverview>(`/api/v1/manager/teams/${teamId}/overview?${rangeQuery(range)}`);
}

export function getMemberAnalytics(
  teamId: string,
  memberId: string,
  range: DateRangeValue,
): Promise<ApiResponse<StaffAnalytics>> {
  return apiRequest<StaffAnalytics>(
    `/api/v1/manager/teams/${teamId}/members/${memberId}/analytics?${rangeQuery(range)}`,
  );
}

export function getMemberWork(
  teamId: string,
  memberId: string,
  scope: "open" | "all",
): Promise<ApiResponse<TeamMemberWork>> {
  return apiRequest<TeamMemberWork>(
    `/api/v1/manager/teams/${teamId}/members/${memberId}/work?scope=${scope}`,
  );
}

export function getTeamLead(teamId: string, leadId: string): Promise<ApiResponse<TeamLeadDetail>> {
  return apiRequest<TeamLeadDetail>(`/api/v1/manager/teams/${teamId}/leads/${leadId}`);
}

export function reassignTeamWork(
  teamId: string,
  kind: "leads" | "tasks",
  id: string,
  toStaffProfileUuid: string,
): Promise<ApiResponse<TeamReassignResult>> {
  return apiRequest<TeamReassignResult>(`/api/v1/manager/teams/${teamId}/${kind}/${id}/reassign`, {
    method: "POST",
    body: { to_staff_profile_uuid: toStaffProfileUuid },
  });
}
