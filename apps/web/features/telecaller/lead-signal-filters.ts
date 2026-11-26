// Lead filters shared by the Telecaller leads list, the Employee tasks list and
// a manager's team work lists: call status, interest, lead source, referred by,
// and (CS-023) product, bank and loan status on the loans line, property
// category, subtype and deal status on the real estate line, and the
// Telecaller's loan transactions. Pure and framework-free so every list (and
// its unit tests) applies exactly the same rules.

import type { components } from "@contracts/generated/schema";

import {
  compactChips,
  selectFilterChip,
  textFilterChip,
  type ActiveFilterChip,
  type FilterOption,
} from "@/features/dashboard/filter-options";
import {
  DEAL_STATUS_LABEL,
  PROPERTY_CATEGORY_LABEL,
  PROPERTY_SUBTYPE_LABEL,
  TRANSACTION_PRESENCE_LABEL,
  amountRangeLabel,
  facetLoanOptions,
  hiddenTransactionParts,
  mergeOptions,
  normalizeName,
  parseRupees,
  transactionBankOptions,
  type LeadFacets,
  type LeadTransactionSummary,
} from "@/features/dashboard/product-filter-options";

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
  /** One entry per loan application and property deal (CS-023). */
  facets?: LeadFacets | null;
  /** Loan transactions; null for callers without that reach. */
  transactions?: LeadTransactionSummary | null;
  /** The lead's stored product (any category) and its label, when recorded. */
  productId?: string | null;
  productLabel?: string | null;
};

export type ReferrerSource = "direct" | "agent" | "client";

export type ResubmissionFilter = "all" | "yes" | "no";
export const RESUBMISSION_OPTIONS = [
  { value: "yes", label: "Resubmitted" },
  { value: "no", label: "Not resubmitted" },
];
export function matchesResubmission(count: number | undefined, filter: ResubmissionFilter): boolean {
  return filter === "all" || (filter === "yes" ? (count ?? 0) > 0 : (count ?? 0) === 0);
}

export type LeadSignalFilters = {
  loanStatus: "all" | LoanStatus;
  /** "not_called" keeps leads with no logged call. */
  callStatus: "all" | "not_called" | CallStatus;
  interest: "all" | InterestLevel;
  source: "all" | ReferrerSource;
  referredBy: string;
  /** Loans line: financial product (loan type id) and bank id. */
  loanTypeId: string;
  bankId: string;
  /** Real estate line. */
  dealStatus: string;
  propertyCategory: string;
  propertySubtype: string;
  /** Telecaller transactions: "has" / "none", or "all". */
  txnPresence: "all" | "has" | "none";
  /** "YYYY-MM-DD", inclusive. */
  txnFrom: string;
  txnTo: string;
  /** A `normalizeName` key, or "all". */
  txnBank: string;
  /** Rupees, as typed. */
  txnAmountMin: string;
  txnAmountMax: string;
};

export const DEFAULT_LEAD_SIGNAL_FILTERS: LeadSignalFilters = {
  loanStatus: "all",
  callStatus: "all",
  interest: "all",
  source: "all",
  referredBy: "",
  loanTypeId: "all",
  bankId: "all",
  dealStatus: "all",
  propertyCategory: "all",
  propertySubtype: "all",
  txnPresence: "all",
  txnFrom: "",
  txnTo: "",
  txnBank: "all",
  txnAmountMin: "",
  txnAmountMax: "",
};

/**
 * Which filter families a list offers: loan filters on the loans line,
 * property filters on the real estate line, transaction filters for
 * Telecaller leads on the loans line, minus the transaction parts the Admin
 * hides ("bank_names", "amount", "dates").
 */
export type LeadSignalScope = {
  loans: boolean;
  property: boolean;
  transactions: boolean;
  hiddenTransactionParts?: ReadonlySet<string>;
};

export function lineScope(line: string, transactions = false, hidden?: ReadonlySet<string>): LeadSignalScope {
  return {
    loans: line === "loans",
    property: line === "real_estate",
    transactions: transactions && line === "loans",
    hiddenTransactionParts: hidden,
  };
}

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

/**
 * The filters with every family the scope does not offer reset, so a control
 * that is hidden (another line, an Admin-hidden field) never keeps narrowing
 * the list or counting as active.
 */
export function scopedLeadSignalFilters(filters: LeadSignalFilters, scope: LeadSignalScope): LeadSignalFilters {
  const next = { ...filters };
  const d = DEFAULT_LEAD_SIGNAL_FILTERS;
  if (!scope.loans) {
    next.loanStatus = d.loanStatus;
    next.loanTypeId = d.loanTypeId;
    next.bankId = d.bankId;
  }
  if (!scope.property) {
    next.dealStatus = d.dealStatus;
    next.propertyCategory = d.propertyCategory;
    next.propertySubtype = d.propertySubtype;
  }
  const hidden = scope.hiddenTransactionParts ?? new Set<string>();
  if (!scope.transactions) {
    next.txnPresence = d.txnPresence;
  }
  if (!scope.transactions || hidden.has("dates")) {
    next.txnFrom = d.txnFrom;
    next.txnTo = d.txnTo;
  }
  if (!scope.transactions || hidden.has("bank_names")) next.txnBank = d.txnBank;
  if (!scope.transactions || hidden.has("amount")) {
    next.txnAmountMin = d.txnAmountMin;
    next.txnAmountMax = d.txnAmountMax;
  }
  return next;
}

/** True when any filter differs from its default (scope-blind: raw state). */
export function leadSignalFiltersActive(filters: LeadSignalFilters): boolean {
  return (Object.keys(DEFAULT_LEAD_SIGNAL_FILTERS) as (keyof LeadSignalFilters)[]).some((key) =>
    key === "referredBy"
      ? filters.referredBy.trim() !== ""
      : filters[key] !== DEFAULT_LEAD_SIGNAL_FILTERS[key],
  );
}

function loanFiltered(filters: LeadSignalFilters): boolean {
  return filters.loanStatus !== "all" || filters.loanTypeId !== "all" || filters.bankId !== "all";
}

function dealFiltered(filters: LeadSignalFilters): boolean {
  return filters.dealStatus !== "all" || filters.propertyCategory !== "all" || filters.propertySubtype !== "all";
}

function txnItemFiltered(filters: LeadSignalFilters): boolean {
  return (
    filters.txnFrom !== "" ||
    filters.txnTo !== "" ||
    filters.txnBank !== "all" ||
    parseRupees(filters.txnAmountMin) !== null ||
    parseRupees(filters.txnAmountMax) !== null
  );
}

/**
 * The product filter matches the lead's stored product first, then a loan
 * application of that product. Bank and loan status still need one
 * application matching every application filter at once.
 */
function matchesLoans(values: LeadSignalValues, filters: LeadSignalFilters): boolean {
  const storedProduct = filters.loanTypeId !== "all" && values.productId === filters.loanTypeId;
  const applicationFiltered = filters.loanStatus !== "all" || filters.bankId !== "all";
  if (storedProduct && !applicationFiltered) return true;
  const loans = values.facets?.loans;
  if (!loans) {
    // Rows without facets (an older API) can still answer the status filter.
    if (filters.bankId !== "all") return false;
    if (filters.loanTypeId !== "all" && !storedProduct) return false;
    return filters.loanStatus === "all" || (values.loanStatuses ?? []).includes(filters.loanStatus);
  }
  return loans.some(
    (loan) =>
      (filters.loanStatus === "all" || loan.status === filters.loanStatus) &&
      (filters.loanTypeId === "all" || storedProduct || loan.loan_type_id === filters.loanTypeId) &&
      (filters.bankId === "all" || loan.bank_id === filters.bankId),
  );
}

/** One property deal must match every property filter at once. */
function matchesDeals(values: LeadSignalValues, filters: LeadSignalFilters): boolean {
  return (values.facets?.deals ?? []).some(
    (deal) =>
      (filters.dealStatus === "all" || deal.status === filters.dealStatus) &&
      (filters.propertyCategory === "all" || deal.property_category === filters.propertyCategory) &&
      (filters.propertySubtype === "all" || deal.property_subtype === filters.propertySubtype),
  );
}

/**
 * Presence counts every recorded transaction; the date, bank and amount
 * filters need one transaction matching all of them.
 */
function matchesTransactions(summary: LeadTransactionSummary | null | undefined, filters: LeadSignalFilters): boolean {
  const count = summary?.count ?? 0;
  if (filters.txnPresence === "has" && count === 0) return false;
  if (filters.txnPresence === "none" && count > 0) return false;
  if (!txnItemFiltered(filters)) return true;
  const min = parseRupees(filters.txnAmountMin);
  const max = parseRupees(filters.txnAmountMax);
  return (summary?.items ?? []).some((item) => {
    if (filters.txnFrom || filters.txnTo) {
      if (!item.txn_date) return false;
      if (filters.txnFrom && item.txn_date < filters.txnFrom) return false;
      if (filters.txnTo && item.txn_date > filters.txnTo) return false;
    }
    if (filters.txnBank !== "all" && normalizeName(item.bank_name) !== filters.txnBank) return false;
    if (min !== null || max !== null) {
      if (item.amount === null || item.amount === undefined) return false;
      if (min !== null && item.amount < min) return false;
      if (max !== null && item.amount > max) return false;
    }
    return true;
  });
}

export function matchesLeadSignals(values: LeadSignalValues, filters: LeadSignalFilters): boolean {
  if (loanFiltered(filters) && !matchesLoans(values, filters)) return false;
  if (dealFiltered(filters) && !matchesDeals(values, filters)) return false;
  if (
    (filters.txnPresence !== "all" || txnItemFiltered(filters)) &&
    !matchesTransactions(values.transactions, filters)
  ) {
    return false;
  }
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

/** Product, bank and transaction-bank choices for the current rows. */
export type LeadSignalOptions = {
  loanTypes: readonly FilterOption[];
  banks: readonly FilterOption[];
  transactionBanks: readonly FilterOption[];
};

export const NO_LEAD_SIGNAL_OPTIONS: LeadSignalOptions = { loanTypes: [], banks: [], transactionBanks: [] };

/** The stored products on the rows (any category), as filter options. */
export function storedProductOptions(rows: readonly LeadSignalValues[]): FilterOption[] {
  return mergeOptions(
    rows.flatMap((row) =>
      row.productId ? [{ value: row.productId, label: row.productLabel ?? "Unnamed product" }] : [],
    ),
  );
}

/**
 * Catalogue choices plus every product, bank and transaction bank on the rows.
 * Product choices cover every category when the catalogue supplies `products`.
 */
export function leadSignalOptions(
  catalogue: {
    loanTypes: readonly FilterOption[];
    products?: readonly FilterOption[];
    banks: readonly FilterOption[];
    bankNames: readonly string[];
  },
  rows: readonly LeadSignalValues[],
): LeadSignalOptions {
  const fromRows = facetLoanOptions(rows.map((row) => row.facets));
  return {
    loanTypes: mergeOptions(
      catalogue.products ?? catalogue.loanTypes,
      fromRows.loanTypes,
      storedProductOptions(rows),
    ),
    banks: mergeOptions(catalogue.banks, fromRows.banks),
    transactionBanks: transactionBankOptions(
      catalogue.bankNames,
      rows.map((row) => row.transactions),
    ),
  };
}

/** The transaction parts the Admin hides, read off the rows' summaries. */
export function rowsHiddenTransactionParts(rows: readonly LeadSignalValues[]): Set<string> {
  return hiddenTransactionParts(rows.map((row) => row.transactions));
}

/** How many lead-signal filters inside "More filters" narrow the list (in scope only). */
export function leadSignalActiveCount(filters: LeadSignalFilters, scope: LeadSignalScope): number {
  const f = scopedLeadSignalFilters(filters, scope);
  return [
    f.loanStatus !== "all",
    f.loanTypeId !== "all",
    f.bankId !== "all",
    f.dealStatus !== "all",
    f.propertyCategory !== "all",
    f.propertySubtype !== "all",
    f.callStatus !== "all",
    f.interest !== "all",
    f.source !== "all",
    f.referredBy.trim() !== "",
    f.txnPresence !== "all",
    f.txnFrom !== "" || f.txnTo !== "",
    f.txnBank !== "all",
    parseRupees(f.txnAmountMin) !== null || parseRupees(f.txnAmountMax) !== null,
  ].filter(Boolean).length;
}

function dateRangeChipText(from: string, to: string): string | null {
  if (from && to) return `${from} to ${to}`;
  if (from) return `from ${from}`;
  if (to) return `up to ${to}`;
  return null;
}

/** Removable chips for the active lead-signal filters (in scope only). */
export function leadSignalChips(
  filters: LeadSignalFilters,
  onChange: (patch: Partial<LeadSignalFilters>) => void,
  scope: LeadSignalScope,
  options: LeadSignalOptions = NO_LEAD_SIGNAL_OPTIONS,
): ActiveFilterChip[] {
  const f = scopedLeadSignalFilters(filters, scope);
  const txnDates = dateRangeChipText(f.txnFrom, f.txnTo);
  const txnAmount = amountRangeLabel(f.txnAmountMin, f.txnAmountMax);
  return compactChips([
    selectFilterChip("loanTypeId", "Product", f.loanTypeId, options.loanTypes, () => onChange({ loanTypeId: "all" })),
    selectFilterChip("bankId", "Bank", f.bankId, options.banks, () => onChange({ bankId: "all" })),
    selectFilterChip("loanStatus", "Loan status", f.loanStatus, LOAN_STATUS_LABEL, () =>
      onChange({ loanStatus: "all" }),
    ),
    selectFilterChip("propertyCategory", "Property category", f.propertyCategory, PROPERTY_CATEGORY_LABEL, () =>
      onChange({ propertyCategory: "all" }),
    ),
    selectFilterChip("propertySubtype", "Property type", f.propertySubtype, PROPERTY_SUBTYPE_LABEL, () =>
      onChange({ propertySubtype: "all" }),
    ),
    selectFilterChip("dealStatus", "Deal status", f.dealStatus, DEAL_STATUS_LABEL, () =>
      onChange({ dealStatus: "all" }),
    ),
    selectFilterChip("callStatus", "Call status", f.callStatus, CALL_STATUS_FILTER_LABEL, () =>
      onChange({ callStatus: "all" }),
    ),
    selectFilterChip("interest", "Lead interest", f.interest, INTEREST_LABEL, () => onChange({ interest: "all" })),
    selectFilterChip("source", "Lead source", f.source, REFERRER_SOURCE_LABEL, () => onChange({ source: "all" })),
    textFilterChip("referredBy", "Referred by ID", f.referredBy, () => onChange({ referredBy: "" })),
    selectFilterChip("txnPresence", "Transactions", f.txnPresence, TRANSACTION_PRESENCE_LABEL, () =>
      onChange({ txnPresence: "all" }),
    ),
    txnDates ? { id: "txnDates", label: `Transaction date: ${txnDates}`, onRemove: () => onChange({ txnFrom: "", txnTo: "" }) } : null,
    selectFilterChip("txnBank", "Transaction bank", f.txnBank, options.transactionBanks, () =>
      onChange({ txnBank: "all" }),
    ),
    txnAmount
      ? {
          id: "txnAmount",
          label: `Transaction amount: ${txnAmount}`,
          onRemove: () => onChange({ txnAmountMin: "", txnAmountMax: "" }),
        }
      : null,
  ]);
}

/** Every "More filters" lead-signal filter back to its default (the list's own filters stay). */
export function clearedLeadSignalFilters<T extends LeadSignalFilters>(filters: T): T {
  return { ...filters, ...DEFAULT_LEAD_SIGNAL_FILTERS };
}
