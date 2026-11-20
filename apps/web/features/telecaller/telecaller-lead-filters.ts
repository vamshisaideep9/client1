// Pure search/filter/sort helpers for the telecaller leads table, kept
// framework-free so they're unit-testable without mounting the view. Mirrors
// the shape of features/admin/operational-records-filter.ts.

import { compareLeadsByDefaultOrder, leadStatusRank } from "@/features/dashboard/list-order";
import { isInDateRange } from "@/lib/date-range";
import type { TelecallerLead } from "@/lib/telecaller-api";

import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  leadSignalFiltersActive,
  matchesLeadSignals,
  matchesResubmission,
  type ResubmissionFilter,
  type LeadSignalFilters,
  type LeadSignalValues,
} from "./lead-signal-filters";
import { DISPOSITION_LABEL } from "./telecaller-lead-status";

export type TelecallerLeadFilters = LeadSignalFilters & {
  search: string;
  status: string; // "all" | TelecallerLead["status"]
  followUpFrom: string; // "YYYY-MM-DD"
  followUpTo: string; // "YYYY-MM-DD"
  /** "Follow-ups due": open leads whose next follow-up is now or overdue (`?followUp=due`). */
  followUpDue: boolean;
  resubmission: ResubmissionFilter;
};

export const DEFAULT_TELECALLER_LEAD_FILTERS: TelecallerLeadFilters = {
  ...DEFAULT_LEAD_SIGNAL_FILTERS,
  search: "",
  status: "all",
  followUpFrom: "",
  followUpTo: "",
  followUpDue: false,
  resubmission: "all",
};

/** The URL value the home "View all follow-ups" link uses. */
export const FOLLOW_UP_DUE_PARAM = "due";

// Same rule as the home panel (services/telecaller.get_home_summary):
// converted, closed and released leads are never "due".
const FINISHED_LEAD_STATUSES = new Set(["converted", "closed", "released"]);

export function isFollowUpDue(lead: Pick<TelecallerLead, "status" | "next_follow_up_at">, now: Date): boolean {
  if (FINISHED_LEAD_STATUSES.has(lead.status) || !lead.next_follow_up_at) return false;
  const due = new Date(lead.next_follow_up_at).getTime();
  return !Number.isNaN(due) && due <= now.getTime();
}

export function telecallerLeadFiltersActive(filters: TelecallerLeadFilters): boolean {
  return (
    filters.search !== "" ||
    filters.status !== "all" ||
    filters.followUpFrom !== "" ||
    filters.followUpTo !== "" ||
    filters.followUpDue ||
    filters.resubmission !== "all" ||
    leadSignalFiltersActive(filters)
  );
}

/** The lead facts the shared lead-signal filters read. */
export function telecallerSignalValues(lead: TelecallerLead): LeadSignalValues {
  return {
    loanStatuses: lead.loan_statuses,
    lastDisposition: lead.last_disposition,
    lastInterestLevel: lead.last_interest_level,
    referrer: lead.referrer,
    facets: lead.facets,
    transactions: lead.transactions,
  };
}

/**
 * Pass filters already narrowed to the list's scope
 * (`scopedLeadSignalFilters`), so a hidden control never filters.
 */
export function filterTelecallerLeads(
  leads: TelecallerLead[],
  filters: TelecallerLeadFilters,
  now: Date = new Date(),
): TelecallerLead[] {
  const query = filters.search.trim().toLocaleLowerCase();
  return leads.filter((lead) => {
    if (filters.status !== "all" && lead.status !== filters.status) return false;
    if (!matchesResubmission(lead.resubmit_count, filters.resubmission)) return false;
    if (filters.followUpDue && !isFollowUpDue(lead, now)) return false;
    if (!isInDateRange(lead.next_follow_up_at, filters.followUpFrom, filters.followUpTo)) return false;
    if (!matchesLeadSignals(telecallerSignalValues(lead), filters)) return false;
    if (!query) return true;
    return `${lead.name ?? ""} ${lead.mobile}`.toLocaleLowerCase().includes(query);
  });
}

/** "default" is the landing order; the others are the sortable columns. */
export type TelecallerLeadSortKey = "default" | "name" | "status" | "last_disposition" | "next_follow_up_at";
export type TelecallerLeadSort = { key: TelecallerLeadSortKey; dir: "asc" | "desc" };

// Default landing order: open work first (New > Assigned > Working >
// Converted > Closed > Released), then whichever lead is due soonest, with
// leads that have no follow-up last, so closed leads never fill page 1.
// Choosing a column sort replaces it.
export const DEFAULT_TELECALLER_LEAD_SORT: TelecallerLeadSort = {
  key: "default",
  dir: "asc",
};

function compareStrings(a: string, b: string): number {
  return a.localeCompare(b);
}

// Missing follow-ups always sink to the bottom, independent of sort direction
// — there's never a reason to lead the queue with leads that have no
// scheduled callback.
function compareFollowUp(
  a: string | null | undefined,
  b: string | null | undefined,
  dirMul: number,
): number {
  if (!a && !b) return 0;
  if (!a) return 1;
  if (!b) return -1;
  return dirMul * (new Date(a).getTime() - new Date(b).getTime());
}

export function sortTelecallerLeads(
  leads: TelecallerLead[],
  sort: TelecallerLeadSort,
): TelecallerLead[] {
  const dirMul = sort.dir === "asc" ? 1 : -1;
  return [...leads].sort((a, b) => {
    switch (sort.key) {
      case "name":
        return dirMul * compareStrings(a.name ?? "", b.name ?? "");
      case "default":
        return compareLeadsByDefaultOrder(
          { status: a.status, followUpAt: a.next_follow_up_at },
          { status: b.status, followUpAt: b.next_follow_up_at },
        );
      case "status":
        return (
          dirMul * (leadStatusRank(a.status) - leadStatusRank(b.status)) ||
          compareFollowUp(a.next_follow_up_at, b.next_follow_up_at, 1)
        );
      case "last_disposition":
        return (
          dirMul *
          compareStrings(
            a.last_disposition ? DISPOSITION_LABEL[a.last_disposition] ?? a.last_disposition : "",
            b.last_disposition ? DISPOSITION_LABEL[b.last_disposition] ?? b.last_disposition : "",
          )
        );
      case "next_follow_up_at":
        return compareFollowUp(a.next_follow_up_at, b.next_follow_up_at, dirMul);
      default:
        return 0;
    }
  });
}
