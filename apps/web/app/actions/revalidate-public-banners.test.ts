import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { revalidateTag } = vi.hoisted(() => ({ revalidateTag: vi.fn() }));
vi.mock("next/cache", () => ({ revalidateTag }));

import { revalidatePublicBanners } from "./revalidate-public-banners";
import { PUBLIC_BANNERS_TAG } from "@/lib/public-banners-cache";

function token(claims: Record<string, unknown>): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode(claims)}.signature`;
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  revalidateTag.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("revalidatePublicBanners", () => {
  it("clears the public banner cache for a token the API accepts as an admin", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    const adminToken = token({ sub: "u1", role: "admin", platform_scope: "true" });

    await expect(revalidatePublicBanners(adminToken)).resolves.toEqual({ ok: true });

    expect(revalidateTag).toHaveBeenCalledWith(PUBLIC_BANNERS_TAG);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/v1\/auth\/me$/);
    expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${adminToken}`);
    expect(init?.cache).toBe("no-store");
  });

  it.each(["sub_admin", "client", "agent", "employee", "telecaller"])(
    "refuses a valid %s token",
    async (role) => {
      fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
      await expect(revalidatePublicBanners(token({ sub: "u1", role }))).resolves.toEqual({
        ok: false,
        reason: "forbidden",
      });
      expect(revalidateTag).not.toHaveBeenCalled();
    },
  );

  it("never trusts a role claim the API rejected", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(revalidatePublicBanners(token({ role: "admin" }))).resolves.toEqual({
      ok: false,
      reason: "unauthorized",
    });
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it("fails closed when the API cannot be reached or errors", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(revalidatePublicBanners(token({ role: "admin" }))).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 503 }));
    await expect(revalidatePublicBanners(token({ role: "admin" }))).resolves.toEqual({
      ok: false,
      reason: "unavailable",
    });
    expect(revalidateTag).not.toHaveBeenCalled();
  });

  it.each(["", "not-a-jwt", "a.b", "x".repeat(5000)])(
    "rejects a malformed token %# without calling the API",
    async (value) => {
      await expect(revalidatePublicBanners(value)).resolves.toEqual({
        ok: false,
        reason: "unauthorized",
      });
      expect(fetchMock).not.toHaveBeenCalled();
      expect(revalidateTag).not.toHaveBeenCalled();
    },
  );

  it("refuses an accepted token whose payload is unreadable", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    await expect(revalidatePublicBanners("aaa.%%%.sig")).resolves.toEqual({
      ok: false,
      reason: "forbidden",
    });
    expect(revalidateTag).not.toHaveBeenCalled();
  });
});
