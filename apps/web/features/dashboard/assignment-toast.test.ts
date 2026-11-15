import { describe, expect, it } from "vitest";

import type { AppNotification, NotificationType } from "@/lib/notifications";

import { pendingAssignmentToast } from "./assignment-toast";

function note(id: string, type: NotificationType, readAt: string | null = null): AppNotification {
  return {
    id,
    type,
    title: "New lead assigned",
    body: "",
    href: null,
    readAt,
    createdAt: "2026-11-13T10:00:00Z",
  };
}

describe("assignment toast", () => {
  const items = [
    note("a", "lead_assigned"),
    note("b", "lead_assigned"),
    note("c", "lead_assigned"),
    note("d", "lead_assigned"),
    note("e", "lead_assigned", "2026-11-13T11:00:00Z"),
    note("f", "task_assigned"),
  ];

  it("counts unread lead assignments for a Telecaller", () => {
    expect(pendingAssignmentToast("telecaller", items, new Set())).toEqual({
      ids: ["a", "b", "c", "d"],
      message: "4 new leads have been assigned to you",
      href: "/dashboard/leads",
    });
  });

  it("counts task assignments for an Employee, singular wording", () => {
    expect(pendingAssignmentToast("employee", items, new Set())).toEqual({
      ids: ["f"],
      message: "1 new task has been assigned to you",
      href: "/dashboard/tasks",
    });
  });

  it("only reports assignments not already announced in this tab", () => {
    expect(pendingAssignmentToast("telecaller", items, new Set(["a", "b", "c"]))?.message).toBe(
      "1 new lead has been assigned to you",
    );
    expect(pendingAssignmentToast("telecaller", items, new Set(["a", "b", "c", "d"]))).toBeNull();
  });

  it("stays silent for roles that are not assigned work", () => {
    for (const role of ["client", "agent", "admin", "sub_admin", null] as const) {
      expect(pendingAssignmentToast(role, items, new Set())).toBeNull();
    }
  });
});
