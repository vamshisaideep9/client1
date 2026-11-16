// Commission history filters for the Agent earnings page (CS-022). Pure so the
// matching rules are unit-tested; they mirror GET /agent/earnings's own filters
// (IST entry date, commission amount, case-insensitive search that never
// matches a client name the Admin has hidden).
import type { AgentEarnings, AgentEarningsRow } from "@/lib/agent-api";
import { formatPeriodLabel } from "@/lib/analytics-range";
import { toIsoDateIST } from "@/lib/reports";
import { ALL_FILTER, type FilterOption } from "@/features/dashboard/filter-options";

export type AgentEarningsFilterState = {
  search: string;
  status: string;
  dealType: string;
  leadStatus: string;
  product: string;
  bank: string;
  propertyCategory: string;
  /** Rupees, as typed. */
  amountMin: string;
  amountMax: string;
  /** IST calendar days ("YYYY-MM-DD"), on the date the commission was entered. */
  from: string;
  to: string;
};

export const EMPTY_EARNINGS_FILTERS: AgentEarningsFilterState = {
  search: "",
  status: ALL_FILTER,
  dealType: ALL_FILTER,
  leadStatus: ALL_FILTER,
  product: ALL_FILTER,
  bank: ALL_FILTER,
  propertyCategory: ALL_FILTER,
  amountMin: "",
  amountMax: "",
  from: "",
  to: "",
};

export const COMMISSION_STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  paid: "Paid",
  cancelled: "Cancelled",
};

export const DEAL_TYPE_LABEL: Record<string, string> = {
  loan_application: "Loan",
  property_deal: "Property deal",
};

export const LEAD_STATUS_LABEL: Record<string, string> = {
  new: "New",
  assigned: "Assigned",
  working: "Working",
  converted: "Converted",
  closed: "Closed",
  released: "Released",
  expired: "Expired",
};

/** "disbursed" -> "Disbursed", "site_visit_done" -> "Site visit done". */
export function humanizeStatus(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Rupees text to paise; null when blank or not a non-negative number. */
export function rupeesToPaise(value: string): number | null {
  const trimmed = value.trim().replace(/,/g, "");
  if (!trimmed) return null;
  const rupees = Number(trimmed);
  if (!Number.isFinite(rupees) || rupees < 0) return null;
  return Math.round(rupees * 100);
}

function uniqueOptions(entries: readonly (readonly [string | null, string | null])[]): FilterOption[] {
  const seen = new Map<string, string>();
  for (const [value, label] of entries) {
    if (value && label && !seen.has(value)) seen.set(value, label);
  }
  return [...seen.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Products, banks and property categories that appear in the Agent's history. */
export function earningsFilterOptions(rows: readonly AgentEarningsRow[]): {
  products: FilterOption[];
  banks: FilterOption[];
  categories: FilterOption[];
  leadStatuses: FilterOption[];
} {
  return {
    products: uniqueOptions(rows.map((row) => [row.product_uuid, row.product_label] as const)),
    banks: uniqueOptions(rows.map((row) => [row.bank_uuid, row.bank_name] as const)),
    categories: uniqueOptions(
      rows.map((row) => [row.property_category, humanizeStatus(row.property_category)] as const),
    ),
    leadStatuses: uniqueOptions(
      rows.map(
        (row) =>
          [row.lead_status, row.lead_status ? (LEAD_STATUS_LABEL[row.lead_status] ?? humanizeStatus(row.lead_status)) : null] as const,
      ),
    ),
  };
}

export function matchesEarningsFilters(
  row: AgentEarningsRow,
  filters: AgentEarningsFilterState,
): boolean {
  if (filters.status !== ALL_FILTER && row.status !== filters.status) return false;
  if (filters.dealType !== ALL_FILTER && row.deal_type !== filters.dealType) return false;
  if (filters.leadStatus !== ALL_FILTER && row.lead_status !== filters.leadStatus) return false;
  if (filters.product !== ALL_FILTER && row.product_uuid !== filters.product) return false;
  if (filters.bank !== ALL_FILTER && row.bank_uuid !== filters.bank) return false;
  if (filters.propertyCategory !== ALL_FILTER && row.property_category !== filters.propertyCategory) {
    return false;
  }
  const min = rupeesToPaise(filters.amountMin);
  const max = rupeesToPaise(filters.amountMax);
  if (min !== null && row.agreed_amount_paise < min) return false;
  if (max !== null && row.agreed_amount_paise > max) return false;
  if (filters.from || filters.to) {
    const day = toIsoDateIST(new Date(row.created_at));
    if (filters.from && day < filters.from) return false;
    if (filters.to && day > filters.to) return false;
  }
  const needle = filters.search.trim().toLocaleLowerCase();
  if (needle) {
    // client_name is null when the Admin hides it, so it is never searchable.
    const texts = [row.client_name, row.product_label, row.bank_name, row.property_title];
    const textHit = texts.some((text) => (text ?? "").toLocaleLowerCase().includes(needle));
    const idHit = [row.id, row.lead_uuid].some((id) => (id ?? "").startsWith(needle));
    if (!textHit && !idHit) return false;
  }
  return true;
}

export function filterEarningsRows(
  rows: readonly AgentEarningsRow[],
  filters: AgentEarningsFilterState,
): AgentEarningsRow[] {
  return rows.filter((row) => matchesEarningsFilters(row, filters));
}

/** How many filters behind "More filters" are set. */
export function moreEarningsFilterCount(filters: AgentEarningsFilterState): number {
  return [
    filters.leadStatus !== ALL_FILTER,
    filters.product !== ALL_FILTER,
    filters.bank !== ALL_FILTER,
    filters.propertyCategory !== ALL_FILTER,
    filters.amountMin.trim() !== "",
    filters.amountMax.trim() !== "",
  ].filter(Boolean).length;
}

/** "Oct 2026" for the previous calendar month the API reports, or "". */
export function lastMonthLabel(totals: AgentEarnings["totals"]): string {
  if (!totals.last_month_start || !totals.last_month_end) return "";
  return formatPeriodLabel({ dateFrom: totals.last_month_start, dateTo: totals.last_month_end });
}

/** The home metric card's label: "Commission paid · Oct 2026". */
export function commissionPaidLabel(totals: AgentEarnings["totals"]): string {
  const month = lastMonthLabel(totals);
  return month ? `Commission paid · ${month}` : "Commission paid";
}
