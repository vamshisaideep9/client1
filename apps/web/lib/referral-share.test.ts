import { describe, expect, it } from "vitest";

import {
  buildReferMessage,
  buildRegisterUrl,
  buildWaMeUrl,
  isValidReferralCodeFormat,
  normalizeReferralCode,
  withReferral,
} from "@/lib/referral-share";

describe("buildRegisterUrl()", () => {
  it("appends ?ref= with the code", () => {
    expect(buildRegisterUrl("https://brolly.example", "AB12CD34")).toBe(
      "https://brolly.example/register?ref=AB12CD34",
    );
  });

  it("strips a trailing slash on the origin", () => {
    expect(buildRegisterUrl("https://brolly.example/", "AB12CD34")).toBe(
      "https://brolly.example/register?ref=AB12CD34",
    );
  });

  it("URL-encodes the code", () => {
    expect(buildRegisterUrl("https://brolly.example", "AB 12")).toBe(
      "https://brolly.example/register?ref=AB%2012",
    );
  });
});

describe("buildWaMeUrl()", () => {
  it("carries no destination number", () => {
    const url = buildWaMeUrl("https://brolly.example", "AB12CD34");
    expect(url.startsWith("https://wa.me/?text=")).toBe(true);
  });

  it("embeds the code and the register link in the message", () => {
    const url = buildWaMeUrl("https://brolly.example", "AB12CD34");
    const message = decodeURIComponent(url.replace("https://wa.me/?text=", ""));
    expect(message).toContain("AB12CD34");
    expect(message).toContain("https://brolly.example/register?ref=AB12CD34");
  });

  it("produces a valid URL with no unencoded whitespace", () => {
    const url = buildWaMeUrl("https://brolly.example", "AB12CD34");
    expect(url).not.toMatch(/\s/);
    expect(() => new URL(url)).not.toThrow();
  });
});

describe("normalizeReferralCode()", () => {
  it("strips and uppercases", () => {
    expect(normalizeReferralCode("  ab12cd34  ")).toBe("AB12CD34");
  });

  it("aliases O/I/L to digits", () => {
    expect(normalizeReferralCode("O1I2L3")).toBe("011213");
  });
});

describe("isValidReferralCodeFormat()", () => {
  it("accepts an 8-char Crockford code", () => {
    expect(isValidReferralCodeFormat("AB12CD34")).toBe(true);
  });

  it("rejects the wrong length", () => {
    expect(isValidReferralCodeFormat("AB12")).toBe(false);
  });

  it("rejects confusable letters (I/L/O/U), which normalize already removes", () => {
    expect(isValidReferralCodeFormat("ABILOU12")).toBe(false);
  });
});

describe("withReferral()", () => {
  it("adds ?ref= to an absolute URL before the hash", () => {
    expect(withReferral("https://x.example/loans/home-loan#providers", "AB12CD34")).toBe(
      "https://x.example/loans/home-loan?ref=AB12CD34#providers",
    );
  });

  it("replaces an existing ref and keeps other parameters", () => {
    expect(withReferral("https://x.example/p?ref=OLD00000&a=1", "AB12CD34")).toBe(
      "https://x.example/p?ref=AB12CD34&a=1",
    );
  });

  it("keeps relative paths relative", () => {
    expect(withReferral("/real-estate/properties/1", "AB12CD34")).toBe(
      "/real-estate/properties/1?ref=AB12CD34",
    );
  });

  it("returns the URL unchanged without a code", () => {
    expect(withReferral("https://x.example/p", null)).toBe("https://x.example/p");
  });
});

describe("buildReferMessage()", () => {
  it("names the item and the code", () => {
    const message = buildReferMessage("Sunny Homes", "https://x.example/p?ref=AB12CD34", "AB12CD34");
    expect(message).toContain("Sunny Homes");
    expect(message).toContain("AB12CD34");
    expect(message).toContain("https://x.example/p?ref=AB12CD34");
  });
});
