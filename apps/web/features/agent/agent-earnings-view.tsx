"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
  MetricCard,
  MetricGrid,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { FilterBar, type FilterBarValue } from "@/features/dashboard/filter-bar";
import {
  compactChips,
  optionsFromLabels,
  selectFilterChip,
  type ActiveFilterChip,
} from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { ListPagination } from "@/features/dashboard/list-pagination";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { useFilteredPage } from "@/features/dashboard/use-filtered-page";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import type { AgentEarningsRow } from "@/lib/agent-api";
import { formatPaise } from "@/lib/format";

import { AgentTransactionSheet } from "./agent-transaction-sheet";
import {
  COMMISSION_STATUS_LABEL,
  DEAL_TYPE_LABEL,
  EMPTY_EARNINGS_FILTERS,
  LEAD_STATUS_LABEL,
  earningsFilterOptions,
  filterEarningsRows,
  humanizeStatus,
  lastMonthLabel,
  moreEarningsFilterCount,
  type AgentEarningsFilterState,
} from "./agent-earnings-filters";
import { formatWhen } from "./agent-history-format";
import { CommissionDetailSheet } from "./commission-detail-sheet";
import { useAgentEarnings } from "./use-agent-earnings";

const STATUS_TONE = { pending: "warning", paid: "success", cancelled: "neutral" } as const;
const STATUS_OPTIONS = optionsFromLabels(COMMISSION_STATUS_LABEL);
const DEAL_TYPE_OPTIONS = optionsFromLabels(DEAL_TYPE_LABEL);

function amountChip(min: string, max: string, onRemove: () => void): ActiveFilterChip | null {
  if (!min && !max) return null;
  const text = min && max ? `₹${min} – ₹${max}` : min ? `from ₹${min}` : `up to ₹${max}`;
  return { id: "amount", label: `Commission: ${text}`, onRemove };
}

function digitsOnly(value: string): string {
  return value.replace(/[^\d]/g, "").slice(0, 12);
}

export function AgentEarningsView() {
  const { earnings, status, error, errorStatus, retry } = useAgentEarnings();
  const [filters, setFilters] = React.useState<AgentEarningsFilterState>(EMPTY_EARNINGS_FILTERS);
  const [selected, setSelected] = React.useState<AgentEarningsRow | null>(null);
  const [transactionId, setTransactionId] = React.useState<string | null>(null);

  const rows = React.useMemo(() => earnings?.rows ?? [], [earnings]);
  const filtered = React.useMemo(() => filterEarningsRows(rows, filters), [rows, filters]);
  const catalogue = useProductCatalogue(!rows.some((row) => row.business_line === "real_estate"));
  const options = React.useMemo(() => earningsFilterOptions(rows, catalogue), [rows, catalogue]);
  const { page, setPage, pageRows, total } = useFilteredPage(filtered, filters);
  const set = (patch: Partial<AgentEarningsFilterState>) => setFilters((current) => ({ ...current, ...patch }));

  if (status === "loading") {
    return (
      <DashboardPage className="space-y-5">
        <Skeleton className="h-9 w-48 rounded-lg" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
          <Skeleton className="h-24 rounded-2xl" />
        </div>
        <Skeleton className="h-64 rounded-2xl" />
      </DashboardPage>
    );
  }

  if (status === "error" || !earnings) {
    return (
      <DashboardPage>
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      </DashboardPage>
    );
  }

  // Agents are line-scoped, so every row shares one line: a Loans Agent
  // filters by product and bank, a Real Estate Agent by property category.
  const isRealEstate = rows.some((row) => row.business_line === "real_estate");
  const hidden = earnings.hidden_fields;
  const month = lastMonthLabel(earnings.totals);
  const barValue: FilterBarValue = {
    search: filters.search,
    status: filters.status,
    line: "all",
    kind: filters.dealType,
    from: filters.from,
    to: filters.to,
  };
  const moreCount = moreEarningsFilterCount(filters);
  const chips = compactChips([
    selectFilterChip("lead-status", "Lead status", filters.leadStatus, options.leadStatuses, () =>
      set({ leadStatus: "all" }),
    ),
    selectFilterChip("product", "Product", filters.product, options.products, () => set({ product: "all" })),
    selectFilterChip("bank", "Bank", filters.bank, options.banks, () => set({ bank: "all" })),
    selectFilterChip("category", "Property category", filters.propertyCategory, options.categories, () =>
      set({ propertyCategory: "all" }),
    ),
    amountChip(filters.amountMin, filters.amountMax, () => set({ amountMin: "", amountMax: "" })),
  ]);
  const amountInverted =
    filters.amountMin !== "" && filters.amountMax !== "" && Number(filters.amountMin) > Number(filters.amountMax);

  const columns: DataColumn<AgentEarningsRow>[] = [
    {
      key: "client",
      header: "Client and deal",
      render: (row) => (
        <DataTablePrimaryCell
          title={row.client_name ?? (hidden.includes("client_name") ? "Client (hidden)" : "Client")}
          subtitle={[
            DEAL_TYPE_LABEL[row.deal_type] ?? row.deal_type,
            row.product_label ?? row.property_title,
            row.bank_name,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
      ),
    },
    {
      key: "lead",
      header: "Lead",
      render: (row) =>
        row.lead_status ? (LEAD_STATUS_LABEL[row.lead_status] ?? humanizeStatus(row.lead_status)) : "—",
    },
    {
      key: "deal_status",
      header: "Deal status",
      render: (row) => humanizeStatus(row.deal_status),
    },
    {
      key: "amount",
      header: "Commission",
      align: "right",
      render: (row) => <span className="font-semibold tabular-nums">{formatPaise(row.agreed_amount_paise)}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <StatusBadge tone={STATUS_TONE[row.status]}>{COMMISSION_STATUS_LABEL[row.status] ?? row.status}</StatusBadge>
      ),
    },
    {
      key: "dates",
      header: "Entered / paid",
      render: (row) => (
        <span className="text-xs text-text-secondary">
          {formatWhen(row.created_at)}
          {row.paid_at ? ` · paid ${formatWhen(row.paid_at)}` : ""}
        </span>
      ),
    },
  ];

  return (
    <DashboardPage>
      <DashboardHeader title="Earnings" description="Every commission Admin has recorded against your deals." />

      <MetricGrid>
        <MetricCard label="Total" value={formatPaise(earnings.totals.total_amount_paise)} icon={DASHBOARD_ICONS.earnings} />
        <MetricCard label="Pending" value={formatPaise(earnings.totals.pending_amount_paise)} icon={DASHBOARD_ICONS.earnings} />
        <MetricCard label="Paid" value={formatPaise(earnings.totals.paid_amount_paise)} icon={DASHBOARD_ICONS.earnings} />
        <MetricCard
          label={month ? `Paid · ${month}` : "Paid last month"}
          value={formatPaise(earnings.totals.last_month_paid_amount_paise)}
          icon={DASHBOARD_ICONS.earnings}
        />
      </MetricGrid>

      {rows.length === 0 ? (
        <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
            <DASHBOARD_ICONS.earnings className="h-6 w-6" aria-hidden="true" />
          </span>
          <h2 className="mt-5 text-lg font-semibold text-text-primary">No commissions recorded yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
            Commissions appear here once Admin records one against a deal you sourced.
          </p>
        </div>
      ) : (
        <>
          <FilterBar
            value={barValue}
            onChange={(next) =>
              set({ search: next.search, status: next.status, dealType: next.kind, from: next.from, to: next.to })
            }
            searchLabel="Search commissions"
            searchPlaceholder={isRealEstate ? "Client, property or ID" : "Client, product, bank or ID"}
            statusOptions={STATUS_OPTIONS}
            statusLabel="Status"
            kindOptions={DEAL_TYPE_OPTIONS}
            kindLabel="Deal type"
            showLine={false}
            dateFromLabel="Entered from"
            dateToLabel="Entered to"
            more={[
              {
                title: "Lead",
                content: (
                  <FilterSelect
                    label="Lead status"
                    value={filters.leadStatus}
                    options={options.leadStatuses}
                    onValueChange={(leadStatus) => set({ leadStatus })}
                  />
                ),
              },
              {
                title: isRealEstate ? "Property" : "Product",
                content: isRealEstate ? (
                  <FilterSelect
                    label="Property category"
                    value={filters.propertyCategory}
                    options={options.categories}
                    onValueChange={(propertyCategory) => set({ propertyCategory })}
                  />
                ) : (
                  <>
                    <FilterSelect
                      label="Product"
                      value={filters.product}
                      options={options.products}
                      onValueChange={(product) => set({ product })}
                    />
                    <FilterSelect
                      label="Bank"
                      value={filters.bank}
                      options={options.banks}
                      onValueChange={(bank) => set({ bank })}
                    />
                  </>
                ),
              },
              {
                title: "Money",
                content: (
                  <fieldset className="min-w-0 sm:col-span-2">
                    <legend className="mb-1 text-xs font-medium text-text-secondary">Commission (₹)</legend>
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        aria-label="Minimum commission (₹)"
                        inputMode="numeric"
                        placeholder="Min"
                        value={filters.amountMin}
                        aria-invalid={amountInverted || undefined}
                        onChange={(event) => set({ amountMin: digitsOnly(event.target.value) })}
                      />
                      <Input
                        aria-label="Maximum commission (₹)"
                        inputMode="numeric"
                        placeholder="Max"
                        value={filters.amountMax}
                        aria-invalid={amountInverted || undefined}
                        onChange={(event) => set({ amountMax: digitsOnly(event.target.value) })}
                      />
                    </div>
                    {amountInverted ? (
                      <p className="mt-1 text-xs text-error">The minimum is above the maximum.</p>
                    ) : null}
                  </fieldset>
                ),
              },
            ]}
            moreActiveCount={moreCount}
            onClearMore={() =>
              set({
                leadStatus: "all",
                product: "all",
                bank: "all",
                propertyCategory: "all",
                amountMin: "",
                amountMax: "",
              })
            }
            chips={chips}
            onClear={() => setFilters(EMPTY_EARNINGS_FILTERS)}
          />

          <DashboardPanel
            title="Commission history"
            description={`${total} of ${rows.length} commissions. Open one for the client, the deal and how it was paid.`}
            bodyClassName="p-0"
          >
            {total === 0 ? (
              <p className="p-4 text-sm text-text-secondary">No commissions match these filters.</p>
            ) : (
              <DataTable
                columns={columns}
                rows={pageRows}
                rowKey={(row) => row.id}
                onRowClick={setSelected}
                rowActionLabel="Open commission"
                minWidth="xl:min-w-[860px]"
              />
            )}
            <div className="p-3">
              <ListPagination page={page} total={total} onPageChange={setPage} label="Commission history pages" />
            </div>
          </DashboardPanel>
        </>
      )}

      <CommissionDetailSheet
        row={selected}
        hiddenFields={hidden}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        onOpenTransaction={(id) => {
          setSelected(null);
          setTransactionId(id);
        }}
      />
      <AgentTransactionSheet
        transactionId={transactionId}
        onOpenChange={(open) => {
          if (!open) setTransactionId(null);
        }}
      />
    </DashboardPage>
  );
}
