// Pure helpers for product specialists (2026-11-26): the specialist's own home
// counts and the defaulted "My product" list filter. Framework-free so the
// rules are unit-tested once and shared by the Telecaller and Officer screens.

import type { ActiveFilterChip } from "./filter-options";

/** One row of a home's per-product counts (leads or tasks); null product = none recorded. */
export type ProductWorkCount = {
  product_id?: string | null;
  label?: string | null;
  category?: string | null;
  open?: number;
  overdue?: number;
  converted_30d?: number;
  completed_30d?: number;
};

export const PRODUCT_CATEGORY_LABEL: Record<string, string> = {
  loan: "Loan",
  credit_card: "Credit card",
  insurance: "Insurance",
};

/** "Home Loan specialist". */
export function specialistTitle(label: string): string {
  return `${label} specialist`;
}

/** The specialty's own counts, and every other product the caller worked on. */
export function splitProductCounts<T extends ProductWorkCount>(
  counts: readonly T[] | null | undefined,
  specialtyId: string | null | undefined,
): { mine: T | null; others: T[] } {
  const rows = counts ?? [];
  if (!specialtyId) return { mine: null, others: [...rows] };
  return {
    mine: rows.find((row) => row.product_id === specialtyId) ?? null,
    others: rows.filter((row) => row.product_id !== specialtyId),
  };
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** `?product=<id>` from a home link, or null when absent or malformed. */
export function productParam(params: Pick<URLSearchParams, "get">): string | null {
  const value = params.get("product");
  return value && UUID_PATTERN.test(value) ? value : null;
}

/** A list link narrowed to one product (the list reads `?product=`). */
export function productListHref(base: string, productId: string | null | undefined): string {
  return productId ? `${base}?product=${encodeURIComponent(productId)}` : base;
}

/**
 * The list filters with the product preset, unless a product is already
 * chosen. A link's `?product=` wins over the caller's specialty.
 */
export function withDefaultProduct<T extends { loanTypeId: string }>(filters: T, productId: string | null): T {
  if (!productId || filters.loanTypeId !== "all") return filters;
  return { ...filters, loanTypeId: productId };
}

/** Renames the product chip "My product" while it shows the caller's specialty. */
export function withMyProductChip(
  chips: readonly ActiveFilterChip[],
  loanTypeId: string,
  specialtyId: string | null | undefined,
): ActiveFilterChip[] {
  if (!specialtyId || loanTypeId !== specialtyId) return [...chips];
  return chips.map((chip) =>
    chip.id === "loanTypeId" ? { ...chip, label: chip.label.replace(/^Product:/, "My product:") } : chip,
  );
}
