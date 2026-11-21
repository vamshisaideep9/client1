// Filters for a manager's team work lists (CS-020). Pure and framework-free so
// the team-wide list, the member list and their unit tests share one rule set.
// The lead signal rules (loan status, last call, interest, referral) are the
// Telecaller / Employee lists' own `matchesLeadSignals`.

import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  leadSignalFiltersActive,
  matchesLeadSignals,
  type LeadSignalFilters,
  type LeadSignalValues,
} from "@/features/telecaller/lead-signal-filters";
import type { TeamLeadRow, TeamTaskRow } from "@/lib/staff-teams-api";

export type TeamWorkFilters = LeadSignalFilters & {
  /** A member's staff profile id, or "all". */
  assignee: string;
  /** Lead or task status, or "all". */
  status: string;
  /** Task type, or "all" (Employee teams). */
  taskType: string;
  /** Client name or mobile. */
  search: string;
  /** Leads past their follow-up, tasks past their due time. */
  overdueOnly: boolean;
};

export const DEFAULT_TEAM_WORK_FILTERS: TeamWorkFilters = {
  ...DEFAULT_LEAD_SIGNAL_FILTERS,
  assignee: "all",
  status: "all",
  taskType: "all",
  search: "",
  overdueOnly: false,
};

const OPEN_LEAD = new Set(["assigned", "working"]);
const OPEN_TASK = new Set(["assigned", "in_progress", "blocked"]);

export function teamWorkFiltersActive(filters: TeamWorkFilters): boolean {
  return (
    leadSignalFiltersActive(filters) ||
    filters.assignee !== "all" ||
    filters.status !== "all" ||
    filters.taskType !== "all" ||
    filters.search.trim() !== "" ||
    filters.overdueOnly
  );
}

function matchesSearch(query: string, ...values: (string | null | undefined)[]): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  const digits = needle.replace(/\D/g, "");
  return values.some((value) => {
    if (!value) return false;
    if (value.toLocaleLowerCase().includes(needle)) return true;
    return digits.length >= 3 && value.replace(/\D/g, "").includes(digits);
  });
}

/** The lead facts the shared lead-signal filters read. */
export function teamSignalValues(row: TeamLeadRow | TeamTaskRow): LeadSignalValues {
  return {
    loanStatuses: row.signals?.loan_statuses,
    lastDisposition: row.signals?.last_disposition,
    lastInterestLevel: row.signals?.last_interest_level,
    referrer: row.signals?.referrer,
    facets: row.signals?.facets,
    transactions: row.signals?.transactions,
  };
}

export function isOverdueLead(row: TeamLeadRow, now: Date): boolean {
  const followUp = row.last_call?.follow_up_at;
  return OPEN_LEAD.has(row.status) && !!followUp && new Date(followUp).getTime() < now.getTime();
}

export function isOverdueTask(row: TeamTaskRow, now: Date): boolean {
  return OPEN_TASK.has(row.status) && !!row.due_at && new Date(row.due_at).getTime() < now.getTime();
}

export function filterTeamLeads(
  rows: readonly TeamLeadRow[],
  filters: TeamWorkFilters,
  now: Date,
): TeamLeadRow[] {
  return rows.filter(
    (row) =>
      (filters.assignee === "all" || row.assigned_to?.staff_profile_uuid === filters.assignee) &&
      (filters.status === "all" || row.status === filters.status) &&
      matchesSearch(filters.search, row.name, row.mobile) &&
      (!filters.overdueOnly || isOverdueLead(row, now)) &&
      matchesLeadSignals(teamSignalValues(row), filters),
  );
}

export function filterTeamTasks(
  rows: readonly TeamTaskRow[],
  filters: TeamWorkFilters,
  now: Date,
): TeamTaskRow[] {
  return rows.filter(
    (row) =>
      (filters.assignee === "all" || row.assigned_to?.staff_profile_uuid === filters.assignee) &&
      (filters.status === "all" || row.status === filters.status) &&
      (filters.taskType === "all" || row.task_type === filters.taskType) &&
      matchesSearch(filters.search, row.lead_name, row.lead_mobile) &&
      (!filters.overdueOnly || isOverdueTask(row, now)) &&
      matchesLeadSignals(teamSignalValues(row), filters),
  );
}
