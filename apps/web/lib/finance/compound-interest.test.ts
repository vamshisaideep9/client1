import { describe, expect, it } from "vitest";

import { compoundInterest } from "@/lib/finance";

describe("compoundInterest", () => {
  it("matches the closed form for a lump sum compounded quarterly", () => {
    // 1,00,000 at 8% quarterly for 10 years: P(1 + 0.02)^40.
    const expected = Math.round(100000 * Math.pow(1.02, 40));
    const result = compoundInterest(100000, 8, 10, 4);
    expect(result.maturity).toBe(expected);
    expect(result.invested).toBe(100000);
    expect(result.interest).toBe(expected - 100000);
    expect(result.schedule).toHaveLength(10);
    expect(result.schedule.at(-1)?.balance).toBe(expected);
  });

  it("earns more with more frequent compounding at the same rate", () => {
    const yearly = compoundInterest(100000, 10, 5, 1).maturity;
    const monthly = compoundInterest(100000, 10, 5, 12).maturity;
    expect(monthly).toBeGreaterThan(yearly);
    expect(yearly).toBe(Math.round(100000 * Math.pow(1.1, 5)));
  });

  it("adds monthly contributions to the invested total", () => {
    const result = compoundInterest(0, 0, 2, 12, 1000);
    expect(result.invested).toBe(24000);
    expect(result.maturity).toBe(24000);
    expect(result.interest).toBe(0);
  });

  it("treats negative or zero inputs as nothing to grow", () => {
    const result = compoundInterest(-5, -3, 0, 4, -100);
    expect(result).toEqual({ maturity: 0, invested: 0, interest: 0, schedule: [] });
  });
});
