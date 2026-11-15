import { matchesLeadSignals, type LeadSignalFilters } from "@/features/telecaller/lead-signal-filters";
import type { EmployeeTask } from "@/lib/employee-api";

/** Applies the lead loan/call/interest/referral filters to the Employee task list. */
export function filterTasksByLeadSignals(tasks: EmployeeTask[], filters: LeadSignalFilters): EmployeeTask[] {
  return tasks.filter((task) =>
    matchesLeadSignals(
      {
        loanStatuses: task.lead_loan_statuses,
        lastDisposition: task.lead_last_disposition,
        lastInterestLevel: task.lead_last_interest_level,
        referrer: task.lead_referrer,
      },
      filters,
    ),
  );
}
