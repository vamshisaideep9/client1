"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/session-provider";

import {
  assignmentRuleFor,
  pendingAssignmentToast,
  readSeenAssignments,
  storeSeenAssignments,
} from "./assignment-toast";
import { useNotifications } from "./notifications-provider";

// Re-check for new assignments while a Telecaller or Employee works.
const REFRESH_MS = 2 * 60_000;

/**
 * "4 new leads have been assigned to you" for Telecallers (tasks for
 * Employees): once when they open the dashboard, then again whenever new
 * assignments arrive while the tab is open. Renders nothing.
 */
export function AssignmentToaster() {
  const { session } = useAuth();
  const role = session?.role;
  const enabled = assignmentRuleFor(role) !== null;
  const { items, feedStatus, refreshNotifications } = useNotifications();
  const router = useRouter();

  React.useEffect(() => {
    if (!enabled) return;
    void refreshNotifications();
    const refresh = () => {
      if (document.visibilityState === "visible") void refreshNotifications();
    };
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [enabled, refreshNotifications]);

  React.useEffect(() => {
    if (!enabled || feedStatus !== "ready") return;
    const seen = readSeenAssignments();
    const pending = pendingAssignmentToast(role, items, seen);
    if (!pending) return;
    for (const id of pending.ids) seen.add(id);
    storeSeenAssignments(seen);
    toast.info(pending.message, {
      id: "assignment-toast",
      duration: 8000,
      action: { label: "View", onClick: () => router.push(pending.href) },
    });
  }, [enabled, feedStatus, items, role, router]);

  return null;
}
