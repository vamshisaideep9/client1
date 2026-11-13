"use client";

import * as React from "react";
import {
  parseAsArrayOf,
  parseAsInteger,
  parseAsString,
  parseAsStringLiteral,
  useQueryStates,
  type Values,
} from "nuqs";

import {
  AGE_BAND_VALUES,
  FURNISHING_VALUES,
  LISTING_INTENT_VALUES,
  RE_CATEGORY_VALUES,
  RE_SUBTYPE_VALUES,
  SALE_TYPE_VALUES,
  SORT_VALUES,
  STATUS_VALUES,
} from "@/lib/property-facets";
import {
  filterListings,
  hasActiveFilters,
  countActiveFilters,
  sortListings,
  type Furnishing,
  type ListingStatus,
  type PropertyFilters,
  type RECategory,
  type REListing,
  type RESubtype,
  type SortOrder,
} from "@/lib/real-estate";

// One hook owns every search + filter facet in the URL query string, mirroring
// the nuqs pattern already used by the calculator islands
// (components/calculators/islands/emi-calculator.tsx). Filters are shareable,
// bookmarkable, and survive reload; results derive from the API-backed source
// through the pure filterListings/sortListings engine in lib/real-estate.ts.
const PARSERS = {
  q: parseAsString,
  intent: parseAsArrayOf(parseAsStringLiteral(LISTING_INTENT_VALUES)),
  saleType: parseAsArrayOf(parseAsStringLiteral(SALE_TYPE_VALUES)),
  age: parseAsArrayOf(parseAsStringLiteral(AGE_BAND_VALUES)),
  categories: parseAsArrayOf(parseAsStringLiteral(RE_CATEGORY_VALUES)),
  subtypes: parseAsArrayOf(parseAsStringLiteral(RE_SUBTYPE_VALUES)),
  bhk: parseAsArrayOf(parseAsInteger),
  // Whole rupees. `priceMin`/`priceMax` are the earlier whole-lakh keys, still
  // read so shared and bookmarked links keep meaning the same budget.
  budgetMin: parseAsInteger,
  budgetMax: parseAsInteger,
  priceMin: parseAsInteger,
  priceMax: parseAsInteger,
  areaMin: parseAsInteger,
  areaMax: parseAsInteger,
  status: parseAsArrayOf(parseAsStringLiteral(STATUS_VALUES)),
  furnishing: parseAsArrayOf(parseAsStringLiteral(FURNISHING_VALUES)),
  amenities: parseAsArrayOf(parseAsString),
  city: parseAsString,
  locality: parseAsString,
  pincode: parseAsString,
  developer: parseAsString,
  sort: parseAsStringLiteral(SORT_VALUES),
};

function lakhsToRupees(lakhs: number | null): number | undefined {
  return lakhs == null ? undefined : lakhs * 100_000;
}

function toPropertyFilters(state: Values<typeof PARSERS>): PropertyFilters {
  return {
    q: state.q ?? undefined,
    intent: (state.intent ?? undefined) as PropertyFilters["intent"],
    saleType: (state.saleType ?? undefined) as PropertyFilters["saleType"],
    age: (state.age ?? undefined) as PropertyFilters["age"],
    categories: (state.categories ?? undefined) as RECategory[] | undefined,
    subtypes: (state.subtypes ?? undefined) as RESubtype[] | undefined,
    bhk: state.bhk ?? undefined,
    budgetMin: state.budgetMin ?? lakhsToRupees(state.priceMin),
    budgetMax: state.budgetMax ?? lakhsToRupees(state.priceMax),
    areaMin: state.areaMin ?? undefined,
    areaMax: state.areaMax ?? undefined,
    status: (state.status ?? undefined) as ListingStatus[] | undefined,
    furnishing: (state.furnishing ?? undefined) as Furnishing[] | undefined,
    amenities: state.amenities ?? undefined,
    city: state.city ?? undefined,
    locality: state.locality ?? undefined,
    pincode: state.pincode ?? undefined,
    developer: state.developer ?? undefined,
    sort: (state.sort ?? undefined) as SortOrder | undefined,
  };
}

// `source` scopes the searchable/filterable API result set;
// `lockedCategory` pins one category invisibly (used on a per-category Explore
// page) so that category never shows as a user-facing chip or active-filter and
// can't be cleared, while still constraining results.
export function usePropertyFilters(opts: { source: REListing[]; lockedCategory?: RECategory }) {
  const { source, lockedCategory } = opts;

  const [state, setState] = useQueryStates(PARSERS, { clearOnDefault: true });

  const rawFilters = React.useMemo(() => toPropertyFilters(state), [state]);

  // User-facing filters never carry the locked category, so chips/activeCount
  // and the "Property type" facet stay clean.
  const filters = React.useMemo<PropertyFilters>(
    () => (lockedCategory ? { ...rawFilters, categories: undefined } : rawFilters),
    [rawFilters, lockedCategory],
  );

  const setFilters = React.useCallback(
    (patch: Partial<PropertyFilters>) => {
      // nuqs only clears a param when it's explicitly `null`; map our
      // "undefined means no constraint" convention onto that so removing a
      // facet chip actually drops it from the URL instead of no-op'ing.
      const next: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(patch)) {
        next[key] = value === undefined ? null : value;
      }
      // Any budget write supersedes a legacy lakh-denominated link value.
      if ("budgetMin" in patch || "budgetMax" in patch) {
        next.priceMin = null;
        next.priceMax = null;
      }
      setState(next as Parameters<typeof setState>[0]);
    },
    [setState],
  );

  const clearAll = React.useCallback(() => {
    setState(null);
  }, [setState]);

  const results = React.useMemo(() => {
    // Inject the locked category only into the engine input, never the UI state.
    const effective = lockedCategory ? { ...filters, categories: [lockedCategory] } : filters;
    return sortListings(filterListings(source, effective), filters.sort);
  }, [source, filters, lockedCategory]);

  return {
    filters,
    setFilters,
    clearAll,
    active: hasActiveFilters(filters),
    activeCount: countActiveFilters(filters),
    results,
    resultCount: results.length,
  };
}
