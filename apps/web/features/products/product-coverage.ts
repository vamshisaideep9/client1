// Pure rules for the Products area (2026-11-26): coverage flags, staffing
// filters, links and the period choices. Framework-free so they are
// unit-tested once and shared by the Admin and Team Manager views.

import type { StatusTone } from "@/features/dashboard/status-badge";
import type {
  ProductCoverage,
  ProductStaffPerson,
  ProductStaffingRow,
} from "@/lib/product-dashboards-api";

export const COVERAGE_LABEL: Record<ProductCoverage, string> = {
  full: "Fully staffed",
  no_telecaller: "No Telecaller",
  no_officer: "No Officer",
  none: "No specialists",
};

/** Status tones always ship with their label, never color alone. */
export const COVERAGE_TONE: Record<ProductCoverage, StatusTone> = {
  full: "success",
  no_telecaller: "warning",
  no_officer: "warning",
  none: "danger",
};

export const CATEGORY_OPTIONS = [
  { value: "loan", label: "Loan" },
  { value: "credit_card", label: "Credit card" },
  { value: "insurance", label: "Insurance" },
];

export const COVERAGE_OPTIONS = (Object.keys(COVERAGE_LABEL) as ProductCoverage[]).map((value) => ({
  value,
  label: COVERAGE_LABEL[value],
}));

export const ACTIVE_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

export type StaffingFilters = {
  search: string;
  category: string;
  coverage: string;
  active: string;
};

/** Inactive products stay listed for their history but start hidden. */
export const DEFAULT_STAFFING_FILTERS: StaffingFilters = {
  search: "",
  category: "all",
  coverage: "all",
  active: "active",
};

export function filterStaffingRows(
  rows: readonly ProductStaffingRow[],
  filters: StaffingFilters,
): ProductStaffingRow[] {
  const query = filters.search.trim().toLocaleLowerCase();
  return rows.filter(
    (row) =>
      (filters.category === "all" || row.category === filters.category) &&
      (filters.coverage === "all" || row.coverage === filters.coverage) &&
      (filters.active === "all" || (filters.active === "active") === (row.active ?? true)) &&
      (!query || row.label.toLocaleLowerCase().includes(query)),
  );
}

/** Products that still need a specialist come first, then the busiest. */
export function compareStaffingRows(a: ProductStaffingRow, b: ProductStaffingRow): number {
  const gap = (row: ProductStaffingRow) => (row.coverage === "full" ? 1 : 0);
  return (
    gap(a) - gap(b) ||
    (b.open_leads ?? 0) - (a.open_leads ?? 0) ||
    a.label.localeCompare(b.label)
  );
}

export type SpecialistRole = ProductStaffPerson["role"];

export const ROLE_LABEL: Record<SpecialistRole, string> = {
  telecaller: "Telecaller",
  employee: "Officer",
};

/** The create form, prefilled for a new specialist of this product. */
export function addSpecialistHref(role: SpecialistRole, productId: string): string {
  const params = new URLSearchParams({ role, product: productId });
  return `/dashboard/users?${params.toString()}`;
}

export function productDashboardHref(productId: string): string {
  return `/dashboard/products/${encodeURIComponent(productId)}`;
}

/** Unspecialised people of one role that an Admin can assign to a product. */
export function assignableFor(
  available: readonly ProductStaffPerson[],
  role: SpecialistRole,
): ProductStaffPerson[] {
  return available
    .filter((person) => person.role === role && person.status === "active")
    .sort((a, b) => `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`));
}

export function personLabel(person: Pick<ProductStaffPerson, "first_name" | "last_name" | "staff_code">): string {
  return `${person.first_name} ${person.last_name}`.trim() + ` · ${person.staff_code}`;
}

export const PERIOD_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

/** "45.5%" or a dash when there is nothing to divide. */
export function formatRate(value: number | null | undefined): string {
  return value == null ? "—" : `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}
