import type { components } from "@contracts/generated/schema";

import { apiRequest } from "@/lib/api/client";

type Schemas = components["schemas"];
export type SubAdminAccess = Schemas["SubAdminAccess"];
export type SubAdminGrant = Schemas["SubAdminGrant"];
export type AccessLine = SubAdminGrant["business_line"];
export type Assignment = SubAdminGrant["assignment"];
export type AccessAction = SubAdminGrant["actions"][number];
export type RelationshipAgent = Schemas["RelationshipAgent"];
export type RelationshipActivity = Schemas["RelationshipActivity"];
export type RelationshipLead = Schemas["RelationshipLead"];
export type RelationshipManager = Schemas["RelationshipManagerRead"];
export type RelationshipManagerOption = Schemas["RelationshipManagerOption"];
export type AgentRelationshipManager = Schemas["AgentRelationshipManagerRead"];

export const ASSIGNMENTS = {
  team_manager: { label: "Team Manager", path: "/dashboard/team", actions: ["edit", "review"] },
  media_sub_admin: { label: "Media Sub Admin", path: "/dashboard/campaigns", actions: ["edit"] },
  account_manager: { label: "Account Manager", path: "/dashboard/finance", actions: ["prepare"] },
  relationship_manager: { label: "Relationship Manager", path: "/dashboard/relationships", actions: ["follow_up"] },
} as const satisfies Record<Assignment, { label: string; path: string; actions: readonly AccessAction[] }>;

export const ACCESS_LINES = { loans: "Loans", real_estate: "Real Estate" } as const;
export const ACTION_LABELS: Record<AccessAction, string> = {
  view: "View",
  edit: "Edit",
  review: "Recommend attendance decisions",
  prepare: "Prepare payout requests",
  follow_up: "Record follow-ups and recommendations",
};

export function assignedLines(access: SubAdminAccess | null | undefined, assignment: Assignment, action: AccessAction) {
  if (access?.status !== "active") return [];
  return access.grants.filter((grant) => grant.assignment === assignment && grant.actions.includes(action))
    .map((grant) => grant.business_line);
}

export function canActOnLine(lines: readonly AccessLine[], line: string) {
  return line === "both" ? lines.length === 2 : lines.some((allowedLine) => allowedLine === line);
}

export function searchRelationshipAgents(line: AccessLine, query: string) {
  return apiRequest<RelationshipAgent[]>(`/api/v1/relationships/options?${new URLSearchParams({ line, query })}`);
}

export function listRelationshipAgents() {
  return apiRequest<RelationshipAgent[]>("/api/v1/relationships");
}

export function listRelationshipActivity(agentId: string) {
  return apiRequest<RelationshipActivity[]>(`/api/v1/relationships/${agentId}/activity`);
}

export function addRelationshipActivity(agentId: string, body: Schemas["RelationshipActivityInput"]) {
  return apiRequest<RelationshipActivity>(`/api/v1/relationships/${agentId}/activity`, { method: "POST", body });
}

/** The assigned Agent's leads, read-only and without client contact details. */
export function listRelationshipLeads(agentId: string) {
  return apiRequest<RelationshipLead[]>(`/api/v1/relationships/${encodeURIComponent(agentId)}/leads`);
}

/** Names of Agents already listed in a Relationship Manager grant (Main Admin). */
export function listSelectedRelationshipAgents(ids: readonly string[]) {
  const query = new URLSearchParams();
  ids.forEach((id) => query.append("ids", id));
  return apiRequest<RelationshipAgent[]>(`/api/v1/relationships/options/selected?${query}`);
}

/** Sub Admins whose Relationship Manager grant covers this Agent (Main Admin). */
export function listRelationshipManagerOptions(agentProfileId: string) {
  return apiRequest<RelationshipManagerOption[]>(
    `/api/v1/admin/agents/${encodeURIComponent(agentProfileId)}/relationship-manager/options`,
  );
}

/** Make one Sub Admin the Agent's only Relationship Manager, or clear it (null). */
export function setAgentRelationshipManager(agentProfileId: string, subAdminProfileId: string | null) {
  return apiRequest<AgentRelationshipManager>(
    `/api/v1/admin/agents/${encodeURIComponent(agentProfileId)}/relationship-manager`,
    { method: "PUT", body: { sub_admin_profile_id: subAdminProfileId } },
  );
}
