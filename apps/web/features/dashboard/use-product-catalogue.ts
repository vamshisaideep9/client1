"use client";

import * as React from "react";

import { getBanks, getLoanTypes } from "@/lib/loans";

import type { FilterOption } from "./filter-options";

/** The active financial-product catalogue, as filter options (CS-023). */
export type ProductCatalogue = {
  /** Lending products only: loan applications exist only for these. */
  loanTypes: FilterOption[];
  /**
   * Every active product (loan, credit card and insurance), for filters on a
   * lead's stored product, which can be any category.
   */
  products: FilterOption[];
  banks: FilterOption[];
  bankNames: string[];
};

const EMPTY: ProductCatalogue = { loanTypes: [], products: [], banks: [], bankNames: [] };

// One fetch per page load for every filter bar on screen; a failed read is not
// kept, so the next bar that mounts tries again.
let pending: Promise<ProductCatalogue> | null = null;

function loadCatalogue(): Promise<ProductCatalogue> {
  pending ??= Promise.all([getLoanTypes(), getBanks()])
    .then(([types, banks]) => {
      if (!types.ok || !banks.ok) pending = null;
      return {
        loanTypes: types.ok
          ? types.data
              .filter((product) => product.category === "loan")
              .map((product) => ({ value: product.id, label: product.label }))
          : [],
        products: types.ok
          ? types.data.map((product) => ({ value: product.id, label: product.label }))
          : [],
        banks: banks.ok ? banks.data.map((bank) => ({ value: bank.id, label: bank.name })) : [],
        bankNames: banks.ok ? banks.data.map((bank) => bank.name) : [],
      };
    })
    .catch(() => {
      pending = null;
      return EMPTY;
    });
  return pending;
}

/**
 * Loan types and banks from the catalogue endpoints every signed-in role may
 * read (`/loans/loan-types`, `/loans/banks`). Empty until loaded or when
 * `enabled` is false (a real-estate bar needs neither).
 */
export function useProductCatalogue(enabled = true): ProductCatalogue {
  const [catalogue, setCatalogue] = React.useState<ProductCatalogue>(EMPTY);
  React.useEffect(() => {
    if (!enabled) return;
    let live = true;
    void loadCatalogue().then((loaded) => {
      if (live) setCatalogue(loaded);
    });
    return () => {
      live = false;
    };
  }, [enabled]);
  return enabled ? catalogue : EMPTY;
}
