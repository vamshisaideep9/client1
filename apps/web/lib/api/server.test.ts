import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("server API fetch", () => {
  it.each([
    ["development", undefined, "http://localhost:8000"],
    ["production", undefined, "http://api:8000"],
    ["development", "http://api:8000/", "http://api:8000"],
    ["production", "http://internal-api:8080", "http://internal-api:8080"],
  ])("uses the appropriate origin for %s with %s", async (environment, configured, origin) => {
    vi.stubEnv("NODE_ENV", environment!);
    vi.stubEnv("API_INTERNAL_URL", configured);
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] })));
    vi.stubGlobal("fetch", fetch);
    const { serverFetchJson } = await import("./server");
    await serverFetchJson("/api/v1/public/financial-products", { revalidate: 0 });
    expect(fetch).toHaveBeenCalledWith(`${origin}/api/v1/public/financial-products`, expect.any(Object));
  });

  it("preserves Next's dynamic-rendering signal instead of returning empty data", async () => {
    const error = Object.assign(new Error("Dynamic server usage"), { digest: "DYNAMIC_SERVER_USAGE" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
    const logger = vi.spyOn(console, "error").mockImplementation(() => {});
    const { serverFetchJson } = await import("./server");
    await expect(serverFetchJson("/api/v1/public/financial-products", { revalidate: 0 })).rejects.toBe(error);
    expect(logger).not.toHaveBeenCalled();
  });

  it("keeps real network failures as safe unavailable results", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { serverFetchJson } = await import("./server");
    expect(await serverFetchJson("/api/v1/public/banners", { revalidate: 60 })).toMatchObject({ ok: false, status: 0 });
  });
});
