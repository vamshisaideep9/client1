// Which Settings sections each role sees (CS-021). The API enforces the same
// rule: PATCH and DELETE /auth/me return 403 for the Admin-managed roles, and
// the personalization preference endpoints are Client-only. This only decides
// what to render.

/** Telecaller, Employee and Sub Admin (team managers are Sub Admins). */
export const ADMIN_MANAGED_ROLES: ReadonlySet<string> = new Set(["telecaller", "employee", "sub_admin"]);

export type SettingsSections = {
  /** Name and email can be edited and saved. */
  profileEditable: boolean;
  /** The "Personalized dashboard" consent card. */
  personalization: boolean;
  /** The Danger zone with Delete account. */
  deleteAccount: boolean;
};

export function settingsForRole(role: string | null | undefined): SettingsSections {
  const adminManaged = role ? ADMIN_MANAGED_ROLES.has(role) : false;
  return {
    profileEditable: !adminManaged,
    personalization: role === "client",
    deleteAccount: !adminManaged,
  };
}
