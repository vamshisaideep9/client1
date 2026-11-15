// Local mirror of the signed-in user's bookmarked property ids, so the public
// Home page (which renders outside AuthProvider and holds no access token) can
// suggest similar properties without an authenticated request.
//
// Only opaque property ids are stored: no titles, prices or personal data. The
// list is written by the dashboard's BookmarksProvider after the server answers,
// read only while the non-authoritative session hint is present, and removed on
// logout, so a shared device does not keep showing a previous user's taste.

export const BOOKMARK_IDS_KEY = "bookmarks.property_ids";
// Mirrors SESSION_HINT_KEY in components/auth/session-provider.tsx.
const SESSION_HINT_KEY = "auth.session_hint";
const MAX_IDS = 50;
const ID_RE = /^[0-9a-f-]{36}$/i;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** Replace (or clear, with null) the cached bookmarked property ids. */
export function rememberBookmarkedIds(ids: readonly string[] | null): void {
  const store = storage();
  if (!store) return;
  try {
    const clean = (ids ?? []).filter((id) => ID_RE.test(id)).slice(-MAX_IDS);
    if (clean.length === 0) store.removeItem(BOOKMARK_IDS_KEY);
    else store.setItem(BOOKMARK_IDS_KEY, JSON.stringify(clean));
  } catch {
    /* blocked or full storage: suggestions simply stay hidden */
  }
}

/** Cached ids, only while a session hint says someone is signed in. */
export function readBookmarkedIds(): string[] {
  const store = storage();
  if (!store) return [];
  try {
    if (store.getItem(SESSION_HINT_KEY) !== "1") return [];
    const parsed: unknown = JSON.parse(store.getItem(BOOKMARK_IDS_KEY) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string" && ID_RE.test(id)).slice(-MAX_IDS)
      : [];
  } catch {
    return [];
  }
}
