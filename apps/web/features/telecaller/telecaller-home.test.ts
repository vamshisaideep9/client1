import { describe, expect, it } from "vitest";

import { greeting } from "./telecaller-home";

describe("telecaller home greeting", () => {
  it("greets the Telecaller by first name", () => {
    expect(greeting("Asha")).toBe("Hi, Asha");
    expect(greeting("  Ravi ")).toBe("Hi, Ravi");
  });

  it("falls back while the profile loads or has no name", () => {
    expect(greeting(undefined)).toBe("Hi there");
    expect(greeting(null)).toBe("Hi there");
    expect(greeting("   ")).toBe("Hi there");
  });
});
