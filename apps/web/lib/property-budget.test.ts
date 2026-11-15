import { describe, expect, it } from "vitest";

import {
  BUDGET_MAX_RUPEES,
  BUDGET_STOPS,
  BUDGET_TOP_INDEX,
  budgetFromSliderCommit,
  budgetFromStops,
  budgetStopIndex,
  formatBudget,
  formatBudgetRange,
  listingPriceRupees,
  orderBudget,
  parseBudgetInput,
} from "@/lib/property-budget";

describe("budget scale", () => {
  it("runs from zero to ₹20 Cr in ascending stops", () => {
    expect(BUDGET_STOPS[0]).toBe(0);
    expect(BUDGET_STOPS[BUDGET_TOP_INDEX]).toBe(20_00_00_000);
    expect(BUDGET_MAX_RUPEES).toBe(20_00_00_000);
    for (let i = 1; i < BUDGET_STOPS.length; i += 1) {
      expect(BUDGET_STOPS[i]).toBeGreaterThan(BUDGET_STOPS[i - 1]);
    }
    // Sub-crore homes get 5 L resolution instead of collapsing into one end.
    expect(BUDGET_STOPS).toContain(50_00_000);
    expect(BUDGET_STOPS).toContain(1_25_00_000);
  });

  it("treats the end stops as no constraint", () => {
    expect(budgetFromStops(0, BUDGET_TOP_INDEX)).toEqual({
      budgetMin: undefined,
      budgetMax: undefined,
    });
    expect(budgetFromStops(1, BUDGET_TOP_INDEX - 1)).toEqual({
      budgetMin: 5_00_000,
      budgetMax: 19_00_00_000,
    });
  });

  it("maps a rupee amount to the nearest stop and falls back when unset", () => {
    expect(budgetStopIndex(undefined, 7)).toBe(7);
    expect(budgetStopIndex(25_000, BUDGET_TOP_INDEX)).toBe(0);
    expect(BUDGET_STOPS[budgetStopIndex(52_00_000, 0)]).toBe(50_00_000);
    expect(budgetStopIndex(99_00_00_000, 0)).toBe(BUDGET_TOP_INDEX);
  });
});

describe("budgetFromSliderCommit", () => {
  it("keeps an exact typed edge when only the other thumb moves", () => {
    const current = { budgetMin: 25_000, budgetMax: 52_00_000 };
    const committed = [budgetStopIndex(25_000, 0), budgetStopIndex(52_00_000, BUDGET_TOP_INDEX)] as const;
    // Drag only the max thumb one stop up.
    expect(budgetFromSliderCommit(committed, [committed[0], committed[1] + 1], current)).toEqual({
      budgetMin: 25_000,
      budgetMax: BUDGET_STOPS[committed[1] + 1],
    });
    // Drag only the min thumb.
    expect(budgetFromSliderCommit(committed, [3, committed[1]], current)).toEqual({
      budgetMin: BUDGET_STOPS[3],
      budgetMax: 52_00_000,
    });
  });

  it("clears an edge dragged back to its end stop", () => {
    expect(
      budgetFromSliderCommit([2, 10], [0, BUDGET_TOP_INDEX], { budgetMin: 10_00_000, budgetMax: 50_00_000 }),
    ).toEqual({ budgetMin: undefined, budgetMax: undefined });
  });
});

describe("parseBudgetInput", () => {
  it("keeps digits only", () => {
    expect(parseBudgetInput("₹1,25,00,000")).toBe(1_25_00_000);
    expect(parseBudgetInput("25k")).toBe(25);
    expect(parseBudgetInput("abc")).toBeUndefined();
    expect(parseBudgetInput("")).toBeUndefined();
    expect(parseBudgetInput("-500")).toBe(500);
    expect(parseBudgetInput("0005000")).toBe(5000);
    expect(parseBudgetInput("0")).toBe(0);
  });

  it("clamps to ₹20 Cr, including very long pastes", () => {
    expect(parseBudgetInput("250000000")).toBe(BUDGET_MAX_RUPEES);
    expect(parseBudgetInput("9".repeat(40))).toBe(BUDGET_MAX_RUPEES);
  });
});

describe("orderBudget", () => {
  it("swaps a reversed pair and leaves open ends alone", () => {
    expect(orderBudget(80, 20)).toEqual({ budgetMin: 20, budgetMax: 80 });
    expect(orderBudget(20, 80)).toEqual({ budgetMin: 20, budgetMax: 80 });
    expect(orderBudget(undefined, 80)).toEqual({ budgetMin: undefined, budgetMax: 80 });
  });
});

describe("formatting", () => {
  it("formats rupees, lakhs and crores", () => {
    expect(formatBudget(25_000)).toBe("₹25,000");
    expect(formatBudget(50_00_000)).toBe("₹50 L");
    expect(formatBudget(1_25_00_000)).toBe("₹1.25 Cr");
    expect(formatBudget(20_00_00_000)).toBe("₹20 Cr");
  });

  it("summarises open-ended ranges", () => {
    expect(formatBudgetRange(undefined, 50_00_000)).toBe("₹0 - ₹50 L");
    expect(formatBudgetRange(50_00_000, undefined)).toBe("₹50 L - ₹20 Cr+");
  });

  it("converts a lakh-normalised listing price to whole rupees", () => {
    expect(listingPriceRupees(0.25)).toBe(25_000);
    expect(listingPriceRupees(125)).toBe(1_25_00_000);
  });
});
