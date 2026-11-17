// Product, bank and amount filters for the Admin loan-applications list
// (CS-023). Pure so the matching rules are unit-tested; options follow the one
// rule every dashboard uses: the catalogue plus what the loaded rows carry.

import { ALL_FILTER, type FilterOption } from "@/features/dashboard/filter-options";
import { mergeOptions, parseRupees } from "@/features/dashboard/product-filter-options";
import type { AdminLoanApplication } from "@/lib/admin-api";

export type AdminLoanDetailFilters = {
  loanTypeId: string;
  bankId: string;
  /** Requested amount in rupees, as typed. */
  amountMin: string;
  amountMax: string;
};

export const EMPTY_ADMIN_LOAN_DETAIL: AdminLoanDetailFilters = {
  loanTypeId: ALL_FILTER,
  bankId: ALL_FILTER,
  amountMin: "",
  amountMax: "",
};

export function matchesAdminLoanDetail(
  application: Pick<AdminLoanApplication, "loan_type_id" | "bank_id" | "amount_requested">,
  filters: AdminLoanDetailFilters,
): boolean {
  if (filters.loanTypeId !== ALL_FILTER && application.loan_type_id !== filters.loanTypeId) return false;
  if (filters.bankId !== ALL_FILTER && application.bank_id !== filters.bankId) return false;
  const min = parseRupees(filters.amountMin);
  const max = parseRupees(filters.amountMax);
  if (min === null && max === null) return true;
  const requested = application.amount_requested === null || application.amount_requested === undefined
    ? null
    : Number(application.amount_requested);
  if (requested === null || Number.isNaN(requested)) return false;
  if (min !== null && requested < min) return false;
  return !(max !== null && requested > max);
}

/** How many of these filters are set (the amount range counts once). */
export function adminLoanDetailCount(filters: AdminLoanDetailFilters): number {
  return [
    filters.loanTypeId !== ALL_FILTER,
    filters.bankId !== ALL_FILTER,
    parseRupees(filters.amountMin) !== null || parseRupees(filters.amountMax) !== null,
  ].filter(Boolean).length;
}

/** Catalogue products and banks plus every one on the loaded applications. */
export function adminLoanOptions(
  rows: readonly AdminLoanApplication[],
  catalogue: { loanTypes: readonly FilterOption[]; banks: readonly FilterOption[] },
): { loanTypes: FilterOption[]; banks: FilterOption[] } {
  return {
    loanTypes: mergeOptions(
      catalogue.loanTypes,
      rows.map((row) => ({ value: row.loan_type_id, label: row.loan_type_label })),
    ),
    banks: mergeOptions(
      catalogue.banks,
      rows.flatMap((row) => (row.bank_id && row.bank_name ? [{ value: row.bank_id, label: row.bank_name }] : [])),
    ),
  };
}
