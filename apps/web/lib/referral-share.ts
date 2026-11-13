// Referral code helpers shared by the client referral card (share links) and
// the register form (client-side format check, matching normalize before
// the same regex is applied server-side in core/security.py).
//
// URL builders are frontend-only by design (docs/specs/referral-program.md
// D14): the API returns just the bare code, never a share_url — there is no
// PUBLIC_WEB_URL setting, and a misconfigured one would produce broken links
// already sent over WhatsApp. window.location.origin can't be wrong, so
// callers always pass it in.

// Same alphabet as core/security.py's Crockford base32 (no I/L/O/U).
const REFERRAL_CODE_RE = /^[0-9A-HJKMNP-TV-Z]{8}$/;
// Crockford's own reading aliases, mirroring normalize_referral_code: a
// human transcribing a code types O for 0, I/L for 1.
const ALIASES: Record<string, string> = { O: "0", I: "1", L: "1" };

/** Strip/uppercase/alias a user-entered referral code, same rules as the backend. */
export function normalizeReferralCode(raw: string): string {
  return raw
    .trim()
    .toUpperCase()
    .replace(/[OIL]/g, (c) => ALIASES[c]);
}

export function isValidReferralCodeFormat(normalized: string): boolean {
  return REFERRAL_CODE_RE.test(normalized);
}

/** e.g. ("https://brolly.example", "AB12CD34") -> "https://brolly.example/register?ref=AB12CD34". */
export function buildRegisterUrl(origin: string, code: string): string {
  return `${origin.replace(/\/$/, "")}/register?ref=${encodeURIComponent(code)}`;
}

/**
 * A wa.me share link with no destination number — opens WhatsApp's own
 * contact picker/share sheet with the message pre-filled, same as the
 * "Share on WhatsApp" pattern (distinct from toWaHref elsewhere, which opens
 * a chat with a specific lead's number).
 */
export function buildWaMeUrl(origin: string, code: string): string {
  const registerUrl = buildRegisterUrl(origin, code);
  const message = `Explore loans and real estate with Dhanadhara. Use my referral code ${code} when you sign up: ${registerUrl}`;
  return `https://wa.me/?text=${encodeURIComponent(message)}`;
}

// ---------------------------------------------------------------------------
// Referral-aware sharing for public loan and property links.
//
// Public pages do not mount AuthProvider (no token on marketing routes), so the
// signed-in client's OWN code is cached by AuthProvider after login and read
// here. The code is not a secret (its whole purpose is to be shared), but it is
// only used while the non-authoritative session hint is present and is removed
// on logout, so a shared device does not keep sharing a previous user's code.
// Attribution itself stays server-side (services/referrals.attribute_signup).
// ---------------------------------------------------------------------------

export const OWN_REFERRAL_CODE_KEY = "referral.own_code";
export const INCOMING_REFERRAL_CODE_KEY = "referral.incoming_code";
// Mirrors SESSION_HINT_KEY in components/auth/session-provider.tsx.
const SESSION_HINT_KEY = "auth.session_hint";

function safeLocal(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

function safeSession(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/** Cache (or clear, with null) the signed-in client's own referral code. */
export function rememberOwnReferralCode(code: string | null): void {
  const storage = safeLocal();
  if (!storage) return;
  try {
    const normalized = code ? normalizeReferralCode(code) : "";
    if (normalized && isValidReferralCodeFormat(normalized)) {
      storage.setItem(OWN_REFERRAL_CODE_KEY, normalized);
    } else {
      storage.removeItem(OWN_REFERRAL_CODE_KEY);
    }
  } catch {
    /* storage full or blocked: sharing simply falls back to a plain link */
  }
}

/** The viewer's own code, only while a session hint says they are signed in. */
export function readOwnReferralCode(): string | null {
  const storage = safeLocal();
  if (!storage) return null;
  try {
    if (storage.getItem(SESSION_HINT_KEY) !== "1") return null;
    const code = storage.getItem(OWN_REFERRAL_CODE_KEY);
    return code && isValidReferralCodeFormat(code) ? code : null;
  } catch {
    return null;
  }
}

/** Append ?ref=CODE to a URL, replacing any existing ref parameter. */
export function withReferral(url: string, code: string | null): string {
  if (!code) return url;
  const parsed = new URL(url, "http://placeholder.invalid");
  parsed.searchParams.set("ref", code);
  return url.startsWith("http") ? parsed.toString() : `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

/**
 * Remember a referral code that arrived on a shared public link (?ref=CODE) for
 * the rest of the browser session, so the visitor can browse before signing up.
 * Only a format-valid code is kept; the server still decides whether it matches.
 */
export function captureIncomingReferral(search: string): void {
  const raw = new URLSearchParams(search).get("ref");
  if (!raw) return;
  const normalized = normalizeReferralCode(raw);
  if (!isValidReferralCodeFormat(normalized)) return;
  const storage = safeSession();
  try {
    storage?.setItem(INCOMING_REFERRAL_CODE_KEY, normalized);
  } catch {
    /* blocked storage: the ?ref= on /register still works directly */
  }
}

export function readIncomingReferral(): string | null {
  const storage = safeSession();
  try {
    const code = storage?.getItem(INCOMING_REFERRAL_CODE_KEY) ?? null;
    return code && isValidReferralCodeFormat(code) ? code : null;
  } catch {
    return null;
  }
}

/** Message used by the Refer action for a specific loan or property. */
export function buildReferMessage(title: string, url: string, code: string): string {
  return `Check out ${title} on Dhanadhara. Sign up with my referral code ${code}: ${url}`;
}
