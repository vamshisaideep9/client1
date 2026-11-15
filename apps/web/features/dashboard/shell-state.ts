import type { UserRole } from "@/lib/auth";

const OPERATIONAL_ROLES = new Set<UserRole>([
  "admin",
  "sub_admin",
  "agent",
  "telecaller",
  "employee",
]);

// Operational roles remember their own rail choice on this device. The Client
// keeps its approved behaviour: the rail starts collapsed every session.
export const SIDEBAR_PREFERENCE_KEY = "dashboard.sidebar.expanded";

export function isOperationalRole(role: UserRole | null | undefined): boolean {
  return role != null && OPERATIONAL_ROLES.has(role);
}

/** Desktop rail state before the viewer toggles it. */
export function defaultDesktopSidebarExpanded(role: UserRole | null | undefined): boolean {
  return isOperationalRole(role);
}

/**
 * Every role can collapse the desktop rail. `preference` is the viewer's
 * explicit choice for this session (or, for operational roles, this device);
 * `null` falls back to the role default. While the session hydrates the rail
 * stays collapsed so it never flashes open for a Client.
 */
export function isDesktopSidebarExpanded(
  role: UserRole | null | undefined,
  preference: boolean | null,
): boolean {
  if (role == null) return false;
  return preference ?? defaultDesktopSidebarExpanded(role);
}

export function readStoredSidebarPreference(
  role: UserRole | null | undefined,
): boolean | null {
  if (!isOperationalRole(role)) return null;
  try {
    const stored = window.localStorage.getItem(SIDEBAR_PREFERENCE_KEY);
    if (stored === "true") return true;
    if (stored === "false") return false;
  } catch {
    // Storage can be unavailable (private mode, blocked site data).
  }
  return null;
}

export function storeSidebarPreference(
  role: UserRole | null | undefined,
  expanded: boolean,
): void {
  if (!isOperationalRole(role)) return;
  try {
    window.localStorage.setItem(SIDEBAR_PREFERENCE_KEY, String(expanded));
  } catch {
    // A missing preference only means the role default applies next time.
  }
}
