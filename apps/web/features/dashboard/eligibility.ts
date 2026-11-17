// Lead and referral eligibility (CS-024), shared by the Agent Leads page and
// the Client Referrals page. The API owns the reason codes and their labels
// (`apps/api/app/services/eligibility.py`); this module only names the three
// outcomes, maps them to a badge tone and applies the list filters. Pure, so
// the rules are unit-tested once.

import type { components } from "@contracts/generated/schema";

import type { FilterOption } from "./filter-options";
import type { StatusTone } from "./status-badge";

type Schemas = components["schemas"];
export type EligibilitySummary = Schemas["EligibilitySummary"];
export type IntakeAttempt = Schemas["IntakeAttemptRead"];
export type IntakeAttemptList = Schemas["IntakeAttemptListResponse"];

/** Accepted rows are eligible or not; only a rejected attempt is a duplicate. */
export type RowEligibility = "eligible" | "not_eligible";
export type EligibilityOutcome = RowEligibility | "duplicate";

export const ELIGIBILITY_LABEL: Record<EligibilityOutcome, string> = {
  eligible: "Eligible",
  not_eligible: "Not eligible",
  duplicate: "Duplicate",
};

export const ELIGIBILITY_TONE: Record<EligibilityOutcome, StatusTone> = {
  eligible: "success",
  not_eligible: "danger",
  duplicate: "warning",
};

/** The Eligibility filter on accepted rows (leads or referrals). */
export const ROW_ELIGIBILITY_OPTIONS: readonly FilterOption[] = [
  { value: "eligible", label: ELIGIBILITY_LABEL.eligible },
  { value: "not_eligible", label: ELIGIBILITY_LABEL.not_eligible },
];

/** The Eligibility filter on the "Not accepted" list. */
export const ATTEMPT_ELIGIBILITY_OPTIONS: readonly FilterOption[] = [
  { value: "duplicate", label: ELIGIBILITY_LABEL.duplicate },
  { value: "not_eligible", label: ELIGIBILITY_LABEL.not_eligible },
];

/**
 * A row's eligibility, or null when the row predates the field (an older API
 * or a cached response), so no badge is invented for it.
 */
export function rowEligibility(row: { eligibility?: string | null }): RowEligibility | null {
  return row.eligibility === "eligible" || row.eligibility === "not_eligible" ? row.eligibility : null;
}

/** "all" keeps every row; otherwise the row's eligibility must match. */
export function matchesEligibility(row: { eligibility?: string | null }, filter: string): boolean {
  return filter === "all" || rowEligibility(row) === filter;
}

/** "all" keeps every attempt; otherwise its outcome must match. */
export function matchesAttemptOutcome(attempt: Pick<IntakeAttempt, "outcome">, filter: string): boolean {
  return filter === "all" || attempt.outcome === filter;
}

/**
 * The summary split for the card hints: `not_eligible` counts accepted rows a
 * rule excludes plus attempts a rule turned away, and every attempt that is
 * not a duplicate is one of the latter.
 */
export function eligibilityBreakdown(summary: EligibilitySummary): {
  notEligibleAccepted: number;
  notEligibleAttempts: number;
} {
  const notEligibleAttempts = Math.max(0, summary.not_accepted - summary.duplicate);
  return {
    notEligibleAttempts,
    notEligibleAccepted: Math.max(0, summary.not_eligible - notEligibleAttempts),
  };
}

/** "2 leads · 1 not accepted" style hint, skipping zero parts. */
export function notEligibleHint(summary: EligibilitySummary, noun: { one: string; many: string }): string {
  const { notEligibleAccepted, notEligibleAttempts } = eligibilityBreakdown(summary);
  const parts: string[] = [];
  if (notEligibleAccepted > 0) {
    parts.push(`${notEligibleAccepted} ${notEligibleAccepted === 1 ? noun.one : noun.many}`);
  }
  if (notEligibleAttempts > 0) parts.push(`${notEligibleAttempts} not accepted`);
  return parts.length > 0 ? parts.join(" · ") : "None";
}
