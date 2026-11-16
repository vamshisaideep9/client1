// One rule for every banner call to action: the public mapper, the hero
// carousel and sponsor strip, the dashboard banner card, the CMS previews and
// the authoring forms all resolve a CTA here, so what an author can save is
// exactly what a visitor gets.
//
// A destination is either a same-site path (rendered with next/link) or a
// strict external https link (rendered as a new-tab anchor). The API enforces
// the same rule on write (apps/api/app/core/urls.py); this re-check covers rows
// written before that validation existed and keeps the browser fail-closed.

import { isSafeLocalHref } from "@/lib/safe-local-href";

export type BannerCta = { href: string; label: string; external: boolean };

export const YOUTUBE_CTA_LABEL = "Watch on YouTube";

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
// Whitespace, C0 controls and DEL. URL parsing silently strips some of these,
// which would make the href differ from what the author saw.
const UNSAFE_CHARACTERS = /[\s\u0000-\u001f\u007f]/;
const HTTPS_AUTHORITY = /^https:\/\/([^/?#]*)/i;

/** An https URL with a host, no userinfo, no backslash and a valid port. */
export function isSafeExternalHref(value: string): boolean {
  if (!value || UNSAFE_CHARACTERS.test(value) || value.includes("\\")) return false;
  const authority = HTTPS_AUTHORITY.exec(value)?.[1];
  // "@" anywhere in the authority is userinfo, even when empty ("https://@host").
  if (!authority || authority.includes("@")) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname !== "" && !url.username && !url.password;
  } catch {
    return false;
  }
}

/** True for a value the API accepts as a banner button destination. */
export function isSafeBannerHref(value: string): boolean {
  return isSafeLocalHref(value) || isSafeExternalHref(value);
}

export const BANNER_DESTINATION_ERROR = "Use a page path like /loans or a full https:// link.";

export function youtubeWatchUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

/**
 * The button a banner renders, or null for none.
 *
 * - An authored destination needs a label too; an unsafe destination renders
 *   no button rather than being trusted.
 * - With no destination, an attached YouTube video becomes the destination
 *   and the label defaults to "Watch on YouTube".
 */
export function resolveBannerCta({
  deepLink,
  ctaLabel,
  youtubeVideoId,
}: {
  deepLink?: string | null;
  ctaLabel?: string | null;
  youtubeVideoId?: string | null;
}): BannerCta | null {
  const label = ctaLabel?.trim() ?? "";
  const link = deepLink ?? "";
  if (link.trim()) {
    if (!label) return null;
    if (isSafeLocalHref(link)) return { href: link, label, external: false };
    if (isSafeExternalHref(link)) return { href: link, label, external: true };
    return null;
  }
  if (youtubeVideoId && YOUTUBE_ID.test(youtubeVideoId)) {
    return { href: youtubeWatchUrl(youtubeVideoId), label: label || YOUTUBE_CTA_LABEL, external: true };
  }
  return null;
}

const YOUTUBE_WATCH_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
]);
const YOUTUBE_SHORT_HOSTS = new Set(["youtu.be", "www.youtu.be"]);
const YOUTUBE_PATH_PREFIXES = ["/embed/", "/shorts/", "/live/", "/v/"];

/**
 * The video id in a pasted YouTube link, for authoring previews only. Mirrors
 * apps/api/app/core/youtube.py; the API's own parse stays authoritative.
 */
export function youtubeIdFromLink(value: string): string | null {
  let candidate = value.trim();
  if (YOUTUBE_ID.test(candidate)) return candidate;
  if (!candidate || candidate.length > 300) return null;
  if (!candidate.includes("://")) candidate = `https://${candidate}`;
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return null;
  }
  if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password) {
    return null;
  }
  const host = url.hostname.toLowerCase();
  let id: string | null = null;
  if (YOUTUBE_SHORT_HOSTS.has(host)) {
    id = url.pathname.replace(/^\/+|\/+$/g, "").split("/")[0] ?? null;
  } else if (YOUTUBE_WATCH_HOSTS.has(host)) {
    if (url.pathname === "/watch") id = url.searchParams.get("v");
    else {
      const prefix = YOUTUBE_PATH_PREFIXES.find((item) => url.pathname.startsWith(item));
      if (prefix) id = url.pathname.slice(prefix.length).split("/")[0] ?? null;
    }
  }
  return id && YOUTUBE_ID.test(id) ? id : null;
}
