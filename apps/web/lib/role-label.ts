const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  sub_admin: "Sub Admin",
  telecaller: "Telecaller",
  employee: "Officer",
  agent: "Agent",
  client: "Client",
};

export function roleLabel(role: string): string {
  return Object.hasOwn(ROLE_LABELS, role) ? ROLE_LABELS[role] : role.replaceAll("_", " ");
}
