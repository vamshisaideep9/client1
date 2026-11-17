"use server";

// Clears the cached public banner reads (homepage hero, sponsor strip,
// Financial Services and Properties sections) right after an Admin approves
// or removes a campaign, so the next visitor sees the change instead of
// waiting out the ISR window.
//
// A Server Action rather than a route handler: nginx sends every /api/* path
// to FastAPI, so a Next route under /api would never be reached. Server
// Actions are POSTs to the current page and carry Next's own Origin check.
//
// The caller is not trusted. The access token is checked by the API itself
// (GET /api/v1/auth/me: signature, expiry, revocation, active account), and
// only after the API accepts that exact token is its role claim read; only
// "admin" may revalidate. The API remains the boundary for the approval or
// removal itself; this action only clears a cache.

import { revalidateTag } from "next/cache";

import { serverApiUrl } from "@/lib/api/server";
import { PUBLIC_BANNERS_TAG } from "@/lib/public-banners-cache";

export type RevalidatePublicBannersResult =
  | { ok: true }
  | { ok: false; reason: "unauthorized" | "forbidden" | "unavailable" };

const MAX_TOKEN_LENGTH = 4096;
const VERIFY_TIMEOUT_MS = 5_000;

function verifiedRoleClaim(token: string): string | null {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const claims: unknown = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    if (claims && typeof claims === "object" && "role" in claims) {
      const { role } = claims as { role: unknown };
      return typeof role === "string" ? role : null;
    }
    return null;
  } catch {
    return null;
  }
}

export async function revalidatePublicBanners(
  accessToken: string,
): Promise<RevalidatePublicBannersResult> {
  if (
    typeof accessToken !== "string" ||
    accessToken.length === 0 ||
    accessToken.length > MAX_TOKEN_LENGTH ||
    accessToken.split(".").length !== 3
  ) {
    return { ok: false, reason: "unauthorized" };
  }

  let response: Response;
  try {
    response = await fetch(serverApiUrl("/api/v1/auth/me"), {
      method: "GET",
      headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(VERIFY_TIMEOUT_MS),
    });
  } catch {
    return { ok: false, reason: "unavailable" };
  }
  if (response.status === 401 || response.status === 403) {
    return { ok: false, reason: "unauthorized" };
  }
  if (!response.ok) return { ok: false, reason: "unavailable" };

  if (verifiedRoleClaim(accessToken) !== "admin") return { ok: false, reason: "forbidden" };

  revalidateTag(PUBLIC_BANNERS_TAG);
  return { ok: true };
}
