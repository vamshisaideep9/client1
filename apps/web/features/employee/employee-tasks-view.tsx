"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, ClipboardList, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import { optionsFromLabels } from "@/features/dashboard/filter-options";
import { ListPagination, useListPagination } from "@/features/dashboard/list-pagination";
import { FetchError } from "@/features/dashboard/fetch-error";
import { useLine } from "@/features/dashboard/line-provider";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import { leadSignalFilterGroups } from "@/features/telecaller/lead-signal-filter-fields";
import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  formatReferrer,
  leadSignalActiveCount,
  leadSignalChips,
  leadSignalFiltersActive,
  leadSignalOptions,
  lineScope,
  scopedLeadSignalFilters,
  type LeadSignalFilters,
} from "@/features/telecaller/lead-signal-filters";
import { DISPOSITION_LABEL } from "@/features/telecaller/telecaller-lead-status";
import { cn } from "@/lib/utils";

import { employeeSignalValues, filterTasksByLeadSignals } from "./employee-task-filters";
import { useEmployeeTasks } from "./use-employee-tasks";
import { StaffCounterpart } from "@/features/dashboard/staff-counterpart";

const STATUS_STYLE: Record<string, string> = {
  assigned: "bg-brand-cta-tint text-brand-link",
  in_progress: "bg-warning/10 text-warning",
  completed: "bg-success/10 text-success",
  cancelled: "bg-muted text-text-secondary",
  blocked: "bg-muted text-text-secondary",
};

const STATUS_LABEL: Record<string, string> = {
  assigned: "Assigned",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
  blocked: "Blocked",
};

const TYPE_LABEL: Record<string, string> = {
  document_collection: "Document collection",
  property_visit: "Property visit",
  background_check: "Background check",
};

const STATUS_OPTIONS = optionsFromLabels(STATUS_LABEL);
const TYPE_OPTIONS = optionsFromLabels(TYPE_LABEL);

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "-"
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

// The employee's assigned-task list. Row click opens the task detail page,
// where status is transitioned and (for background checks) an outcome recorded.
export function EmployeeTasksView() {
  const router = useRouter();
  const [statusFilter, setStatusFilter] = React.useState<string>("all");
  const [typeFilter, setTypeFilter] = React.useState<string>("all");
  const { activeLine } = useLine();
  const [signalFilters, setSignalFilters] = React.useState<LeadSignalFilters>(DEFAULT_LEAD_SIGNAL_FILTERS);
  const { items, loading, error, reload } = useEmployeeTasks(
    statusFilter === "all" ? undefined : statusFilter,
    typeFilter === "all" ? undefined : typeFilter,
  );
  // Loan filters on Loans, property filters on Real Estate; Employees have no
  // transaction data. Options: the active catalogue plus the loaded tasks' leads.
  const scope = React.useMemo(() => lineScope(activeLine), [activeLine]);
  const catalogue = useProductCatalogue(activeLine === "loans");
  const options = React.useMemo(
    () => leadSignalOptions(catalogue, items.map(employeeSignalValues)),
    [catalogue, items],
  );
  // A control of the other line never keeps narrowing the list.
  const effective = React.useMemo(() => scopedLeadSignalFilters(signalFilters, scope), [signalFilters, scope]);
  const filtered = React.useMemo(() => filterTasksByLeadSignals(items, effective), [items, effective]);
  const { page, pageItems, setPage } = useListPagination(filtered);
  const signalFiltersOn = leadSignalFiltersActive(effective);
  const patchSignals = (patch: Partial<LeadSignalFilters>) => setSignalFilters((f) => ({ ...f, ...patch }));

  React.useEffect(() => {
    setPage(0);
  }, [statusFilter, typeFilter, effective, setPage]);

  return (
    <DashboardPage>
      <DashboardHeader
        title="Tasks"
        description="Field and background-check tasks assigned to you."
      />

      <FilterBar
        value={{ ...EMPTY_FILTERS, status: statusFilter, kind: typeFilter }}
        onChange={(next) => {
          setStatusFilter(next.status);
          setTypeFilter(next.kind);
        }}
        searchLabel="Search tasks"
        showSearch={false}
        showLine={false}
        showDates={false}
        statusOptions={STATUS_OPTIONS}
        kindOptions={TYPE_OPTIONS}
        kindLabel="Task type"
        more={leadSignalFilterGroups({ filters: signalFilters, scope, options, onChange: patchSignals })}
        moreActiveCount={leadSignalActiveCount(signalFilters, scope)}
        onClearMore={() => setSignalFilters(DEFAULT_LEAD_SIGNAL_FILTERS)}
        chips={leadSignalChips(signalFilters, patchSignals, scope, options)}
        onClear={() => {
          setStatusFilter("all");
          setTypeFilter("all");
          setSignalFilters(DEFAULT_LEAD_SIGNAL_FILTERS);
        }}
      />

      {loading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : error ? (
        <FetchError status={null} message={error} onRetry={() => void reload()} />
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
            <ClipboardList className="h-6 w-6" aria-hidden="true" />
          </span>
          <h2 className="mt-5 text-lg font-semibold text-text-primary">No tasks assigned yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
            Tasks assigned to you by Admin will show up here.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
            <ClipboardList className="h-6 w-6" aria-hidden="true" />
          </span>
          <h2 className="mt-5 text-lg font-semibold text-text-primary">No tasks match your filters</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">Loosen a filter to see more tasks.</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => setSignalFilters(DEFAULT_LEAD_SIGNAL_FILTERS)}
          >
            <X className="h-4 w-4" aria-hidden="true" />
            Clear lead filters
          </Button>
        </div>
      ) : (
        <DashboardPanel
          title="Assigned tasks"
          description={signalFiltersOn ? `${filtered.length} of ${items.length} tasks` : `${items.length} tasks`}
        >
          <div className="animate-in fade-in-0 overflow-x-auto duration-200 motion-reduce:animate-none">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-text-secondary">
                <tr>
                  <th className="px-5 py-3 font-medium">Lead</th>
                  <th className="px-5 py-3 font-medium">Type</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Due</th>
                  {/* Trailing affordance column — no header label. */}
                  <th className="w-10 px-3 py-3">
                    <span className="sr-only">Open task</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((task) => (
                  <tr
                    key={task.id}
                    role="link"
                    tabIndex={0}
                    onClick={() => router.push(`/dashboard/tasks/${task.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") router.push(`/dashboard/tasks/${task.id}`);
                    }}
                    className="group cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <td className="px-5 py-4">
                      <p className="font-medium text-text-primary transition-colors group-hover:text-brand-link">
                        {task.lead_name ?? "Assigned lead"}
                      </p>
                      <p className="text-xs text-text-secondary">
                        {task.lead_mobile ??
                          (task.lead_contact_mode === "share_link"
                            ? "Contact via secure invitation"
                            : "Contact details hidden")}
                      </p>
                      <StaffCounterpart label="Telecaller" name={task.raised_by_telecaller_name} code={task.raised_by_telecaller_code} />
                      {task.lead_last_disposition ? (
                        <p className="mt-1 text-xs text-text-secondary">
                          Last call: {DISPOSITION_LABEL[task.lead_last_disposition] ?? task.lead_last_disposition}
                        </p>
                      ) : null}
                      {task.lead_referrer ? (
                        <p className="mt-1 text-xs text-text-secondary">
                          Referred by{" "}
                          <span className="font-medium text-text-primary">{formatReferrer(task.lead_referrer)}</span>
                        </p>
                      ) : null}
                    </td>
                    <td className="px-5 py-4 text-text-secondary">
                      {TYPE_LABEL[task.task_type] ?? task.task_type}
                    </td>
                    <td className="px-5 py-4">
                      <span
                        className={cn(
                          "inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium",
                          STATUS_STYLE[task.status] ?? "bg-muted text-text-secondary",
                        )}
                      >
                        {STATUS_LABEL[task.status] ?? task.status}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-text-secondary">{formatDateTime(task.due_at)}</td>
                    <td className="px-3 py-4">
                      <ChevronRight
                        className="h-4 w-4 text-text-secondary/60 transition-[color,transform] group-hover:translate-x-0.5 group-hover:text-brand-link motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
                        aria-hidden="true"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ListPagination page={page} total={filtered.length} onPageChange={setPage} label="Assigned tasks pages" />
        </DashboardPanel>
      )}
    </DashboardPage>
  );
}
