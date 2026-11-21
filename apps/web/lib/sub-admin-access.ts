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
