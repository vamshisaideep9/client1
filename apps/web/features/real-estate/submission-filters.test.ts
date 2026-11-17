import { describe, expect, it } from "vitest";

import type { Submission } from "@/lib/property-submissions-api";

import {
  EMPTY_SUBMISSION_FILTERS,
  applySubmissionFilters,
  countActiveSubmissionFilters,
  countAdvancedSubmissionFilters,
  matchesSubmissionFilters,
  normalizeSubmissionFilters,
  parseSubmissionFilters,
  serializeSubmissionFilters,
  submissionCityOptions,
  type SubmissionFilters,
} from "./submission-filters";

function row(overrides: Partial<Submission>): Submission {
  return {
    id: "00000000-0000-4000-8000-000000000000",
    title: "Synthetic listing",
    type: "Apartment",
    location: "Kondapur, Hyderabad",
    locality: "Kondapur",
    city: "Hyderabad",
    state: "Telangana",
    pincode: "500084",
    developer_name: null,
    meta: null,
    image: null,
    category: "apartments",
    property_subtype: "standalone_apartment",
    listing_intent: "sale",
    price_paise: 1_20_00_00_000,
    security_deposit_paise: null,
    minimum_lease_months: null,
    available_from: null,
    bhk: 3,
    area_sqft: 1750,
    furnishing: "semi",
    construction_status: "ready",
    amenities: [],
    age_years: 3,
    rera_number: "RERA/TS/DEMO/SUB01",
    rera_applicability: "applicable",
    rera_verification_status: "not_reviewed",
    rera_verified_at: null,
    status: "pending",
    review_note: null,
    reviewed_at: null,
    reviewed_by_uuid: null,
    approved_property_id: null,
    submitter_uuid: "00000000-0000-4000-8000-0000000000aa",
    details: {},
    details_version: null,
    structured_details: null,
    listing_links: null,
    media: [],
    created_at: "2026-11-10T09:00:00Z",
    updated_at: "2026-11-10T09:00:00Z",
    ...overrides,
  };
}

const flat = row({ id: "a", title: "Kondapur Flat" });
const office = row({
  id: "b",
  title: "HITEC Office",
  location: "HITEC City, Hyderabad",
  locality: "HITEC City",
  pincode: "500081",
  category: "commercial",
  property_subtype: "locked_space",
  listing_intent: "rent",
  price_paise: 1_20_000_00,
  bhk: 0,
  area_sqft: 2200,
  furnishing: "furnished",
  rera_number: "P02400000101",
  rera_verification_status: "mismatch",
  status: "rejected",
  developer_name: "Cyber Towers Realty",
  media: [{ kind: "document" } as NonNullable<Submission["media"]>[number]],
  created_at: "2026-11-01T09:00:00Z",
});
const villa = row({
  id: "c",
  title: "Rushikonda Villa",
  location: "Rushikonda, Visakhapatnam",
  locality: "Rushikonda",
  city: "Visakhapatnam",
  pincode: "530045",
  category: "villas",
  property_subtype: "villa",
  listing_intent: "rent",
  price_paise: 85_000_00,
  bhk: 5,
  area_sqft: 4200,
  furnishing: "furnished",
  construction_status: "under_construction",
  rera_verification_status: "verified",
  status: "approved",
  media: [{ kind: "panorama" } as NonNullable<Submission["media"]>[number]],
  created_at: "2026-10-20T09:00:00Z",
});
const farm = row({
  id: "d",
  title: "Mamnoor Farmland",
  location: "Mamnoor, Warangal",
  locality: "Mamnoor",
  city: " warangal ",
  pincode: "506166",
  category: "plots",
  property_subtype: "farmland",
  price_paise: 45_00_00_000,
  bhk: 0,
  area_sqft: 43_560,
  furnishing: null,
  construction_status: null,
  rera_number: null,
  rera_applicability: "exemption_claimed",
  rera_verification_status: "exemption_verified",
  status: "withdrawn",
  created_at: "2026-11-15T09:00:00Z",
});
const rows = [flat, office, villa, farm];

function ids(filters: Partial<SubmissionFilters>): string[] {
  return applySubmissionFilters(rows, { ...EMPTY_SUBMISSION_FILTERS, ...filters }).map((r) => r.id);
}

describe("submission filters", () => {
  it("shows every row, newest first, with no filters", () => {
    expect(ids({})).toEqual(["d", "a", "b", "c"]);
    expect(countActiveSubmissionFilters(EMPTY_SUBMISSION_FILTERS)).toBe(0);
  });

  it("searches title, locality, pincode, developer and RERA number", () => {
    expect(ids({ search: "kondapur" })).toEqual(["a"]);
    expect(ids({ search: "530045" })).toEqual(["c"]);
    expect(ids({ search: "cyber towers" })).toEqual(["b"]);
    expect(ids({ search: "P0240" })).toEqual(["b"]);
    expect(ids({ search: "   " })).toHaveLength(4);
  });

  it("filters each single-value facet", () => {
    expect(ids({ status: "approved" })).toEqual(["c"]);
    expect(ids({ status: "withdrawn" })).toEqual(["d"]);
    expect(ids({ intent: "rent" })).toEqual(["b", "c"]);
    expect(ids({ category: "plots" })).toEqual(["d"]);
    expect(ids({ subtype: "locked_space" })).toEqual(["b"]);
    expect(ids({ furnishing: "furnished" })).toEqual(["b", "c"]);
    expect(ids({ construction: "under_construction" })).toEqual(["c"]);
    expect(ids({ rera: "exemption_verified" })).toEqual(["d"]);
    expect(ids({ rera: "mismatch" })).toEqual(["b"]);
  });

  it("matches cities case- and space-insensitively", () => {
    expect(ids({ city: "warangal" })).toEqual(["d"]);
    expect(submissionCityOptions(rows)).toEqual([
      { value: "hyderabad", label: "Hyderabad" },
      { value: "visakhapatnam", label: "Visakhapatnam" },
      { value: "warangal", label: "warangal" },
    ]);
  });

  it("treats 5 BHK as five or more and excludes plots from any BHK choice", () => {
    expect(ids({ bhk: "3" })).toEqual(["a"]);
    expect(ids({ bhk: "5" })).toEqual(["c"]);
    expect(ids({ bhk: "1" })).toEqual([]);
  });

  it("bounds price in rupees and area in square feet, inclusively", () => {
    expect(ids({ priceMax: "120000" })).toEqual(["b", "c"]);
    expect(ids({ priceMin: "120000", priceMax: "120000" })).toEqual(["b"]);
    expect(ids({ priceMin: "10000000" })).toEqual(["a"]);
    expect(ids({ areaMin: "2200", areaMax: "4200" })).toEqual(["b", "c"]);
    expect(ids({ priceMin: "200", priceMax: "100" })).toEqual([]);
  });

  it("filters by 360° images and documents, both ways", () => {
    expect(ids({ panorama: "yes" })).toEqual(["c"]);
    expect(ids({ panorama: "no" })).toEqual(["d", "a", "b"]);
    expect(ids({ documents: "yes" })).toEqual(["b"]);
  });

  it("bounds the submitted date", () => {
    expect(ids({ from: "2026-11-01", to: "2026-11-10" })).toEqual(["a", "b"]);
    expect(ids({ to: "2026-10-31" })).toEqual(["c"]);
  });

  it("combines filters with AND", () => {
    expect(ids({ intent: "rent", furnishing: "furnished", panorama: "yes" })).toEqual(["c"]);
    expect(ids({ intent: "rent", status: "pending" })).toEqual([]);
    expect(matchesSubmissionFilters(villa, { ...EMPTY_SUBMISSION_FILTERS, city: "hyderabad" })).toBe(false);
  });

  it("sorts by date, price and area", () => {
    expect(ids({ sort: "oldest" })).toEqual(["c", "b", "a", "d"]);
    expect(ids({ sort: "price_asc" })).toEqual(["c", "b", "d", "a"]);
    expect(ids({ sort: "price_desc" })).toEqual(["a", "d", "b", "c"]);
    expect(ids({ sort: "area_asc" })).toEqual(["a", "b", "c", "d"]);
    expect(ids({ sort: "area_desc" })).toEqual(["d", "c", "b", "a"]);
  });

  it("drops a subtype that is outside the chosen category", () => {
    const narrowed = normalizeSubmissionFilters({
      ...EMPTY_SUBMISSION_FILTERS,
      category: "plots",
      subtype: "villa",
    });
    expect(narrowed.subtype).toBe("all");
    const kept = normalizeSubmissionFilters({
      ...EMPTY_SUBMISSION_FILTERS,
      category: "plots",
      subtype: "farmland",
    });
    expect(kept.subtype).toBe("farmland");
  });

  it("counts active filters, with each range counted once and sort ignored", () => {
    const filters: SubmissionFilters = {
      ...EMPTY_SUBMISSION_FILTERS,
      search: "flat",
      status: "pending",
      priceMin: "1",
      priceMax: "2",
      areaMax: "900",
      from: "2026-11-01",
      to: "2026-11-30",
      panorama: "no",
      sort: "price_desc",
    };
    expect(countAdvancedSubmissionFilters(filters)).toBe(3);
    expect(countActiveSubmissionFilters(filters)).toBe(6);
  });

  it("round-trips through the URL and writes only non-default values", () => {
    const filters: SubmissionFilters = {
      ...EMPTY_SUBMISSION_FILTERS,
      search: "Kondapur",
      status: "approved",
      intent: "rent",
      category: "apartments",
      subtype: "gated_community_apartment",
      city: "hyderabad",
      bhk: "2",
      priceMin: "5000",
      priceMax: "90000",
      areaMin: "500",
      areaMax: "1500",
      furnishing: "unfurnished",
      construction: "ready",
      rera: "verified",
      panorama: "yes",
      documents: "no",
      from: "2026-10-01",
      to: "2026-11-30",
      sort: "area_desc",
    };
    const params = serializeSubmissionFilters(filters);
    expect(parseSubmissionFilters(new URLSearchParams(params.toString()))).toEqual(filters);
    expect(serializeSubmissionFilters(EMPTY_SUBMISSION_FILTERS).toString()).toBe("");
    expect(serializeSubmissionFilters({ ...EMPTY_SUBMISSION_FILTERS, status: "pending" }).toString()).toBe(
      "status=pending",
    );
  });

  it("falls back to defaults for invalid URL values", () => {
    const parsed = parseSubmissionFilters(
      new URLSearchParams(
        "status=deleted&intent=lease&category=castle&subtype=igloo&bhk=9&price_min=-5&price_max=1e9" +
          "&area_min=abc&furnishing=luxury&construction=soon&rera=maybe&panorama=sometimes" +
          "&from=yesterday&to=2026-13&sort=random&city=" +
          "x".repeat(81),
      ),
    );
    expect(parsed).toEqual(EMPTY_SUBMISSION_FILTERS);
  });

  it("clears a mismatched subtype from a hand-edited URL", () => {
    const parsed = parseSubmissionFilters(new URLSearchParams("category=commercial&subtype=plot"));
    expect(parsed).toMatchObject({ category: "commercial", subtype: "all" });
  });
});
