import * as React from "react";

import type { AgentLeadStaff } from "@/lib/agent-api";
import { cn } from "@/lib/utils";

/** "Tara Caller · Telecaller · TC-0012", or the code alone when no name is on file. */
export function assignedStaffText(staff: AgentLeadStaff | null | undefined): string | null {
  if (!staff) return null;
  return [staff.name, staff.role_label, staff.staff_code].filter(Boolean).join(" · ");
}

/** A staff member working an Agent's lead: name, then role and staff code. Never contact details. */
export function AssignedStaff({
  staff,
  empty = "Not assigned yet",
  className,
}: {
  staff: AgentLeadStaff | null | undefined;
  empty?: string;
  className?: string;
}) {
  if (!staff) return <span className={cn("text-text-secondary", className)}>{empty}</span>;
  return (
    <span className={cn("inline-flex min-w-0 flex-col", className)}>
      <span className="break-words font-medium text-text-primary">{staff.name ?? staff.staff_code}</span>
      <span className="text-xs text-text-secondary">
        {staff.role_label} · <span className="tabular-nums">{staff.staff_code}</span>
      </span>
    </span>
  );
}
