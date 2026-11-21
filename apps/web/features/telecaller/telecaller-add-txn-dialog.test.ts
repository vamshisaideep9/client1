import { describe, expect, it } from "vitest";

import { amountPreview, localDateInputValue } from "./telecaller-add-txn-dialog";

describe("add transaction dialog helpers", () => {
  it("defaults the date to the viewer's local day", () => {
    expect(localDateInputValue(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
    expect(localDateInputValue(new Date(2026, 10, 13, 0, 5))).toBe("2026-11-13");
  });

  it("previews a typed amount in rupees, with a compact form for large values", () => {
    expect(amountPreview("")).toBeNull();
    expect(amountPreview("0")).toBeNull();
    expect(amountPreview("abc")).toBeNull();
    const preview = amountPreview("500000");
    expect(preview).toContain("5,00,000");
    expect(preview).toContain("L");
  });
});
