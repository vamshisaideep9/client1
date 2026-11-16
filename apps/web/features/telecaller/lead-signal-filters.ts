// Loan status / call status / interest / "referred by" filters shared by the
// Telecaller leads list and the Employee tasks list. Pure and framework-free so
// both lists (and their unit tests) apply exactly the same rules.

import type { components } from "@contracts/generated/schema";

import {
  compactChips,
  selectFilterChip,
  textFilterChip,
  type ActiveFilterChip,
} from "@/features/dashboard/filter-options";

import { DISPOSITION_LABEL } from "./telecaller-lead-status";

export type LeadReferrer = components["schemas"]["LeadReferrerRead"];
type LoanStatus = NonNullable<components["schemas"]["TelecallerLeadRead"]["loan_statuses"]>[number];
type CallStatus = NonNullable<components["schemas"]["TelecallerLeadRead"]["last_disposition"]>;
type InterestLevel = NonNullable<components["schemas"]["TelecallerLeadRead"]["last_interest_level"]>;

/** The lead facts a list row carries, whichever list it comes from. */
export type LeadSignalValues = {
  loanStatuses?: readonly string[] | null;
  lastDisposition?: string | null;
  lastInterestLevel?: string | null;
  referrer?: LeadReferrer | null;
};

export type ReferrerSource = "direct" | "agent" | "client";

export type LeadSignalFilters = {
  loanStatus: "all" | LoanStatus;
  /** "not_called" keeps leads with no logged call. */
  callStatus: "all" | "not_called" | CallStatus;
  interest: "all" | InterestLevel;
  source: "all" | ReferrerSource;
  referredBy: string;
};

export const DEFAULT_LEAD_SIGNAL_FILTERS: LeadSignalFilters = {
  loanStatus: "all",
  callStatus: "all",
  interest: "all",
  source: "all",
  referredBy: "",
};

export const LOAN_STATUS_LABEL: Record<LoanStatus, string> = {
  new: "New",
  assigned: "Assigned",
  contacted: "Contacted",
  docs_collected: "Docs collected",
  submitted_to_bank: "Submitted to bank",
  under_review: "Under review",
  sanctioned: "Approved",
  agreement_collected: "Agreement collected",
  agreement_submitted_to_bank: "Agreement submitted to bank",
  disbursed: "Disbursed",
  closed: "Closed",
  rejected: "Rejected",
  on_hold: "On hold",
};

export const LOAN_STATUS_OPTIONS = Object.keys(LOAN_STATUS_LABEL) as LoanStatus[];

export const INTEREST_LABEL: Record<InterestLevel, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };

export const REFERRER_SOURCE_LABEL: Record<ReferrerSource, string> = {
  direct: "Direct lead",
  agent: "Referred by agent",
  client: "Referred by client",
};

export function leadSignalFiltersActive(filters: LeadSignalFilters): boolean {
  return (
    filters.loanStatus !== "all" ||
    filters.callStatus !== "all" ||
    filters.interest !== "all" ||
    filters.source !== "all" ||
    filters.referredBy.trim() !== ""
  );
}

export function matchesLeadSignals(values: LeadSignalValues, filters: LeadSignalFilters): boolean {
  if (filters.loanStatus !== "all" && !(values.loanStatuses ?? []).includes(filters.loanStatus)) return false;
  if (filters.callStatus === "not_called") {
    if (values.lastDisposition) return false;
  } else if (filters.callStatus !== "all" && values.lastDisposition !== filters.callStatus) {
    return false;
  }
  if (filters.interest !== "all" && values.lastInterestLevel !== filters.interest) return false;
  const referrer = values.referrer ?? null;
  if (filters.source !== "all") {
    const kind: ReferrerSource = referrer ? referrer.kind : "direct";
    if (kind !== filters.source) return false;
  }
  const query = filters.referredBy.trim().toLocaleUpperCase();
  if (query && !(referrer?.reference_id.toLocaleUpperCase().includes(query) ?? false)) return false;
  return true;
}

/** "Agent · AG-1234" / "Client · 7K2M9QXA" (read after "Referred by"), or null for a direct lead. */
export function formatReferrer(referrer: LeadReferrer | null | undefined): string | null {
  if (!referrer) return null;
  return `${referrer.kind === "agent" ? "Agent" : "Client"} · ${referrer.reference_id}`;
}

/** Call-status filter choices: "Not called yet" plus every logged outcome. */
export const CALL_STATUS_FILTER_LABEL: Record<string, string> = {
  not_called: "Not called yet",
  ...DISPOSITION_LABEL,
};

/** How many lead-signal filters are narrowing the list (loan status only where it applies). */
export function leadSignalActiveCount(filters: LeadSignalFilters, showLoanStatus = true): number {
  return [
    showLoanStatus && filters.loanStatus !== "all",
    filters.callStatus !== "all",
    filters.interest !== "all",
    filters.source !== "all",
    filters.referredBy.trim() !== "",
  ].filter(Boolean).length;
}

/** Removable chips for the active lead-signal filters. */
export function leadSignalChips(
  filters: LeadSignalFilters,
  onChange: (patch: Partial<LeadSignalFilters>) => void,
  showLoanStatus = true,
): ActiveFilterChip[] {
  return compactChips([
    showLoanStatus
      ? selectFilterChip("loanStatus", "Loan status", filters.loanStatus, LOAN_STATUS_LABEL, () =>
          onChange({ loanStatus: "all" }),
        )
      : null,
    selectFilterChip("callStatus", "Call status", filters.callStatus, CALL_STATUS_FILTER_LABEL, () =>
      onChange({ callStatus: "all" }),
    ),
    selectFilterChip("interest", "Lead interest", filters.interest, INTEREST_LABEL, () =>
      onChange({ interest: "all" }),
    ),
    selectFilterChip("source", "Lead source", filters.source, REFERRER_SOURCE_LABEL, () =>
      onChange({ source: "all" }),
    ),
    textFilterChip("referredBy", "Referred by ID", filters.referredBy, () => onChange({ referredBy: "" })),
  ]);
}
