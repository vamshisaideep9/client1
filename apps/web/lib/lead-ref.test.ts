import { describe, expect, it } from "vitest";

import { leadRefDigits, matchesAnyLeadRef, matchesLeadRef } from "./lead-ref";

describe("leadRefDigits", () => {
  it.each(["LD-00000123", "ld-123", "Ld-0123", "LD 123", "LD123", "123", " 00000123 "])(
    "reads %j as lead 123",
    (value) => {
      expect(leadRefDigits(value)).toBe("123");
    },
  );

  it("keeps numbers past eight digits and past 2^53 exact", () => {
    expect(leadRefDigits("LD-123456789")).toBe("123456789");
    expect(leadRefDigits("LD-900719925474099312")).toBe("900719925474099312");
  });

  it.each(["", "   ", "LD-", "LD-0", "0", "-5", "LD--12", "AB-123", "LD-12a", "12 34", "1".repeat(19), "9".repeat(40), null, undefined])(
    "rejects %j",
    (value) => {
      expect(leadRefDigits(value)).toBeNull();
    },
  );
});

describe("matchesLeadRef", () => {
  it("matches the same number in any tolerant form", () => {
    expect(matchesLeadRef("ld-123", "LD-00000123")).toBe(true);
    expect(matchesLeadRef("123", "LD-00000123")).toBe(true);
  });

  it("never matches a partial number or a missing reference", () => {
    expect(matchesLeadRef("12", "LD-00000123")).toBe(false);
    expect(matchesLeadRef("LD-1234", "LD-00000123")).toBe(false);
    expect(matchesLeadRef("asha", "LD-00000123")).toBe(false);
    expect(matchesLeadRef("123", null)).toBe(false);
  });
});

describe("matchesAnyLeadRef", () => {
  it("matches one reference of a grouped payout", () => {
    expect(matchesAnyLeadRef("LD-00000007", ["LD-00000003", "LD-00000007"])).toBe(true);
    expect(matchesAnyLeadRef("LD-00000008", ["LD-00000003", "LD-00000007"])).toBe(false);
    expect(matchesAnyLeadRef("LD-00000008", undefined)).toBe(false);
  });
});
