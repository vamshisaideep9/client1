"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PhoneCall, SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ResubmissionBadge } from "@/features/dashboard/resubmission-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { ROW_ELIGIBILITY_OPTIONS } from "@/features/dashboard/eligibility";
import {
  EligibilitySummaryCards,
  NotAcceptedList,
  RowEligibilityBadge,
  notAcceptedTabLabel,
} from "@/features/dashboard/eligibility-ui";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import { compactChips, optionsFromLabels, selectFilterChip } from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { ListEmptyState } from "@/features/dashboard/list-states";
import { ListPagination, clampPaginationPage, paginateItems } from "@/features/dashboard/list-pagination";
import { FetchError } from "@/features/dashboard/fetch-error";
import { sortLeadsByDefaultOrder } from "@/features/dashboard/list-order";
import { useEligibility } from "@/features/dashboard/use-eligibility";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import { leadSignalFilterGroups } from "@/features/telecaller/lead-signal-filter-fields";
import {
  clearedLeadSignalFilters,
  leadSignalActiveCount,
  leadSignalChips,
  leadSignalOptions,
  RESUBMISSION_OPTIONS,
  type ResubmissionFilter,
} from "@/features/telecaller/lead-signal-filters";
import { getAgentLeadEligibility, listAgentLeadAttempts, resubmitAgentLead } from "@/lib/agent-api";
import { formatMobile } from "@/lib/phone";
import { cn } from "@/lib/utils";

import {
  AGENT_LEAD_STATUS_LABEL,
  DEFAULT_AGENT_LEAD_FILTERS,
  agentLeadScope,
  filterAgentLeads,
  type AgentLeadFilters,
} from "./agent-lead-filters";
import { useAgentLeads } from "./use-agent-leads";
import { AGENT_LEAD_EXPIRY_POLICY, formatAgentLeadExpiry } from "./lead-expiry";
import { ResubmitLeadButton } from "./resubmit-lead-button";

const STATUS_STYLE: Record<string, string> = {
  new: "bg-muted text-text-secondary",
  assigned: "bg-brand-cta-tint text-brand-link",
  working: "bg-warning/10 text-warning",
  converted: "bg-success/10 text-success",
  closed: "bg-muted text-text-secondary",
  released: "bg-muted text-text-secondary",
  expired: "bg-destructive/10 text-destructive",
};

const STATUS_OPTIONS = optionsFromLabels(AGENT_LEAD_STATUS_LABEL);
const NOUN = { one: "lead", many: "leads" };

// The agent's introduced-lead list. Row click opens the lead detail page,
// where the requirement can still be edited until a telecaller picks it up.
// CS-024 adds lead eligibility: a summary, an Eligibility filter and badge,
// and a "Not accepted" tab of introductions the platform turned away.
export function AgentLeadsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { items: loaded, loading, error, reload } = useAgentLeads();
  const eligibility = useEligibility(getAgentLeadEligibility, listAgentLeadAttempts);
  const [tab, setTab] = React.useState("leads");
  const [filters, setFilters] = React.useState<AgentLeadFilters>(DEFAULT_AGENT_LEAD_FILTERS);

  const scope = React.useMemo(() => agentLeadScope(loaded), [loaded]);
  const catalogue = useProductCatalogue(scope.loans);
  const options = React.useMemo(() => leadSignalOptions(catalogue, loaded), [catalogue, loaded]);
  // Open leads first (New > Assigned > Working > Converted > Closed > Released > Expired).
  const sorted = React.useMemo(() => sortLeadsByDefaultOrder(loaded, (lead) => lead.status), [loaded]);
  const items = React.useMemo(() => filterAgentLeads(sorted, filters, scope), [sorted, filters, scope]);

  const requestedPage = Number(searchParams.get("page") ?? 1);
  const page = clampPaginationPage(Number.isSafeInteger(requestedPage) ? requestedPage - 1 : 0, items.length);
  const pageItems = paginateItems(items, page);
  const setPage = (next: number) => router.replace(`/dashboard/leads?page=${next + 1}`, { scroll: false });

  const patch = (next: Partial<AgentLeadFilters>) => {
    setFilters((current) => ({ ...current, ...next }));
    if (page !== 0) setPage(0);
  };
  const moreActive = leadSignalActiveCount(filters, scope);
  const more = leadSignalFilterGroups({ filters, onChange: patch, scope, options, lead: false });
  const chips = compactChips([
    selectFilterChip("eligibility", "Eligibility", filters.eligibility, ROW_ELIGIBILITY_OPTIONS, () =>
      patch({ eligibility: "all" }),
    ),
    ...leadSignalChips(filters, patch, scope, options),
  ]);

  const reloadAll = () => {
    void reload();
    void eligibility.reload();
  };

  return (
    <DashboardPage>
      <DashboardHeader
        title="Leads"
        description="Leads you have introduced, and whether each one counts for you."
        actions={
          <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline"><Link href="/dashboard/leads/bulk">Bulk upload</Link></Button>
          <Button asChild className="bg-brand-cta text-white hover:bg-brand-cta/90">
            <Link href="/dashboard/leads/new">
              <PhoneCall className="h-4 w-4" aria-hidden="true" />
              Introduce a lead
            </Link>
          </Button>
          </div>
        }
      />

      <EligibilitySummaryCards
        summary={eligibility.summary}
        loading={eligibility.loading}
        noun={NOUN}
        eligibleHint="Accepted and counted for you"
        duplicateHint="Already registered or linked"
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto w-full justify-start overflow-x-auto sm:w-fit">
          <TabsTrigger value="leads">{loading ? "Leads" : `Leads (${loaded.length})`}</TabsTrigger>
          <TabsTrigger value="not-accepted">{notAcceptedTabLabel(eligibility.total)}</TabsTrigger>
        </TabsList>

        <TabsContent value="leads" className="mt-4 space-y-4">
          {loading ? (
            <Skeleton className="h-40 rounded-xl" />
          ) : error ? (
            <FetchError status={null} message={error} onRetry={reloadAll} />
          ) : loaded.length === 0 ? (
            <ListEmptyState
              icon={PhoneCall}
              title="No leads introduced yet"
              description="Introduce a lead to start tracking it here."
            />
          ) : (
            <>
              <FilterBar
                value={{ ...EMPTY_FILTERS, search: filters.search, status: filters.status }}
                onChange={(next) => patch({ search: next.search, status: next.status })}
                searchLabel="Search leads by name or mobile"
                searchPlaceholder="Search name or mobile"
                statusOptions={STATUS_OPTIONS}
                showLine={false}
                showDates={false}
                extra={
                  <div className="flex flex-wrap gap-2">
                  <FilterSelect
                    label="Eligibility"
                    value={filters.eligibility}
                    options={ROW_ELIGIBILITY_OPTIONS}
                    onValueChange={(value) => patch({ eligibility: value })}
                  />
                  <FilterSelect label="Resubmission" value={filters.resubmission} options={RESUBMISSION_OPTIONS}
                    onValueChange={(value) => patch({ resubmission: value as ResubmissionFilter })} />
                  </div>
                }
                hasExternalFilters={filters.eligibility !== "all" || filters.resubmission !== "all"}
                more={more}
                moreActiveCount={moreActive}
                onClearMore={() => patch(clearedLeadSignalFilters(filters))}
                chips={chips}
                onClear={() => {
                  setFilters(DEFAULT_AGENT_LEAD_FILTERS);
                  if (page !== 0) setPage(0);
                }}
              />
              <DashboardPanel
                title="Introduced leads"
                description={`Tap a lead to view its details. ${AGENT_LEAD_EXPIRY_POLICY}`}
              >
                {items.length === 0 ? (
                  <ListEmptyState
                    icon={SearchX}
                    title="No leads match these filters"
                    description="Change or clear the filters to see more leads."
                    className="bg-muted/20"
                  />
                ) : (
                  <>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm" aria-label="Introduced leads">
                        <thead className="border-b border-border text-xs uppercase tracking-wide text-text-secondary">
                          <tr>
                            <th className="px-5 py-3 font-medium">Lead</th>
                            <th className="px-5 py-3 font-medium">Status</th>
                            <th className="px-5 py-3 font-medium">Eligibility</th>
                            <th className="hidden px-5 py-3 font-medium md:table-cell">Registered</th>
                            <th className="px-5 py-3 font-medium">Agent window</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pageItems.map((lead) => (
                            <tr
                              key={lead.id}
                              onClick={() => router.push(`/dashboard/leads/${lead.id}?page=${page + 1}`)}
                              className="cursor-pointer border-b border-border transition-colors last:border-0 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              <td className="px-5 py-4">
                                <Link href={`/dashboard/leads/${lead.id}?page=${page + 1}`} onClick={(event) => event.stopPropagation()} className="inline-flex min-h-11 items-center rounded font-semibold text-brand-link underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{lead.name ?? "Unnamed lead"}</Link>
                                <p className="text-xs text-text-secondary">{formatMobile(lead.mobile)}</p>
                                <ResubmissionBadge count={lead.resubmit_count} at={lead.last_resubmitted_at} />
                              </td>
                              <td className="px-5 py-4">
                                <span
                                  className={cn(
                                    "inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium",
                                    STATUS_STYLE[lead.status] ?? "bg-muted text-text-secondary",
                                  )}
                                >
                                  {AGENT_LEAD_STATUS_LABEL[lead.status] ?? lead.status}
                                </span>
                              </td>
                              <td className="px-5 py-4">
                                <RowEligibilityBadge row={lead} />
                              </td>
                              <td className="hidden px-5 py-4 text-text-secondary md:table-cell">
                                {lead.registered ? "Account created" : "Not registered yet"}
                              </td>
                              <td className="px-5 py-4 text-xs text-text-secondary">
                                <p>
                                  {formatAgentLeadExpiry(lead.status, lead.expires_at, lead.expired_at, {
                                    resubmittable: lead.resubmittable,
                                  })}
                                </p>
                                {lead.resubmittable ? (
                                  <ResubmitLeadButton
                                    className="mt-2"
                                    leadName={lead.name}
                                    onResubmit={() => resubmitAgentLead(lead.id)}
                                    onDone={reloadAll}
                                  />
                                ) : null}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <ListPagination page={page} total={items.length} onPageChange={setPage} label="Introduced leads pages" />
                  </>
                )}
              </DashboardPanel>
            </>
          )}
        </TabsContent>

        <TabsContent value="not-accepted" className="mt-4">
          <DashboardPanel
            title="Not accepted"
            description="Numbers you tried to introduce that were turned away, and why."
            bodyClassName="p-4 sm:p-5"
          >
            <NotAcceptedList
              attempts={eligibility.attempts}
              total={eligibility.total}
              loading={eligibility.loading}
              error={eligibility.attemptsError}
              onRetry={() => void eligibility.reload()}
              emptyDescription="When a number you introduce is already registered, linked to another enquiry or past your window, it is listed here."
              label="Leads not accepted"
            />
          </DashboardPanel>
        </TabsContent>
      </Tabs>
    </DashboardPage>
  );
}
