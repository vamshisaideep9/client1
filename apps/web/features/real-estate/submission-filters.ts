import type { components } from "@contracts/generated/schema";

import { matchesSearch } from "@/features/dashboard/filter-bar";
import { isInDateRange } from "@/lib/date-range";
import { BHK_OPTIONS, LISTING_INTENT_VALUES, RE_CATEGORY_VALUES } from "@/lib/property-facets";
import { boundedNumberFilter } from "@/lib/form-validation";
import { CONSTRUCTION_OPTIONS, FURNISHING_OPTIONS } from "@/lib/property-submit";
import type { Submission } from "@/lib/property-submissions-api";
import { PROPERTY_SUBTYPE_OPTIONS, propertySubtypeOption } from "@/lib/property-taxonomy";

/**
 * Client-side filters for an author's own listings (`/dashboard/my-submissions`).
 *
 * Each author has a small number of rows and the API already scopes them, so
 * filtering stays in the browser like every other dashboard list. The filter
 * state lives in the URL; parsing is strict so a hand-edited or stale link
 * falls back to "all" instead of showing an inexplicably empty list.
 */
type Schemas = components["schemas"];

export const SUBMISSION_STATUS_OPTIONS = [
  { value: "pending", label: "Pending review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "withdrawn", label: "Withdrawn" },
] as const satisfies readonly { value: Schemas["SubmissionStatus"]; label: string }[];

export const RERA_REVIEW_OPTIONS = [
  { value: "not_reviewed", label: "RERA not reviewed" },
  { value: "verified", label: "RERA verified" },
  { value: "mismatch", label: "RERA mismatch" },
  { value: "exemption_verified", label: "Exemption verified" },
] as const satisfies readonly { value: Schemas["ReraVerificationStatus"]; label: string }[];

export const CATEGORY_OPTIONS = [
  { value: "houses", label: "Houses" },
  { value: "apartments", label: "Apartments" },
  { value: "villas", label: "Villas" },
  { value: "plots", label: "Plots and land" },
  { value: "commercial", label: "Commercial" },
] as const satisfies readonly { value: (typeof RE_CATEGORY_VALUES)[number]; label: string }[];

export const SUBMISSION_SORT_OPTIONS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "area_asc", label: "Area: small to large" },
  { value: "area_desc", label: "Area: large to small" },
] as const;

export type SubmissionSort = (typeof SUBMISSION_SORT_OPTIONS)[number]["value"];
export type MediaPresence = "all" | "yes" | "no";

export type SubmissionFilters = {
  search: string;
  status: "all" | Schemas["SubmissionStatus"];
  intent: "all" | Schemas["ListingIntent"];
  category: "all" | Schemas["PropertyCategory"];
  subtype: "all" | Schemas["PropertySubtype"];
  /** Lower-cased city key, or "all". */
  city: string;
  /** "1"-"4" match exactly; "5" means five or more. */
  bhk: string;
  /** Whole rupees, as typed. */
  priceMin: string;
  priceMax: string;
  /** Square feet, as typed. */
  areaMin: string;
  areaMax: string;
  furnishing: "all" | Schemas["Furnishing"];
  construction: "all" | Schemas["ConstructionStatus"];
  rera: "all" | Schemas["ReraVerificationStatus"];
  panorama: MediaPresence;
  documents: MediaPresence;
  from: string;
  to: string;
  sort: SubmissionSort;
};

export const EMPTY_SUBMISSION_FILTERS: SubmissionFilters = {
  search: "",
  status: "all",
  intent: "all",
  category: "all",
  subtype: "all",
  city: "all",
  bhk: "all",
  priceMin: "",
  priceMax: "",
  areaMin: "",
  areaMax: "",
  furnishing: "all",
  construction: "all",
  rera: "all",
  panorama: "all",
  documents: "all",
  from: "",
  to: "",
  sort: "newest",
};

const MAX_RUPEES = 1_000_000_000_000;
const MAX_SQFT = 100_000_000;
const SEARCH_MAX_LENGTH = 100;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** URL query keys, kept short and readable. */
const PARAM: Record<keyof SubmissionFilters, string> = {
  search: "q",
  status: "status",
  intent: "intent",
  category: "category",
  subtype: "subtype",
  city: "city",
  bhk: "bhk",
  priceMin: "price_min",
  priceMax: "price_max",
  areaMin: "area_min",
  areaMax: "area_max",
  furnishing: "furnishing",
  construction: "construction",
  rera: "rera",
  panorama: "panorama",
  documents: "documents",
  from: "from",
  to: "to",
  sort: "sort",
};

/** Filters revealed by "More filters"; a range counts once. */
const ADVANCED_KEYS = [
  "subtype",
  "city",
  "bhk",
  "price",
  "area",
  "furnishing",
  "construction",
  "rera",
  "panorama",
  "documents",
] as const;

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | "all" {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : "all";
}

export function cityKey(city: string): string {
  return city.trim().toLowerCase();
}

/** Drop a subtype that does not belong to the chosen category. */
export function normalizeSubmissionFilters(filters: SubmissionFilters): SubmissionFilters {
  if (filters.subtype === "all" || filters.category === "all") return filters;
  return propertySubtypeOption(filters.subtype)?.category === filters.category
    ? filters
    : { ...filters, subtype: "all" };
}

export function parseSubmissionFilters(params: URLSearchParams): SubmissionFilters {
  const get = (key: keyof SubmissionFilters) => params.get(PARAM[key]);
  const rupees = (key: keyof SubmissionFilters) =>
    boundedNumberFilter(get(key) ?? undefined, { min: 0, max: MAX_RUPEES, integer: true }) ?? "";
  const sqft = (key: keyof SubmissionFilters) =>
    boundedNumberFilter(get(key) ?? undefined, { min: 0, max: MAX_SQFT, integer: true }) ?? "";
  const date = (key: keyof SubmissionFilters) => {
    const value = get(key) ?? "";
    return DATE_PATTERN.test(value) ? value : "";
  };
  const presence = (key: keyof SubmissionFilters): MediaPresence =>
    oneOf(get(key), ["yes", "no"] as const);
  const city = get("city")?.trim() ?? "";
  const sort = SUBMISSION_SORT_OPTIONS.find((option) => option.value === get("sort"));

  return normalizeSubmissionFilters({
    search: (get("search") ?? "").slice(0, SEARCH_MAX_LENGTH),
    status: oneOf(get("status"), SUBMISSION_STATUS_OPTIONS.map((option) => option.value)),
    intent: oneOf(get("intent"), LISTING_INTENT_VALUES),
    category: oneOf(get("category"), RE_CATEGORY_VALUES),
    subtype: oneOf(get("subtype"), PROPERTY_SUBTYPE_OPTIONS.map((option) => option.value)),
    city: city && city.length <= 80 ? cityKey(city) : "all",
    bhk: oneOf(get("bhk"), BHK_OPTIONS.map((option) => String(option.value))),
    priceMin: rupees("priceMin"),
    priceMax: rupees("priceMax"),
    areaMin: sqft("areaMin"),
    areaMax: sqft("areaMax"),
    furnishing: oneOf(get("furnishing"), FURNISHING_OPTIONS.map((option) => option.value)),
    construction: oneOf(get("construction"), CONSTRUCTION_OPTIONS.map((option) => option.value)),
    rera: oneOf(get("rera"), RERA_REVIEW_OPTIONS.map((option) => option.value)),
    panorama: presence("panorama"),
    documents: presence("documents"),
    from: date("from"),
    to: date("to"),
    sort: sort?.value ?? "newest",
  });
}

/** Only non-default values are written, so a clean list has a clean URL. */
export function serializeSubmissionFilters(filters: SubmissionFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of Object.keys(PARAM) as (keyof SubmissionFilters)[]) {
    const value = key === "search" ? filters.search.trim() : filters[key];
    if (value !== EMPTY_SUBMISSION_FILTERS[key] && value !== "") params.set(PARAM[key], value);
  }
  return params;
}

function isAdvancedActive(filters: SubmissionFilters, key: (typeof ADVANCED_KEYS)[number]): boolean {
  if (key === "price") return filters.priceMin !== "" || filters.priceMax !== "";
  if (key === "area") return filters.areaMin !== "" || filters.areaMax !== "";
  return filters[key] !== EMPTY_SUBMISSION_FILTERS[key];
}

/** How many of the "More filters" fields narrow the list. */
export function countAdvancedSubmissionFilters(filters: SubmissionFilters): number {
  return ADVANCED_KEYS.filter((key) => isAdvancedActive(filters, key)).length;
}

/** How many filters narrow the list; sort order is not a filter. */
export function countActiveSubmissionFilters(filters: SubmissionFilters): number {
  const basic = (["search", "status", "intent", "category"] as const).filter((key) =>
    key === "search" ? filters.search.trim() !== "" : filters[key] !== "all",
  ).length;
  const dates = filters.from !== "" || filters.to !== "" ? 1 : 0;
  return basic + dates + countAdvancedSubmissionFilters(filters);
}

/** Distinct cities in the loaded rows, labelled as first written. */
export function submissionCityOptions(rows: readonly Submission[]): { value: string; label: string }[] {
  const byKey = new Map<string, string>();
  for (const row of rows) {
    const label = row.city.trim();
    if (label && !byKey.has(cityKey(label))) byKey.set(cityKey(label), label);
  }
  return [...byKey]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label, "en-IN"));
}

function inRange(value: number, min: string, max: string, scale = 1): boolean {
  return (min === "" || value >= Number(min) * scale) && (max === "" || value <= Number(max) * scale);
}

function hasMedia(row: Submission, kind: "panorama" | "document"): boolean {
  return (row.media ?? []).some((asset) => asset.kind === kind);
}

function matchesPresence(present: boolean, wanted: MediaPresence): boolean {
  return wanted === "all" || present === (wanted === "yes");
}

export function matchesSubmissionFilters(row: Submission, filters: SubmissionFilters): boolean {
  const search = filters.search.trim();
  if (search) {
    const haystack = [
      row.title,
      row.location,
      row.locality,
      row.city,
      row.pincode,
      row.developer_name,
      row.rera_number,
    ]
      .filter(Boolean)
      .join(" ");
    if (!matchesSearch(haystack, search)) return false;
  }
  if (filters.bhk !== "all") {
    const wanted = Number(filters.bhk);
    if (wanted >= 5 ? row.bhk < 5 : row.bhk !== wanted) return false;
  }
  return (
    (filters.status === "all" || row.status === filters.status) &&
    (filters.intent === "all" || row.listing_intent === filters.intent) &&
    (filters.category === "all" || row.category === filters.category) &&
    (filters.subtype === "all" || row.property_subtype === filters.subtype) &&
    (filters.city === "all" || cityKey(row.city) === filters.city) &&
    inRange(row.price_paise, filters.priceMin, filters.priceMax, 100) &&
    inRange(row.area_sqft, filters.areaMin, filters.areaMax) &&
    (filters.furnishing === "all" || row.furnishing === filters.furnishing) &&
    (filters.construction === "all" || row.construction_status === filters.construction) &&
    (filters.rera === "all" || row.rera_verification_status === filters.rera) &&
    matchesPresence(hasMedia(row, "panorama"), filters.panorama) &&
    matchesPresence(hasMedia(row, "document"), filters.documents) &&
    isInDateRange(row.created_at, filters.from, filters.to)
  );
}

const SORTERS: Record<SubmissionSort, (a: Submission, b: Submission) => number> = {
  newest: (a, b) => b.created_at.localeCompare(a.created_at),
  oldest: (a, b) => a.created_at.localeCompare(b.created_at),
  price_asc: (a, b) => a.price_paise - b.price_paise,
  price_desc: (a, b) => b.price_paise - a.price_paise,
  area_asc: (a, b) => a.area_sqft - b.area_sqft,
  area_desc: (a, b) => b.area_sqft - a.area_sqft,
};

/** Filter, then sort; ties keep newest first so the order is stable. */
export function applySubmissionFilters(
  rows: readonly Submission[],
  filters: SubmissionFilters,
): Submission[] {
  const compare = SORTERS[filters.sort];
  return rows
    .filter((row) => matchesSubmissionFilters(row, filters))
    .sort((a, b) => compare(a, b) || SORTERS.newest(a, b) || a.id.localeCompare(b.id));
}
