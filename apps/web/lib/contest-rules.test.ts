import { describe, expect, it } from "vitest";

import { progressRows } from "./contest-rules";

describe("contest progress rows", () => {
  it("shows each target with the at-most limit and money totals", () => {
    const rows = progressRows(
      {
        version: 1,
        loans: {
          counted_stage: "disbursed",
          count_at_least: 2,
          count_at_most: 5,
          amount_at_least_paise: 50_00_000_00,
        },
      },
      { count: 6, amount_paise: 25_00_000_00 },
    );
    expect(rows.map((row) => [row.key, row.achieved, row.target, row.met])).toEqual([
      ["count", "6", "at least 2", true],
      ["count_at_most", "6", "at most 5", false],
      ["amount", "₹25,00,000", "at least ₹50,00,000", false],
    ]);
    expect(rows[2].share).toBe(0.5);
  });

  it("needs the minimum calls before a connect rate counts", () => {
    const [rate] = progressRows(
      { version: 1, activity: { connect_rate_at_least_percent: 40, connect_rate_min_calls: 20 } },
      { connect_rate_percent: 50, calls_logged: 10 },
    );
    expect(rate.met).toBe(false);
    expect(rate.share).toBe(0.5);
  });
});
