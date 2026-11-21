import { expect, it } from "vitest";
import { commissionRateLabel, parseCommissionRate } from "./commission-rate";
import { matchesResubmission } from "@/features/telecaller/lead-signal-filters";

it("converts percent/fixed input without confusing rupees and basis points", () => {
  expect(parseCommissionRate("percent", "0.5", "  Standard  ")).toEqual({ kind: "percent", percent_bps: 50, amount_paise: null, note: "Standard" });
  expect(parseCommissionRate("fixed", "1234.56", "")).toEqual({ kind: "fixed", percent_bps: null, amount_paise: 123456, note: null });
  for (const value of ["0", "100.01", "0.001", "1e2"]) expect(parseCommissionRate("percent", value, "")).toBeNull();
  expect(commissionRateLabel({ kind: "percent", percent_bps: 50, amount_paise: null })).toBe("0.5% of disbursed amount");
});
it("filters resubmissions safely when an older row lacks the count", () => {
  expect(matchesResubmission(2, "yes")).toBe(true);
  expect(matchesResubmission(2, "no")).toBe(false);
  expect(matchesResubmission(undefined, "no")).toBe(true);
  expect(matchesResubmission(undefined, "yes")).toBe(false);
  expect(matchesResubmission(0, "all")).toBe(true);
});
