import { describe, expect, it } from "vitest";

import type { AgentsReportRow, TeamPerformanceSummary } from "@/lib/reports-api";

import {
  conversionSeries,
  formatBucketLabel,
  istDate,
  journeyTrend,
  teamShare,
  topAgents,
  type JourneyRow,
} from "./report-chart-data";

// Bucket starts are IST midnight sent as UTC instants (18:30 the day before).
const WEEK_1 = "2026-11-01T18:30:00Z"; // Mon 2 Nov IST
const WEEK_2 = "2026-11-08T18:30:00Z"; // Mon 9 Nov IST

const ROWS: JourneyRow[] = [
  // Newest first, as the table's default sort would return them.
  { bucket_start: WEEK_2, business_line: "real_estate", total: 4, converted: 1 },
  { bucket_start: WEEK_1, business_line: "real_estate", total: 2, converted: 0 },
  { bucket_start: WEEK_1, business_line: "loans", total: 6, converted: 3 },
];

function agent(name: string, leads: number, converted = 0): AgentsReportRow {
  return {
    agent_profile_uuid: `uuid-${name}`,
    agent_code: name.toUpperCase(),
    agent_name: name,
    business_line: "loans",
    leads_total: leads,
    leads_converted: converted,
    loans_total: 0,
    loans_converted: 0,
    deals_total: 0,
    deals_converted: 0,
  } as AgentsReportRow;
}

function team(line: string, leads: number): TeamPerformanceSummary {
  return {
    business_line: line,
    agent_count: 1,
    leads_total: leads,
    leads_converted: 0,
    loans_total: 0,
    loans_converted: 0,
    deals_total: 0,
    deals_converted: 0,
  } as TeamPerformanceSummary;
}

describe("istDate", () => {
  it("reads the IST calendar day of a UTC instant", () => {
    expect(istDate(WEEK_1)).toBe("2026-11-02");
    expect(istDate("2026-11-02T00:00:00+05:30")).toBe("2026-11-02");
  });
});

describe("formatBucketLabel", () => {
  it("labels weeks by day and months by month", () => {
    expect(formatBucketLabel("2026-11-02", "week")).toBe("2 Nov");
    expect(formatBucketLabel("2026-11-01", "month")).toBe("Nov 2026");
  });
});

describe("journeyTrend", () => {
  it("merges each bucket's lines into one point in date order, filling missing lines with zero", () => {
    const trend = journeyTrend(ROWS, "loans", "week");
    expect(trend.title).toBe("Applications per week");
    expect(trend.series).toEqual([
      { key: "loans", label: "Loans" },
      { key: "real_estate", label: "Real Estate" },
    ]);
    expect(trend.points).toEqual([
      { day: "2026-11-02", values: { loans: 6, real_estate: 2 } },
      { day: "2026-11-09", values: { loans: 0, real_estate: 4 } },
    ]);
  });

  it("keeps only the selected line as a series", () => {
    const trend = journeyTrend(ROWS.filter((row) => row.business_line === "loans"), "leads", "month", "loans");
    expect(trend.title).toBe("Leads per month");
    expect(trend.series.map((series) => series.key)).toEqual(["loans"]);
    expect(trend.points).toEqual([{ day: "2026-11-02", values: { loans: 6 } }]);
  });

  it("returns no points for no rows", () => {
    expect(journeyTrend([], "deals").points).toEqual([]);
  });
});

describe("conversionSeries", () => {
  it("divides converted by total per bucket across lines", () => {
    expect(conversionSeries(ROWS)).toEqual([
      { day: "2026-11-02", total: 8, converted: 3, rate: 37.5 },
      { day: "2026-11-09", total: 4, converted: 1, rate: 25 },
    ]);
  });

  it("has no rate for a bucket with no activity", () => {
    expect(conversionSeries([{ bucket_start: WEEK_1, business_line: "loans", total: 0, converted: 0 }])).toEqual([
      { day: "2026-11-02", total: 0, converted: 0, rate: null },
    ]);
    expect(conversionSeries([])).toEqual([]);
  });
});

describe("topAgents", () => {
  it("ranks by leads, breaks ties by name, drops agents with no leads and caps the list", () => {
    const rows = [agent("Cara", 3, 1), agent("Ben", 9, 4), agent("Abe", 3), agent("Dan", 0), agent("Eve", 1)];
    const top = topAgents(rows, 3);
    expect(top.map((item) => item.label)).toEqual(["Ben (BEN)", "Abe (ABE)", "Cara (CARA)"]);
    expect(top[0]).toMatchObject({ value: 9, converted: 4, note: "4 converted" });
    expect(topAgents([agent("Dan", 0)])).toEqual([]);
  });
});

describe("teamShare", () => {
  it("lists lines in a fixed order and omits lines with no leads", () => {
    const share = teamShare([team("real_estate", 5), team("loans", 7)]);
    expect(share.kind).toBe("share");
    expect(share.items).toEqual([
      { key: "loans", label: "Loans", value: 7 },
      { key: "real_estate", label: "Real Estate", value: 5 },
    ]);
    expect(teamShare([team("loans", 0)]).items).toEqual([]);
    expect(teamShare([]).items).toEqual([]);
  });
});
