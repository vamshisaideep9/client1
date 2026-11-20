// Which Settings sections each role sees (CS-021, CS-025). The API enforces
// the same rules: PATCH and DELETE /auth/me return 403 for the Admin-managed
// roles, the personalization preference endpoints are Client-only, the
// self-service phone/email change refuses Admin-managed roles and the staff
// contact-change request refuses everyone else. This only decides what to
// render.

/** Telecaller, Employee and Sub Admin (team managers are Sub Admins). */
export const ADMIN_MANAGED_ROLES: ReadonlySet<string> = new Set(["telecaller", "employee", "sub_admin"]);

export type SettingsSections = {
  /** Name and optional profile details can be edited and saved. */
  profileEditable: boolean;
  /** The "Personalized dashboard" consent card. */
  personalization: boolean;
  /** The Danger zone with Delete account. */
  deleteAccount: boolean;
  /**
   * How phone and email change: `self` (password, a code to the current and
   * the new value) or `request` (an Admin approves).
   */
  contactChange: "self" | "request";
};

export function settingsForRole(role: string | null | undefined): SettingsSections {
  const adminManaged = role ? ADMIN_MANAGED_ROLES.has(role) : false;
  return {
    profileEditable: !adminManaged,
    personalization: role === "client",
    deleteAccount: !adminManaged,
    contactChange: adminManaged ? "request" : "self",
  };
}
