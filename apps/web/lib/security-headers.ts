export type SecurityHeader = { key: string; value: string };

type SecurityHeaderOptions = {
  production: boolean;
  strictPublicConfig?: boolean;
  apiBaseUrl?: string;
  assetHost?: string;
};

function trustedOrigin(
  label: string,
  value: string | undefined,
  production: boolean,
  strictPublicConfig: boolean,
): string | null {
  const candidate = value?.trim();
  if (!candidate) return null;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error(`${label} must be a valid absolute HTTP URL.`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`${label} must be a valid absolute HTTP URL.`);
  }

  const loopback = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
  if (production && parsed.protocol !== "https:" && (strictPublicConfig || !loopback)) {
    throw new Error(`${label} must use HTTPS outside local development.`);
  }
  return parsed.origin;
}

export const YOUTUBE_EMBED_ORIGIN = "https://www.youtube-nocookie.com";
export const YOUTUBE_THUMBNAIL_ORIGIN = "https://i.ytimg.com";

export function buildSecurityHeaders({
  production,
  strictPublicConfig = false,
  apiBaseUrl,
  assetHost,
}: SecurityHeaderOptions): SecurityHeader[] {
  const apiOrigin = trustedOrigin(
    "NEXT_PUBLIC_API_BASE_URL",
    apiBaseUrl,
    production,
    strictPublicConfig,
  );
  const assetOrigin = trustedOrigin(
    "NEXT_PUBLIC_ASSET_HOST",
    assetHost,
    production,
    strictPublicConfig,
  );
  // Signed multipart uploads go directly to the configured object-storage
  // origin. img-src alone does not permit fetch; keep this an exact origin,
  // never a wildcard or an origin taken from an individual API response.
  const connectSources = ["'self'", apiOrigin, assetOrigin, ...(production ? [] : ["http://localhost:9000", "ws:", "wss:"])].filter(
    (source): source is string => Boolean(source),
  );
  // Public banner videos may embed YouTube, but only through the privacy-
  // enhanced host and only as a click-to-play facade whose poster comes from
  // YouTube's thumbnail CDN (components/banner-video.tsx). Exact hosts only.
  const imageSources = ["'self'", "data:", "blob:", assetOrigin, YOUTUBE_THUMBNAIL_ORIGIN].filter(
    (source): source is string => Boolean(source),
  );
  const scriptSources = [
    "'self'",
    "'unsafe-inline'",
    ...(production ? [] : ["'unsafe-eval'"]),
  ];

  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    `frame-src ${YOUTUBE_EMBED_ORIGIN}`,
    "object-src 'none'",
    `script-src ${scriptSources.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src ${imageSources.join(" ")}`,
    "font-src 'self' data:",
    `connect-src ${connectSources.join(" ")}`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    // Approved private loan videos use short-lived URLs on the same trusted
    // storage origin as uploads. Authorization remains at the signed URL/API.
    `media-src ${["'self'", assetOrigin].filter(Boolean).join(" ")}`,
    ...(production ? ["upgrade-insecure-requests"] : []),
  ];

  const headers: SecurityHeader[] = [
    { key: "Content-Security-Policy", value: directives.join("; ") },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
    },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    { key: "Origin-Agent-Cluster", value: "?1" },
  ];

  if (production) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000",
    });
  }
  return headers;
}
