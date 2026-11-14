import { describe, expect, it } from "vitest";

import { BRAND_ASSETS, TRUST_LINES, trustLinesForPath } from "@/lib/brand";

describe("trustLinesForPath", () => {
  it.each(["/loans", "/loans/home-loan", "/loans/credit-card"])("shows only the lender line on %s", (path) => {
    expect(trustLinesForPath(path)).toEqual([TRUST_LINES.finance]);
  });

  it.each(["/real-estate", "/real-estate/properties/abc"])("shows only the property line on %s", (path) => {
    expect(trustLinesForPath(path)).toEqual([TRUST_LINES.property]);
  });

  it.each(["/", "/calculators/emi", "/contact", "/loansx", "/real-estates", null, undefined])("shows both lines on %s", (path) => {
    expect(trustLinesForPath(path)).toEqual([TRUST_LINES.finance, TRUST_LINES.property]);
  });

  it("keeps the property line free of lender wording", () => {
    expect(`${TRUST_LINES.property.lead} ${TRUST_LINES.property.rest}`).not.toMatch(/bank|lender/i);
  });
});

describe("BRAND_ASSETS", () => {
  it("matches the generated captioned lockup dimensions", () => {
    expect(BRAND_ASSETS.horizontal).toMatchObject({ width: 960, height: 232 });
    expect(BRAND_ASSETS.stacked).toMatchObject({ width: 960, height: 930 });
  });
});
