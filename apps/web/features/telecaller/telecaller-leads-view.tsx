"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, PhoneCall, X } from "lucide-react";

import { LeadRefText } from "@/features/dashboard/lead-ref";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { ResubmissionBadge } from "@/features/dashboard/resubmission-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import { ListPagination, useListPagination } from "@/features/dashboard/list-pagination";
import { FetchError } from "@/features/dashboard/fetch-error";
import { useLine } from "@/features/dashboard/line-provider";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import { formatMobile } from "@/lib/phone";
import { cn } from "@/lib/utils";

import { leadSignalFilterGroups } from "./lead-signal-filter-fields";
import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  formatReferrer,
  leadSignalActiveCount,
  leadSignalChips,
  leadSignalOptions,
  lineScope,
  rowsHiddenTransactionParts,
  scopedLeadSignalFilters,
  RESUBMISSION_OPTIONS,
  type ResubmissionFilter,
} from "./lead-signal-filters";
import {
  DEFAULT_TELECALLER_LEAD_FILTERS,
  DEFAULT_TELECALLER_LEAD_SORT,
  FOLLOW_UP_DUE_PARAM,
  filterTelecallerLeads,
  sortTelecallerLeads,
  telecallerLeadFiltersActive,
  telecallerSignalValues,
  type TelecallerLeadFilters,
  type TelecallerLeadSort,
  type TelecallerLeadSortKey,
} from "./telecaller-lead-filters";
import { DISPOSITION_LABEL, STATUS_LABEL, STATUS_STYLE, formatDateTime } from "./telecaller-lead-status";
import { REQUEST_KIND_LABEL, formatAppliedAt } from "./telecaller-requests";
import { useTelecallerLeads } from "./use-telecaller-leads";

const STATUS_FILTER_OPTIONS = (["new", "assigned", "working", "converted", "closed", "released"] as const).map(
  (value) => ({ value, label: STATUS_LABEL[value] }),
);

const COLUMNS: { key: TelecallerLeadSortKey; label: string }[] = [
  { key: "name", label: "Lead" },
  { key: "status", label: "Status" },
  { key: "last_disposition", label: "Last disposition" },
  { key: "next_follow_up_at", label: "Next follow-up" },
];

function SortableHeader({
  column,
  sort,
  onSort,
}: {
  column: { key: TelecallerLeadSortKey; label: string };
  sort: TelecallerLeadSort;
  onSort: (key: TelecallerLeadSortKey) => void;
}) {
  const active = sort.key === column.key;
  const Icon = active ? (sort.dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <th
      className="p-0 font-medium"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      {/* Full-cell button, not just the label — keeps the sort control's hit
          target at a comfortable size rather than the label text's own
          line-height. */}
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className="group flex w-full items-center gap-1.5 px-5 py-3 text-xs font-medium uppercase tracking-wide text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        {column.label}
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-colors",
            active ? "text-brand-link" : "text-text-secondary/70 group-hover:text-text-secondary",
          )}
          aria-hidden="true"
        />
      </button>
    </th>
  );
}

// The telecaller's assigned-lead list. Row click opens the lead detail page,
// where a call gets logged and status/requirement updated.
export function TelecallerLeadsView() {
  const router = useRouter();
  const { activeLine } = useLine();
  const { items, loading, error, reload } = useTelecallerLeads();
  const searchParams = useSearchParams();
  // "View all follow-ups" on the home page links here with ?followUp=due.
  const [filters, setFilters] = React.useState<TelecallerLeadFilters>(() => ({
    ...DEFAULT_TELECALLER_LEAD_FILTERS,
    followUpDue: searchParams.get("followUp") === FOLLOW_UP_DUE_PARAM,
  }));
  const [sort, setSort] = React.useState<TelecallerLeadSort>(DEFAULT_TELECALLER_LEAD_SORT);

  // Loan filters on Loans, property filters on Real Estate, transaction
  // filters on Loans minus the parts the Admin hides; options are the active
  // catalogue plus whatever the loaded leads carry.
  const signalValues = React.useMemo(() => items.map(telecallerSignalValues), [items]);
  const catalogue = useProductCatalogue(activeLine === "loans");
  const scope = React.useMemo(
    () => lineScope(activeLine, true, rowsHiddenTransactionParts(signalValues)),
    [activeLine, signalValues],
  );
  const options = React.useMemo(() => leadSignalOptions(catalogue, signalValues), [catalogue, signalValues]);
  // A hidden control (other line, Admin-hidden part) never keeps narrowing.
  const effective = React.useMemo(
    () => ({ ...filters, ...scopedLeadSignalFilters(filters, scope) }),
    [filters, scope],
  );

  const filtered = React.useMemo(() => filterTelecallerLeads(items, effective), [items, effective]);
  const sorted = React.useMemo(() => sortTelecallerLeads(filtered, sort), [filtered, sort]);
  const { page, pageItems, setPage } = useListPagination(sorted);

  React.useEffect(() => {
    setPage(0);
  }, [effective, sort, setPage]);

  const filtersActive = telecallerLeadFiltersActive(effective);

  function onSort(key: TelecallerLeadSortKey) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  // Keep the URL honest once the due-only filter is dropped.
  React.useEffect(() => {
    if (!filters.followUpDue && searchParams.get("followUp")) router.replace("/dashboard/leads", { scroll: false });
  }, [filters.followUpDue, searchParams, router]);

  function clearFilters() {
    setFilters(DEFAULT_TELECALLER_LEAD_FILTERS);
  }

  const chips = [
    ...(filters.followUpDue
      ? [{ id: "followUpDue", label: "Follow-up: due now", onRemove: () => patchFilters({ followUpDue: false }) }]
      : []),
    ...leadSignalChips(filters, patchFilters, scope, options),
  ];

  function patchFilters(patch: Partial<TelecallerLeadFilters>) {
    setFilters((f) => ({ ...f, ...patch }));
  }

  return (
    <DashboardPage>
      <DashboardHeader
        title="Leads"
        description="Leads assigned to you. Open one to log a call."
      />

      {loading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : error ? (
        <FetchError status={null} message={error} onRetry={() => void reload()} />
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
            <PhoneCall className="h-6 w-6" aria-hidden="true" />
          </span>
          <h2 className="mt-5 text-lg font-semibold text-text-primary">No leads assigned yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
            Leads assigned to you by Admin will show up here.
          </p>
        </div>
      ) : (
        <>
          <FilterBar
            value={{
              ...EMPTY_FILTERS,
              search: filters.search,
              status: filters.status,
              from: filters.followUpFrom,
              to: filters.followUpTo,
            }}
            onChange={(next) =>
              setFilters((f) => ({
                ...f,
                search: next.search,
                status: next.status,
                followUpFrom: next.from,
                followUpTo: next.to,
              }))
            }
            searchLabel="Search leads"
            searchPlaceholder="Name, mobile or lead ref"
            statusOptions={STATUS_FILTER_OPTIONS}
            showLine={false}
            extra={<FilterSelect label="Resubmission" value={filters.resubmission} options={RESUBMISSION_OPTIONS}
              onValueChange={(value) => patchFilters({ resubmission: value as ResubmissionFilter })} />}
            dateFromLabel="Follow-up from date"
            dateToLabel="Follow-up to date"
            more={leadSignalFilterGroups({ filters, scope, options, onChange: patchFilters })}
            moreActiveCount={leadSignalActiveCount(filters, scope)}
            onClearMore={() => patchFilters(DEFAULT_LEAD_SIGNAL_FILTERS)}
            chips={chips}
            onClear={clearFilters}
            hasExternalFilters={filtersActive}
          />

          {sorted.length === 0 ? (
            <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
                <PhoneCall className="h-6 w-6" aria-hidden="true" />
              </span>
              <h2 className="mt-5 text-lg font-semibold text-text-primary">No leads match your filters</h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
                Try a different search or loosen a filter.
              </p>
              {filtersActive ? (
                <Button variant="outline" size="sm" className="mt-4" onClick={clearFilters}>
                  <X className="h-4 w-4" aria-hidden="true" />
                  Clear filters
                </Button>
              ) : null}
            </div>
          ) : (
            <DashboardPanel
              title="Assigned leads"
              description={
                filtersActive ? `${sorted.length} of ${items.length} leads` : `${items.length} leads`
              }
            >
              <div className="animate-in fade-in-0 overflow-x-auto duration-200 motion-reduce:animate-none">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border text-text-secondary">
                    <tr>
                      {COLUMNS.map((column) => (
                        <SortableHeader key={column.key} column={column} sort={sort} onSort={onSort} />
                      ))}
                      {/* Trailing affordance column — no header label, just the
                          chevron every row ends in, so it isn't sortable. */}
                      <th className="w-10 px-3 py-3">
                        <span className="sr-only">Open lead</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((lead) => (
                      <tr
                        key={lead.id}
                        role="link"
                        tabIndex={0}
                        onClick={() => router.push(`/dashboard/leads/${lead.id}`)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") router.push(`/dashboard/leads/${lead.id}`);
                        }}
                        className="group cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        <td className="px-5 py-4">
                          <p className="font-medium text-text-primary transition-colors group-hover:text-brand-link">
                            {lead.name ?? "Unnamed lead"}
                          </p>
                          <p className="text-xs text-text-secondary">
                            {formatMobile(lead.mobile)}
                            {lead.lead_ref ? " · " : null}
                            <LeadRefText value={lead.lead_ref} />
                          </p>
                          <ResubmissionBadge count={lead.resubmit_count} at={lead.last_resubmitted_at} />
                          {lead.latest_request ? (
                            <p className="mt-1 text-xs text-text-secondary">
                              <span className="font-medium text-text-primary">
                                {lead.latest_request.title}
                              </span>
                              {" · "}
                              {REQUEST_KIND_LABEL[lead.latest_request.kind]}
                              {" · "}
                              <time dateTime={lead.latest_request.applied_at}>
                                {formatAppliedAt(lead.latest_request.applied_at)}
                              </time>
                            </p>
                          ) : null}
                          {lead.referrer ? (
                            <p className="mt-1 text-xs text-text-secondary">
                              Referred by <span className="font-medium text-text-primary">{formatReferrer(lead.referrer)}</span>
                            </p>
                          ) : null}
                        </td>
                        <td className="px-5 py-4">
                          <span
                            className={cn(
                              "inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium",
                              STATUS_STYLE[lead.status] ?? "bg-muted text-text-secondary",
                            )}
                          >
                            {STATUS_LABEL[lead.status] ?? lead.status}
                          </span>
                        </td>
                        <td className="px-5 py-4 text-text-secondary">
                          {lead.last_disposition ? DISPOSITION_LABEL[lead.last_disposition] : "Not called yet"}
                        </td>
                        <td className="px-5 py-4 text-text-secondary">{formatDateTime(lead.next_follow_up_at)}</td>
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
              <ListPagination
                page={page}
                total={sorted.length}
                onPageChange={setPage}
                label="Assigned leads pages"
              />
            </DashboardPanel>
          )}
        </>
      )}
    </DashboardPage>
  );
}
