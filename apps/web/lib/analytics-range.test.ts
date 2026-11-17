import { describe, expect, it } from "vitest";

import {
  formatIsoDay,
  formatPeriodLabel,
  formatRangeLabel,
  isoToLocalDate,
  localDateToIso,
  matchingPreset,
  MAX_RANGE_DAYS,
  rangeError,
  rangeMonthTags,
  rangeSpanDays,
  resolveRangePreset,
  shiftIsoDate,
} from "@/lib/analytics-range";
import { buildReportParams } from "@/lib/reports";
import { buildMyAnalyticsQuery } from "@/lib/staff-analytics-api";
import {
  filtersForRole,
  moreFilterSpecGroups,
  requestFilters,
  withFilter,
  withFilters,
} from "@/features/analytics/staff-analytics-filter-bar";

// 2026-11-15 20:00 UTC is 2026-11-16 01:30 IST: the IST date must win.
const LATE_EVENING_UTC = new Date("2026-11-15T20:00:00Z");
const MID_NOV = new Date("2026-11-15T06:00:00Z");

describe("resolveRangePreset", () => {
  it("anchors every preset on the IST calendar day", () => {
    expect(resolveRangePreset("today", LATE_EVENING_UTC)).toEqual({ dateFrom: "2026-11-16", dateTo: "2026-11-16" });
    expect(resolveRangePreset("yesterday", LATE_EVENING_UTC)).toEqual({ dateFrom: "2026-11-15", dateTo: "2026-11-15" });
  });

  it("resolves rolling and calendar ranges", () => {
    expect(resolveRangePreset("last_7_days", MID_NOV)).toEqual({ dateFrom: "2026-11-09", dateTo: "2026-11-15" });
    expect(resolveRangePreset("last_30_days", MID_NOV)).toEqual({ dateFrom: "2026-10-17", dateTo: "2026-11-15" });
    expect(resolveRangePreset("this_month", MID_NOV)).toEqual({ dateFrom: "2026-11-01", dateTo: "2026-11-15" });
    expect(resolveRangePreset("last_month", MID_NOV)).toEqual({ dateFrom: "2026-10-01", dateTo: "2026-10-31" });
    expect(resolveRangePreset("this_quarter", MID_NOV)).toEqual({ dateFrom: "2026-10-01", dateTo: "2026-11-15" });
    expect(resolveRangePreset("this_year", MID_NOV)).toEqual({ dateFrom: "2026-01-01", dateTo: "2026-11-15" });
  });

  it("handles January's last month and the first quarter", () => {
    const jan = new Date("2027-01-10T06:00:00Z");
    expect(resolveRangePreset("last_month", jan)).toEqual({ dateFrom: "2026-12-01", dateTo: "2026-12-31" });
    expect(resolveRangePreset("this_quarter", jan)).toEqual({ dateFrom: "2027-01-01", dateTo: "2027-01-10" });
  });

  it("recognises a range that equals a preset", () => {
    expect(matchingPreset({ dateFrom: "2026-11-01", dateTo: "2026-11-15" }, MID_NOV)).toBe("this_month");
    expect(matchingPreset({ dateFrom: "2026-11-02", dateTo: "2026-11-15" }, MID_NOV)).toBeNull();
  });
});

describe("range validation and labels", () => {
  it("counts inclusive days and shifts across month ends", () => {
    expect(rangeSpanDays({ dateFrom: "2026-11-01", dateTo: "2026-11-01" })).toBe(1);
    expect(rangeSpanDays({ dateFrom: "2026-02-01", dateTo: "2026-03-01" })).toBe(29);
    expect(shiftIsoDate("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("rejects reversed, future and over-long ranges", () => {
    expect(rangeError({ dateFrom: "2026-11-10", dateTo: "2026-11-01" }, MID_NOV)).toMatch(/on or before/);
    expect(rangeError({ dateFrom: "2026-11-10", dateTo: "2026-11-16" }, MID_NOV)).toMatch(/future/);
    expect(rangeError({ dateFrom: "2025-11-01", dateTo: "2026-11-15" }, MID_NOV)).toMatch(String(MAX_RANGE_DAYS));
    expect(rangeError({ dateFrom: "2025-11-15", dateTo: "2026-11-15" }, MID_NOV)).toBeNull();
    expect(rangeError({ dateFrom: "", dateTo: "" }, MID_NOV)).toMatch(/start and an end/);
  });

  it("formats compact labels", () => {
    expect(formatRangeLabel({ dateFrom: "2026-11-15", dateTo: "2026-11-15" })).toBe("15 Nov 2026");
    expect(formatRangeLabel({ dateFrom: "2026-10-28", dateTo: "2026-11-15" })).toBe("28 Oct – 15 Nov 2026");
    expect(formatRangeLabel({ dateFrom: "2025-12-20", dateTo: "2026-01-05" })).toBe("20 Dec 2025 – 5 Jan 2026");
  });

  it("round-trips calendar days through local dates", () => {
    expect(localDateToIso(isoToLocalDate("2026-03-31"))).toBe("2026-03-31");
  });
});

describe("analytics request parameters", () => {
  it("builds the personal analytics query with only the filters that are set", () => {
    const query = buildMyAnalyticsQuery(
      { dateFrom: "2026-11-01", dateTo: "2026-11-15" },
      { call_status: "busy", interest: undefined },
    );
    expect(query).toBe("date_from=2026-11-01&date_to=2026-11-15&call_status=busy");
  });

  it("maps admin report detail filters to API parameters", () => {
    const params = buildReportParams({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-15",
      detail: { leadSource: "client", propertyCity: "  Hyderabad ", callStatus: "", telecallerProfileUuid: "t-1" },
    });
    expect(params.get("lead_source")).toBe("client");
    expect(params.get("property_city")).toBe("Hyderabad");
    expect(params.get("telecaller_profile_uuid")).toBe("t-1");
    expect(params.has("call_status")).toBe(false);
  });

  it("offers each role only the filters its analytics accept", () => {
    const keys = (role: string, line = "loans") => filtersForRole(role, line).map((spec) => spec.key);
    // CS-023: product filters on Loans, property filters on Real Estate,
    // Telecaller amount, Agent commission status and amount.
    expect(keys("telecaller")).toEqual([
      "call_status",
      "interest",
      "lead_source",
      "loan_type_id",
      "bank_id",
      "loan_status",
      "amount",
    ]);
    expect(keys("telecaller", "real_estate")).toEqual([
      "call_status",
      "interest",
      "lead_source",
      "property_category",
      "property_subtype",
      "deal_status",
      "amount",
    ]);
    expect(keys("employee")).toEqual(["task_type", "loan_type_id", "bank_id", "loan_status"]);
    expect(keys("employee", "real_estate")).toEqual(["task_type", "property_category", "property_subtype", "deal_status"]);
    expect(keys("agent")).toEqual(["lead_status", "loan_type_id", "bank_id", "loan_status", "commission_status", "amount"]);
    expect(keys("sub_admin")).toEqual(["content_type", "content_status", "placement", "banner_type", "discount_type"]);
    // The Admin hides the amount from Telecallers: no amount filter.
    expect(
      filtersForRole("telecaller", "loans", {}, { hiddenFilters: ["amount_max", "amount_min"] }).some(
        (spec) => spec.key === "amount",
      ),
    ).toBe(false);
  });

  it("hides Sub Admin filters that cannot match the chosen content type", () => {
    const keys = (content_type?: "banners" | "offers") =>
      filtersForRole("sub_admin", "loans", { content_type }).map((spec) => spec.key);
    expect(keys("offers")).toEqual(["content_type", "content_status", "discount_type"]);
    expect(keys("banners")).toEqual(["content_type", "content_status", "placement", "banner_type"]);
    // A banner-only filter hides the offer-only one, and the reverse.
    expect(filtersForRole("sub_admin", "loans", { placement: "homepage" }).map((spec) => spec.key)).toEqual([
      "content_type",
      "content_status",
      "placement",
      "banner_type",
    ]);
    expect(filtersForRole("sub_admin", "loans", { discount_type: "flat" }).map((spec) => spec.key)).toEqual([
      "content_type",
      "content_status",
      "discount_type",
    ]);
    // Other roles ignore the current filters.
    expect(filtersForRole("employee", "real_estate", { content_type: "offers" }).map((spec) => spec.key)).toEqual([
      "task_type",
      "property_category",
      "property_subtype",
      "deal_status",
    ]);
  });

  it("clears filters that no longer apply when the content type changes", () => {
    const start = { content_status: "live", placement: "homepage", banner_type: "action", discount_type: "flat" } as const;
    expect(withFilter("sub_admin", "loans", start, "content_type", "offers")).toEqual({
      content_type: "offers",
      content_status: "live",
      discount_type: "flat",
    });
    expect(withFilter("sub_admin", "loans", start, "content_type", "banners")).toEqual({
      content_type: "banners",
      content_status: "live",
      placement: "homepage",
      banner_type: "action",
    });
    // Picking a banner-only filter drops the offer-only one, and the reverse.
    expect(withFilter("sub_admin", "loans", { discount_type: "flat" }, "placement", "homepage")).toEqual({
      placement: "homepage",
    });
    expect(withFilter("sub_admin", "loans", { banner_type: "action" }, "discount_type", "flat")).toEqual({
      discount_type: "flat",
    });
    // Back to both kinds keeps what is left, and "all" removes the key.
    expect(withFilter("sub_admin", "loans", { content_type: "offers", discount_type: "flat" }, "content_type", undefined)).toEqual({
      discount_type: "flat",
    });
    expect(
      withFilter("telecaller", "loans", { call_status: "busy", interest: "hot" }, "interest", undefined),
    ).toEqual({ call_status: "busy" });
  });

  it("keeps the role's status filter in the first row and groups the rest behind More filters", () => {
    expect(
      moreFilterSpecGroups(filtersForRole("telecaller", "loans")).map((group) => [
        group.title,
        group.specs.map((spec) => spec.label),
      ]),
    ).toEqual([
      ["Lead", ["Call status", "Lead interest", "Lead source"]],
      ["Product", ["Product", "Bank", "Loan status"]],
      ["Money", ["Loan amount"]],
    ]);
    expect(
      moreFilterSpecGroups(filtersForRole("agent", "real_estate")).map((group) => [
        group.title,
        group.specs.map((spec) => spec.label),
      ]),
    ).toEqual([
      ["Property", ["Property category", "Property type", "Deal status"]],
      ["Money", ["Commission status", "Commission"]],
    ]);
    expect(filtersForRole("agent", "loans").filter((spec) => spec.group === null).map((spec) => spec.key)).toEqual([
      "lead_status",
    ]);
    expect(filtersForRole("sub_admin", "loans").find((spec) => spec.key === "content_status")?.group).toBeNull();
  });

  it("sends only the filters the role offers on the current line, amounts as plain rupees", () => {
    const filters = {
      loan_type_id: "lt-1",
      property_category: "villas",
      call_status: "busy",
      amount_min: "1,50,000",
      amount_max: "",
    } as const;
    expect(requestFilters("telecaller", "loans", filters)).toEqual({
      loan_type_id: "lt-1",
      call_status: "busy",
      amount_min: "150000",
    });
    expect(requestFilters("telecaller", "real_estate", filters)).toEqual({
      property_category: "villas",
      call_status: "busy",
      amount_min: "150000",
    });
    // Employees have no amount and no call status.
    expect(requestFilters("employee", "loans", filters)).toEqual({ loan_type_id: "lt-1" });
    // A hidden amount, or an inverted range, is never sent.
    expect(requestFilters("telecaller", "loans", filters, { hiddenFilters: ["amount_min", "amount_max"] })).toEqual({
      loan_type_id: "lt-1",
      call_status: "busy",
    });
    expect(requestFilters("agent", "loans", { amount_min: "500", amount_max: "100" })).toEqual({});
    expect(requestFilters("agent", "loans", { amount_min: "abc", amount_max: "100" })).toEqual({ amount_max: "100" });
  });

  it("drops filters of the other line when the line changes", () => {
    const loans = { loan_type_id: "lt-1", bank_id: "b-1", lead_status: "working" } as const;
    expect(withFilters("agent", "real_estate", loans, {})).toEqual({ lead_status: "working" });
    expect(withFilters("agent", "loans", loans, { amount_min: "10", amount_max: undefined })).toEqual({
      ...loans,
      amount_min: "10",
    });
  });
});

describe("KPI period label", () => {
  it("names a whole calendar month, such as the Last month default", () => {
    expect(formatPeriodLabel(resolveRangePreset("last_month", MID_NOV))).toBe("Oct 2026");
    expect(formatPeriodLabel({ dateFrom: "2024-02-01", dateTo: "2024-02-29" })).toBe("Feb 2024");
  });

  it("falls back to the range for anything else", () => {
    expect(formatPeriodLabel({ dateFrom: "2026-10-01", dateTo: "2026-10-15" })).toBe(
      formatRangeLabel({ dateFrom: "2026-10-01", dateTo: "2026-10-15" }),
    );
    expect(formatPeriodLabel({ dateFrom: "", dateTo: "" })).toBe("");
  });
});

describe("date range picker labels", () => {
  it("formats one chosen day, or nothing yet", () => {
    expect(formatIsoDay("2026-10-01")).toBe("1 Oct 2026");
    expect(formatIsoDay("")).toBe("");
  });

  it("tags the months holding the From and To days", () => {
    const from = new Date(2026, 9, 20);
    const to = new Date(2026, 10, 5);
    expect(rangeMonthTags(new Date(2026, 9, 1), from, to)).toEqual(["From"]);
    expect(rangeMonthTags(new Date(2026, 10, 1), from, to)).toEqual(["To"]);
    expect(rangeMonthTags(new Date(2026, 8, 1), from, to)).toEqual([]);
    expect(rangeMonthTags(new Date(2026, 9, 1), from, new Date(2026, 9, 25))).toEqual(["From", "To"]);
    // Half-picked: the start also stands in for the end, as when it is applied.
    expect(rangeMonthTags(new Date(2026, 9, 1), from, undefined)).toEqual(["From", "To"]);
  });
});
