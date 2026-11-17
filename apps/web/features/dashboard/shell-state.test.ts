import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserRole } from "@/lib/auth";

import {
  SIDEBAR_PREFERENCE_KEY,
  defaultDesktopSidebarExpanded,
  isDesktopSidebarExpanded,
  readStoredSidebarPreference,
  storeSidebarPreference,
} from "./shell-state";

const OPERATIONAL: UserRole[] = ["admin", "sub_admin", "agent", "telecaller", "employee"];

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => void values.set(key, value)),
  };
}

let storage: ReturnType<typeof memoryStorage>;

beforeEach(() => {
  storage = memoryStorage();
  vi.stubGlobal("window", { localStorage: storage });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dashboard desktop sidebar state", () => {
  it("starts operational roles expanded and lets them collapse", () => {
    for (const role of OPERATIONAL) {
      expect(defaultDesktopSidebarExpanded(role)).toBe(true);
      expect(isDesktopSidebarExpanded(role, null)).toBe(true);
      expect(isDesktopSidebarExpanded(role, false)).toBe(false);
    }
  });

  it("keeps the Client collapsed by default with session-only expand", () => {
    expect(defaultDesktopSidebarExpanded("client")).toBe(false);
    expect(isDesktopSidebarExpanded("client", null)).toBe(false);
    expect(isDesktopSidebarExpanded("client", true)).toBe(true);
  });

  it("stays collapsed while the authenticated session is hydrating", () => {
    expect(isDesktopSidebarExpanded(undefined, true)).toBe(false);
    expect(isDesktopSidebarExpanded(null, null)).toBe(false);
  });

  it("remembers the choice for operational roles only", () => {
    storeSidebarPreference("telecaller", false);
    expect(storage.setItem).toHaveBeenCalledWith(SIDEBAR_PREFERENCE_KEY, "false");
    expect(readStoredSidebarPreference("telecaller")).toBe(false);
    expect(readStoredSidebarPreference("client")).toBeNull();

    storage.setItem.mockClear();
    storeSidebarPreference("client", true);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("falls back to the role default when storage throws", () => {
    storage.getItem.mockImplementation(() => {
      throw new Error("blocked");
    });
    storage.setItem.mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => storeSidebarPreference("admin", false)).not.toThrow();
    expect(readStoredSidebarPreference("admin")).toBeNull();
  });
});
