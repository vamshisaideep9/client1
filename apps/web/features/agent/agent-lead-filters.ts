// Filters for the Agent's own Leads list (CS-024): search, status,
// eligibility, and — from the Batch C facts on each row — product, bank and
// loan status (loans line) or property category, type and deal status (real
// estate line). Agents get no call outcomes, referral codes or transactions,
// so those lead-signal filters never apply here. Pure, for unit tests.

import { matchesEligibility } from "@/features/dashboard/eligibility";
import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  lineScope,
  matchesLeadSignals,
  matchesResubmission,
  type ResubmissionFilter,
  scopedLeadSignalFilters,
  type LeadSignalFilters,
  type LeadSignalScope,
} from "@/features/telecaller/lead-signal-filters";
import type { AgentLead } from "@/lib/agent-api";

export const AGENT_LEAD_STATUS_LABEL: Record<string, string> = {
  new: "New",
  assigned: "Assigned",
  working: "Working",
  converted: "Converted",
  closed: "Closed",
  released: "Released",
  expired: "Expired",
};

export type AgentLeadFilters = LeadSignalFilters & {
  search: string;
  status: string;
  eligibility: string;
  resubmission: ResubmissionFilter;
};

export const DEFAULT_AGENT_LEAD_FILTERS: AgentLeadFilters = {
  ...DEFAULT_LEAD_SIGNAL_FILTERS,
  search: "",
  status: "all",
  eligibility: "all",
  resubmission: "all",
};

/** Agents are line-scoped, so every row shares one line; none without rows. */
export function agentLeadScope(rows: readonly Pick<AgentLead, "business_line">[]): LeadSignalScope {
  const line = rows.find((row) => row.business_line)?.business_line ?? "";
  return lineScope(line);
}

function matchesSearch(lead: Pick<AgentLead, "name" | "mobile">, search: string): boolean {
  const query = search.trim().toLocaleLowerCase();
  if (!query) return true;
  if ((lead.name ?? "").toLocaleLowerCase().includes(query)) return true;
  const digits = query.replace(/\D/g, "");
  return digits.length > 0 && lead.mobile.replace(/\D/g, "").includes(digits);
}

export function filterAgentLeads<T extends AgentLead>(
  rows: readonly T[],
  filters: AgentLeadFilters,
  scope: LeadSignalScope,
): T[] {
  const signals = scopedLeadSignalFilters(filters, scope);
  return rows.filter(
    (lead) =>
      (filters.status === "all" || lead.status === filters.status) &&
      matchesEligibility(lead, filters.eligibility) &&
      matchesResubmission(lead.resubmit_count, filters.resubmission) &&
      matchesSearch(lead, filters.search) &&
      matchesLeadSignals({ facets: lead.facets }, signals),
  );
}
