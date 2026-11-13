import { Building2, Home, LandPlot, TreePine, Warehouse } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { components } from "@contracts/generated/schema";

import { listingSaleType, type PropertyListing as BaseListing, type SaleType } from "@/lib/properties";
import { categoryArtwork } from "@/lib/property-artwork";
import { listingPriceRupees } from "@/lib/property-budget";

// Derived from the generated contract, never hand-declared: a category,
// furnishing state, or construction status the backend adds later must surface
// as a compile error here (and in RE_CATEGORIES / the parser tuples in
// lib/property-facets.ts), not as a value the dashboard silently never renders.
type Schemas = components["schemas"];
export type RECategory = Schemas["PropertyCategory"];
export type RESubtype = Schemas["PropertySubtype"];
export type Furnishing = Schemas["Furnishing"];
export type ListingStatus = Schemas["ConstructionStatus"];

// Dashboard listings are populated from the authenticated property API. Keep
// this module limited to types and pure filtering so production search never
// falls back to a frontend-authored city, locality, PIN, or sample listing.
export type REListing = Omit<BaseListing, "category" | "reraNumber"> & {
  category: RECategory;
  pincode: string;
  furnishing: Furnishing | null;
  status: ListingStatus | null;
  amenities: string[];
  ageYears: number;
  city: string;
  locality: string;
  state?: string;
  bhk: number;
  areaSqft: number;
  priceLakhs: number;
  constructionStatus?: ListingStatus | null;
  /** Rent-only terms; all null on a sale listing. */
  securityDepositPaise?: number | null;
  minimumLeaseMonths?: number | null;
  availableFrom?: string | null;
  listingLinks?: components["schemas"]["ListingLink"][] | null;
  reraApplicability?: components["schemas"]["ReraApplicability"];
  reraNumber?: string | null;
  reraVerificationStatus?: components["schemas"]["ReraVerificationStatus"];
  structuredDetails?: components["schemas"]["PropertyRead"]["structured_details"];
};

export const RE_CATEGORIES: {
  key: RECategory;
  label: string;
  icon: LucideIcon;
  blurb: string;
  // Local generated representative artwork for the dashboard's category cards.
  // One subtype stands in for a category with more than one (apartments ->
  // gated community, commercial -> unlocked space).
  illustration: string;
}[] = [
  {
    key: "houses",
    label: "Residential Houses",
    icon: Home,
    blurb: "Independent houses and row houses on their own plot.",
    illustration: categoryArtwork("houses"),
  },
  {
    key: "apartments",
    label: "Apartments",
    icon: Building2,
    blurb: "Flats and apartment homes, ready to move or under construction.",
    illustration: categoryArtwork("apartments"),
  },
  {
    key: "villas",
    label: "Villas",
    icon: TreePine,
    blurb: "Gated-community villas with private gardens and amenities.",
    illustration: categoryArtwork("villas"),
  },
  {
    key: "plots",
    label: "Plots and Land",
    icon: LandPlot,
    blurb: "Residential plots and farm land to build on or hold for later.",
    illustration: categoryArtwork("plots"),
  },
  {
    key: "commercial",
    label: "Commercial",
    icon: Warehouse,
    blurb: "Offices, shops, and commercial spaces for your business.",
    illustration: categoryArtwork("commercial"),
  },
];

export function getRECategory(key: string): (typeof RE_CATEGORIES)[number] | undefined {
  return RE_CATEGORIES.find((category) => category.key === key);
}

export function populatedPropertyCategories(listings: REListing[]) {
  return RE_CATEGORIES.flatMap((category) => {
    const categoryListings = listings.filter((listing) => listing.category === category.key);
    return categoryListings.length > 0 ? [{ category, listings: categoryListings }] : [];
  });
}

export type SortOrder = "relevance" | "price_asc" | "price_desc" | "newest";

/** Age of a resale property, in whole years since completion. */
export type AgeBand = "under_5" | "5_to_10" | "10_plus";

export function ageBandOf(ageYears: number): AgeBand {
  if (ageYears < 5) return "under_5";
  if (ageYears < 10) return "5_to_10";
  return "10_plus";
}

export type PropertyFilters = {
  q?: string;
  /** Sale vs rent/lease. Also scopes the price facet, whose ranges differ by an
   * order of magnitude between a sale price and a monthly rent. */
  intent?: components["schemas"]["ListingIntent"][];
  /** New launch vs resale. Only sale listings can match. */
  saleType?: SaleType[];
  /** Age of property, mainly for resale homes. */
  age?: AgeBand[];
  categories?: RECategory[];
  subtypes?: RESubtype[];
  bhk?: number[];
  /** Budget bounds in whole rupees (see lib/property-budget.ts). */
  budgetMin?: number;
  budgetMax?: number;
  areaMin?: number;
  areaMax?: number;
  status?: ListingStatus[];
  furnishing?: Furnishing[];
  amenities?: string[];
  city?: string;
  locality?: string;
  pincode?: string;
  /** Exact developer / builder brand, matched case-insensitively. */
  developer?: string;
  sort?: SortOrder;
};

const FACET_KEYS = [
  "intent",
  "saleType",
  "age",
  "categories",
  "subtypes",
  "bhk",
  "budgetMin",
  "budgetMax",
  "areaMin",
  "areaMax",
  "status",
  "furnishing",
  "amenities",
  "city",
  "locality",
  "pincode",
  "developer",
] as const;

export function filterListings(listings: REListing[], filters: PropertyFilters): REListing[] {
  const query = filters.q?.trim().toLowerCase();
  return listings.filter((listing) => {
    if (filters.intent?.length && !filters.intent.includes(listing.listingIntent)) return false;
    if (filters.saleType?.length) {
      const saleType = listing.listingIntent === "sale" ? listingSaleType(listing.structuredDetails) : null;
      if (!saleType || !filters.saleType.includes(saleType)) return false;
    }
    if (filters.age?.length && !filters.age.includes(ageBandOf(listing.ageYears))) return false;
    if (filters.categories?.length && !filters.categories.includes(listing.category)) return false;
    // Legacy rows carry no subtype. Asking for a subtype is a narrower question
    // than asking for its category, so an unclassified listing cannot answer it
    // and is excluded rather than assumed to match.
    if (
      filters.subtypes?.length &&
      (!listing.propertySubtype || !filters.subtypes.includes(listing.propertySubtype))
    ) {
      return false;
    }
    if (filters.bhk?.length && !filters.bhk.includes(listing.bhk)) return false;
    if (filters.budgetMin != null || filters.budgetMax != null) {
      const rupees = listingPriceRupees(listing.priceLakhs);
      if (filters.budgetMin != null && rupees < filters.budgetMin) return false;
      if (filters.budgetMax != null && rupees > filters.budgetMax) return false;
    }
    if (filters.areaMin != null && listing.areaSqft < filters.areaMin) return false;
    if (filters.areaMax != null && listing.areaSqft > filters.areaMax) return false;
    if (filters.status?.length && (!listing.status || !filters.status.includes(listing.status))) return false;
    if (filters.furnishing?.length && (!listing.furnishing || !filters.furnishing.includes(listing.furnishing))) return false;
    if (filters.amenities?.length && !filters.amenities.every((item) => listing.amenities.includes(item))) {
      return false;
    }
    if (filters.city && listing.city !== filters.city) return false;
    if (filters.locality && listing.locality !== filters.locality) return false;
    if (filters.pincode && listing.pincode !== filters.pincode) return false;
    if (
      filters.developer &&
      listing.developerName?.toLowerCase() !== filters.developer.toLowerCase()
    ) {
      return false;
    }
    if (query) {
      const haystack = `${listing.title} ${listing.developerName ?? ""} ${listing.locality} ${listing.city} ${listing.pincode}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

export function sortListings(listings: REListing[], sort: SortOrder = "relevance"): REListing[] {
  if (sort === "relevance") return listings;
  const sorted = [...listings];
  if (sort === "price_asc") sorted.sort((a, b) => a.priceLakhs - b.priceLakhs);
  if (sort === "price_desc") sorted.sort((a, b) => b.priceLakhs - a.priceLakhs);
  if (sort === "newest") sorted.sort((a, b) => a.ageYears - b.ageYears);
  return sorted;
}

export function hasActiveFilters(filters: PropertyFilters): boolean {
  if (filters.q?.trim()) return true;
  return FACET_KEYS.some((key) => {
    const value = filters[key];
    return Array.isArray(value) ? value.length > 0 : value != null && value !== "";
  });
}

export function countActiveFilters(filters: PropertyFilters): number {
  let count = filters.q?.trim() ? 1 : 0;
  for (const key of FACET_KEYS) {
    const value = filters[key];
    if (Array.isArray(value)) {
      if (value.length > 0) count += 1;
    } else if (value != null && value !== "") {
      count += 1;
    }
  }
  return count;
}
