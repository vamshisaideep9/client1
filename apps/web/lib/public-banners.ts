// Server-only client for the three public campaign placements
// (GET /api/v1/public/banners). Same division of labor as
// lib/public-properties.ts: this module returns the display HeroBanner shape
// and goes through the server-only serverFetchJson, so it must never be
// imported by a Client Component.

import type { components } from "@contracts/generated/schema";

import { isAllowedAssetUrl } from "@/lib/allowed-asset-url";
import { serverFetchJson } from "@/lib/api/server";
import { resolveBannerCta } from "@/lib/banner-cta";
import type { HeroBanner } from "@/lib/banners";
import { PUBLIC_BANNERS_TAG } from "@/lib/public-banners-cache";

type Schemas = components["schemas"];

// A single leading "/" not followed by another "/" or a backslash. Plain
// startsWith("/") is not enough: "//evil.com" also starts with "/" but
// browsers (and next/link, which treats a "//"-prefixed href as non-local and
// renders a plain anchor) resolve it as protocol-relative to an off-site
// origin, and "/\evil.com" normalizes the same way under WHATWG URL parsing.
// Both would otherwise sail through a naive same-origin check.
// Mirrors next.config.ts's remotePatterns allowlist -- a host outside it
// makes next/image throw at RENDER time (not a graceful broken-image icon),
// which would take the whole homepage down. This guard is what stops that:
// image_url is server-computed and should already be one of these two
// hosts, but "should" isn't a load-bearing guarantee for an origin crash, so
// it's re-checked here rather than trusted blindly.
export { isAllowedAssetUrl } from "@/lib/allowed-asset-url";

export function mapPublicBanner(raw: Schemas["PublicBannerRead"]): HeroBanner {
  // Re-checked like image_url: an id that is not exactly 11 safe characters is
  // dropped, both as the embed and as the default CTA destination.
  const youtubeId =
    raw.youtube_video_id && /^[A-Za-z0-9_-]{11}$/.test(raw.youtube_video_id)
      ? raw.youtube_video_id
      : undefined;
  return {
    id: raw.id,
    title: raw.title,
    subtitle: raw.subtitle ?? undefined,
    // The component's cream-placeholder branch handles undefined -- kept
    // for a banner with no image, or one whose image_url somehow isn't on
    // an allowed host (shouldn't happen post write-validator; see the guard
    // above and services/storage.py::public_asset_url).
    image: raw.image_url && isAllowedAssetUrl(raw.image_url) ? raw.image_url : undefined,
    reraVerified: raw.rera_verified || undefined,
    youtubeId,
    // A video URL off the asset allowlist is dropped.
    videoUrl: raw.video_url && isAllowedAssetUrl(raw.video_url) ? raw.video_url : undefined,
    // deep_link is CMS copy that becomes an href. lib/banner-cta.ts accepts a
    // same-origin path (next/link) or a strict https link (new-tab anchor)
    // and drops anything else -- protocol-relative, backslash, http:,
    // javascript: or credential-bearing -- rather than trusting it. With no
    // destination, an attached YouTube video becomes the destination. Without
    // a button the title/subtitle still render.
    cta: resolveBannerCta({
      deepLink: raw.deep_link,
      ctaLabel: raw.cta_label,
      youtubeVideoId: youtubeId,
    }) ?? undefined,
  };
}

// Never throws, never rejects, same contract as getPublicListings(): the
// homepage must keep rendering when the fetch fails or the table is simply
// empty. The hero caller (app/(public)/page.tsx) falls back to
// FALLBACK_HERO_BANNERS on an empty array; the ad strip deliberately does not,
// because an empty ad slot must vanish rather than show placeholder inventory.
// The two failure shapes are not distinguished here, since a visitor cannot
// act on the difference.
//
// Derived from the generated contract rather than hand-written, so it cannot
// drift from the router's Literal. "dashboard" is excluded for the same reason
// the API excludes it: that placement carries authenticated, audience-targeted
// content and is not anonymously reachable.
export type PublicBannerPlacement = Exclude<Schemas["BannerPlacement"], "dashboard">;

export async function getHeroBanners(
  placement: PublicBannerPlacement = "homepage",
): Promise<HeroBanner[]> {
  const res = await serverFetchJson<Schemas["PublicBannerListResponse"]>(
    `/api/v1/public/banners?placement=${encodeURIComponent(placement)}`,
    // Tagged so an Admin approval or removal clears it at once (see
    // app/actions/revalidate-public-banners.ts); 60 s remains the fallback
    // for scheduler-driven changes.
    { revalidate: 60, tags: [PUBLIC_BANNERS_TAG] },
  );
  if (!res.ok) return [];
  return res.data.banners.map(mapPublicBanner);
}
