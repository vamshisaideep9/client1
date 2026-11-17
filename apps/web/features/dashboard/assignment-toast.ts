import type { UserRole } from "@/lib/auth";
import type { AppNotification, NotificationType } from "@/lib/notifications";

type AssignmentRule = {
  type: NotificationType;
  href: string;
  noun: [singular: string, plural: string];
};

// Roles that receive work by automatic or manual assignment.
const ASSIGNMENT_RULES: Partial<Record<UserRole, AssignmentRule>> = {
  telecaller: { type: "lead_assigned", href: "/dashboard/leads", noun: ["lead", "leads"] },
  employee: { type: "task_assigned", href: "/dashboard/tasks", noun: ["task", "tasks"] },
};

export const SEEN_ASSIGNMENTS_KEY = "dashboard.assignments.seen";

export function assignmentRuleFor(role: UserRole | null | undefined): AssignmentRule | null {
  return role ? (ASSIGNMENT_RULES[role] ?? null) : null;
}

export type AssignmentToast = {
  ids: string[];
  message: string;
  href: string;
};

/**
 * Unread assignment notifications the viewer has not been told about in this
 * tab yet. Seen ids, not a flag, so a different account in the same tab still
 * gets its own toast.
 */
export function pendingAssignmentToast(
  role: UserRole | null | undefined,
  items: AppNotification[],
  seen: ReadonlySet<string>,
): AssignmentToast | null {
  const rule = assignmentRuleFor(role);
  if (!rule) return null;
  const ids = items
    .filter((item) => item.type === rule.type && item.readAt === null && !seen.has(item.id))
    .map((item) => item.id);
  if (ids.length === 0) return null;
  const noun = ids.length === 1 ? rule.noun[0] : rule.noun[1];
  const verb = ids.length === 1 ? "has" : "have";
  return {
    ids,
    message: `${ids.length} new ${noun} ${verb} been assigned to you`,
    href: rule.href,
  };
}

export function readSeenAssignments(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(SEEN_ASSIGNMENTS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

export function storeSeenAssignments(seen: ReadonlySet<string>): void {
  try {
    // Bounded: the feed itself is capped at 100 rows.
    const ids = Array.from(seen).slice(-200);
    window.sessionStorage.setItem(SEEN_ASSIGNMENTS_KEY, JSON.stringify(ids));
  } catch {
    // Without storage the toast may repeat on reload; nothing else breaks.
  }
}
