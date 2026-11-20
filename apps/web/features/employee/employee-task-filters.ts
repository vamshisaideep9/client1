import {
  matchesLeadSignals,
  type LeadSignalFilters,
  type LeadSignalValues,
} from "@/features/telecaller/lead-signal-filters";
import type { EmployeeTask } from "@/lib/employee-api";

/** The task's lead facts the shared lead-signal filters read (no transactions for Employees). */
export function employeeSignalValues(task: EmployeeTask): LeadSignalValues {
  return {
    loanStatuses: task.lead_loan_statuses,
    lastDisposition: task.lead_last_disposition,
    lastInterestLevel: task.lead_last_interest_level,
    referrer: task.lead_referrer,
    facets: task.lead_facets,
  };
}

/**
 * Applies the lead filters to the Employee task list. Pass filters already
 * narrowed to the list's scope (`scopedLeadSignalFilters`).
 */
export function filterTasksByLeadSignals(tasks: EmployeeTask[], filters: LeadSignalFilters): EmployeeTask[] {
  return tasks.filter((task) => matchesLeadSignals(employeeSignalValues(task), filters));
}
