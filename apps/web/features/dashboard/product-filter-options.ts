// Option lists and labels for the product, property and money filters (CS-023)
// shared by every dashboard: lead lists, My analytics, team analytics, Admin
// reports and Agent earnings. Pure, so the merge rules are unit-tested once.
//
// One rule everywhere: a filter offers the active catalogue (financial
// products and banks from the catalogue endpoints, fixed property and status
// vocabularies) plus anything already on a loaded row, so an option is never
// missing for data on screen (an inactive product, a bank name typed on a
// transaction) and never invented.

import type { components } from "@contracts/generated/schema";

import { PROPERTY_SUBTYPE_OPTIONS } from "@/lib/property-taxonomy";

import type { FilterOption } from "./filter-options";

type Schemas = components["schemas"];
export type LeadFacets = Schemas["LeadFacets"];
export type LeadTransactionSummary = Schemas["LeadTransactionSummary"];

export const DEAL_STATUS_LABEL: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  site_visit_done: "Site visit done",
  negotiation: "Negotiation",
  booked: "Booked",
  agreement_signed: "Agreement signed",
  closed: "Closed",
  rejected: "Rejected",
  on_hold: "On hold",
};

export const PROPERTY_CATEGORY_LABEL: Record<string, string> = {
  houses: "Houses",
  apartments: "Apartments",
  villas: "Villas",
  plots: "Plots",
  commercial: "Commercial",
};

/** Subtype labels in the catalogue's own order (Residential, Plots, Commercial). */
export const PROPERTY_SUBTYPE_LABEL: Record<string, string> = Object.fromEntries(
  PROPERTY_SUBTYPE_OPTIONS.map((option) => [option.value, option.label]),
);

export const COMMISSION_STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  paid: "Paid",
  cancelled: "Cancelled",
};

export const TRANSACTION_PRESENCE_LABEL: Record<string, string> = {
  has: "Has a transaction",
  none: "No transaction",
};

/** Trimmed, single-spaced and case-folded, so "HDFC  bank " matches "HDFC Bank". */
export function normalizeName(value: string | null | undefined): string {
  return (value ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

/**
 * One option per value, the first label seen winning (pass the catalogue
 * first), sorted by label. Blank values or labels are dropped.
 */
export function mergeOptions(...lists: readonly (readonly FilterOption[])[]): FilterOption[] {
  const seen = new Map<string, string>();
  for (const list of lists) {
    for (const option of list) {
      if (option.value && option.label && !seen.has(option.value)) seen.set(option.value, option.label);
    }
  }
  return [...seen.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Products and banks named on the loaded rows' loan applications. */
export function facetLoanOptions(facets: readonly (LeadFacets | null | undefined)[]): {
  loanTypes: FilterOption[];
  banks: FilterOption[];
} {
  const loanTypes: FilterOption[] = [];
  const banks: FilterOption[] = [];
  for (const facet of facets) {
    for (const loan of facet?.loans ?? []) {
      loanTypes.push({ value: loan.loan_type_id, label: loan.loan_type_label ?? "Unnamed product" });
      if (loan.bank_id) banks.push({ value: loan.bank_id, label: loan.bank_name ?? "Unnamed bank" });
    }
  }
  return { loanTypes: mergeOptions(loanTypes), banks: mergeOptions(banks) };
}

/**
 * Transaction bank choices: the catalogue's bank names plus every name typed
 * on a loaded transaction, keyed by `normalizeName` so spelling variants of
 * one bank collapse into one option.
 */
export function transactionBankOptions(
  catalogueNames: readonly string[],
  summaries: readonly (LeadTransactionSummary | null | undefined)[],
): FilterOption[] {
  const typed: string[] = [];
  for (const summary of summaries) {
    for (const name of summary?.bank_names ?? []) typed.push(name);
  }
  return mergeOptions(
    [...catalogueNames, ...typed]
      .map((name) => ({ value: normalizeName(name), label: name.trim() }))
      .filter((option) => option.value),
  );
}

/** The transaction parts the Admin hides from Telecallers, read off the rows. */
export function hiddenTransactionParts(
  summaries: readonly (LeadTransactionSummary | null | undefined)[],
): Set<string> {
  // Field rules are per role, so every summary carries the same list.
  const first = summaries.find((summary) => summary);
  return new Set(first?.hidden_fields ?? []);
}

/** Rupees as typed ("1,50,000") to a number; null when blank or invalid. */
export function parseRupees(value: string): number | null {
  const trimmed = value.trim().replace(/,/g, "");
  if (!trimmed) return null;
  const rupees = Number(trimmed);
  return Number.isFinite(rupees) && rupees >= 0 ? rupees : null;
}

/** True when both ends are set and the minimum is above the maximum. */
export function amountRangeInverted(min: string, max: string): boolean {
  const low = parseRupees(min);
  const high = parseRupees(max);
  return low !== null && high !== null && low > high;
}

/** "₹10,000 – ₹50,000", "From ₹10,000", "Up to ₹50,000", or null. */
export function amountRangeLabel(min: string, max: string): string | null {
  const low = parseRupees(min);
  const high = parseRupees(max);
  const rupees = (value: number) => `₹${value.toLocaleString("en-IN")}`;
  if (low !== null && high !== null) return `${rupees(low)} – ${rupees(high)}`;
  if (low !== null) return `From ${rupees(low)}`;
  if (high !== null) return `Up to ${rupees(high)}`;
  return null;
}
