import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authHref,
  buildReferMessage,
  buildReferUrl,
  captureIncomingReferral,
  clearIncomingReferral,
  readIncomingReferral,
  referReturnToFor,
  buildRegisterUrl,
  buildWaMeUrl,
  isValidReferralCodeFormat,
  normalizeReferralCode,
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

describe("referReturnToFor()", () => {
  const id = "c5c7763c-70c1-4ebb-aec5-d4daf28832cb";

  it("sends a referred property to its signed-in dashboard page", () => {
    expect(referReturnToFor(`/real-estate/properties/${id}`)).toBe(`/dashboard/properties/${id}`);
    expect(referReturnToFor(`/real-estate/properties/${id.toUpperCase()}#gallery`)).toBe(
      `/dashboard/properties/${id}`,
    );
  });

  it("falls back to the dashboard home for anything else", () => {
    expect(referReturnToFor("/loans/home-loan#providers")).toBe("/dashboard");
    expect(referReturnToFor("/real-estate/properties/not-a-uuid")).toBe("/dashboard");
    expect(referReturnToFor("https://evil.example/real-estate/properties/" + id)).toBe("/dashboard");
  });
});

describe("authHref()", () => {
  it("carries the code and the destination", () => {
    expect(authHref("/register", { code: "AB12CD34", returnTo: "/dashboard/properties/x" })).toBe(
      "/register?ref=AB12CD34&return_to=%2Fdashboard%2Fproperties%2Fx",
    );
    expect(authHref("/login", { code: "AB12CD34", returnTo: "/dashboard/properties/x" })).toBe(
      "/login?ref=AB12CD34&return_to=%2Fdashboard%2Fproperties%2Fx",
    );
  });

  it("omits what is absent and the default dashboard destination", () => {
    expect(authHref("/login", { code: null, returnTo: "/dashboard" })).toBe("/login");
    expect(authHref("/register", { returnTo: "/dashboard/explore" })).toBe(
      "/register?return_to=%2Fdashboard%2Fexplore",
    );
    expect(authHref("/register", { code: "AB12CD34" })).toBe("/register?ref=AB12CD34");
  });
});

describe("buildReferUrl()", () => {
  it("points at Register with the code, then the referred page", () => {
    expect(buildReferUrl("https://x.example/", "AB12CD34", "/dashboard/properties/p1")).toBe(
      "https://x.example/register?ref=AB12CD34&return_to=%2Fdashboard%2Fproperties%2Fp1",
    );
  });
});

describe("incoming referral capture", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubSession() {
    const store = new Map<string, string>();
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    });
    return store;
  }

  it("keeps the latest valid link code and forgets it once used", () => {
    stubSession();
    captureIncomingReferral("?ref=ab12cd34");
    expect(readIncomingReferral()).toBe("AB12CD34");
    captureIncomingReferral("?ref=ZZ99YY88");
    expect(readIncomingReferral()).toBe("ZZ99YY88");
    captureIncomingReferral("?ref=bad");
    expect(readIncomingReferral()).toBe("ZZ99YY88");
    clearIncomingReferral();
    expect(readIncomingReferral()).toBeNull();
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
