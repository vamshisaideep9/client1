import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

describe("server API origin", () => {
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
});
