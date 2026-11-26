"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { CheckCircle2, ClipboardList, Clock, Layers, Repeat, TrendingUp, Users } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { formatDay } from "@/features/analytics/analytics-format";
import { Legend, TableToggle } from "@/features/analytics/staff-analytics-view";
import {
  DashboardBackLink,
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
  MetricCard,
  MetricGrid,
} from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { FetchError } from "@/features/dashboard/fetch-error";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { PRODUCT_CATEGORY_LABEL } from "@/features/dashboard/product-specialty";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { LOAN_STATUS_LABEL } from "@/features/telecaller/lead-signal-filters";
import { useLoad } from "@/features/team/use-load";
import { getProductDashboard, type ProductDashboard, type ProductStaffRow } from "@/lib/product-dashboards-api";

import { PERIOD_OPTIONS, ROLE_LABEL, formatRate } from "./product-coverage";
import { PRODUCT_TREND_SERIES } from "./product-trend-chart";

// Recharts loads only on this page, after the shell has painted.
const ProductTrendChart = dynamic(() => import("./product-trend-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full rounded-lg sm:h-72" />,
});

const ENQUIRY_STATUS_LABEL: Record<string, string> = {
  submitted: "Submitted",
  contacted: "Contacted",
  in_progress: "In progress",
  completed: "Completed",
  closed: "Closed",
  rejected: "Rejected",
};

function statusLabel(kind: ProductDashboard["requests_kind"], status: string): string {
  const labels: Record<string, string> = kind === "applications" ? LOAN_STATUS_LABEL : ENQUIRY_STATUS_LABEL;
  return labels[status] ?? status.replaceAll("_", " ");
}

function RequestsPanel({ data }: { data: ProductDashboard }) {
  const items = data.requests_by_status ?? [];
  const max = Math.max(1, ...items.map((item) => item.count));
  const title = data.requests_kind === "applications" ? "Applications by stage" : "Enquiries by status";
  return (
    <DashboardPanel title={title} description={`Opened in this period${data.scope === "team" ? " on your team's leads" : ""}.`}>
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-secondary">None opened in this period.</p>
      ) : (
        <ul className="space-y-3" aria-label={title}>
          {items.map((item) => (
            <li key={item.status} className="space-y-1">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="text-text-secondary">{statusLabel(data.requests_kind, item.status)}</span>
                <span className="font-medium tabular-nums text-text-primary">{item.count}</span>
              </div>
              <div className="h-2 rounded-full bg-muted" aria-hidden="true">
                <div className="h-2 rounded-full bg-brand-cta" style={{ width: `${Math.max(4, (item.count / max) * 100)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </DashboardPanel>
  );
}

function TrendPanel({ data }: { data: ProductDashboard }) {
  const points = data.trend ?? [];
  const totals = PRODUCT_TREND_SERIES.map((series) => points.reduce((sum, point) => sum + (point[series.key] ?? 0), 0));
  const empty = totals.every((total) => total === 0);
  const title = "Leads captured and converted";
  return (
    <DashboardPanel title={title} description="Per week (Monday start). Converted counts leads converted that week.">
      <div className="mb-3">
        <Legend
          items={PRODUCT_TREND_SERIES.map((series, index) => ({ key: series.key, label: series.label, detail: String(totals[index]) }))}
        />
      </div>
      {empty ? (
        <p className="py-10 text-center text-sm text-text-secondary">Nothing recorded in this period yet.</p>
      ) : (
        <ProductTrendChart points={points} />
      )}
      <TableToggle summary={title}>
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Week starting</th>
              {PRODUCT_TREND_SERIES.map((series) => (
                <th key={series.key} scope="col" className="px-3 py-2 text-right font-medium">{series.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {[...points].reverse().map((point) => (
              <tr key={point.week_start}>
                <th scope="row" className="px-3 py-1.5 font-normal text-text-secondary">{formatDay(point.week_start)}</th>
                {PRODUCT_TREND_SERIES.map((series) => (
                  <td key={series.key} className="px-3 py-1.5 text-right tabular-nums">{point[series.key] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableToggle>
    </DashboardPanel>
  );
}

const STAFF_COLUMNS: DataColumn<ProductStaffRow>[] = [
  {
    key: "person",
    header: "Person",
    render: (row) => (
      <DataTablePrimaryCell title={`${row.first_name} ${row.last_name}`} subtitle={`${ROLE_LABEL[row.role]} · ${row.staff_code}`} />
    ),
  },
  {
    key: "routing",
    header: "Routing",
    render: (row) =>
      row.specialist ? <StatusBadge tone="info">Specialist</StatusBadge> : <StatusBadge>Fallback</StatusBadge>,
  },
  { key: "assigned", header: "Leads held", align: "right", render: (row) => <span className="tabular-nums">{row.role === "telecaller" ? row.assigned ?? 0 : "—"}</span> },
  { key: "contacted", header: "Called", align: "right", render: (row) => <span className="tabular-nums">{row.role === "telecaller" ? row.contacted ?? 0 : "—"}</span> },
  { key: "converted", header: "Converted", align: "right", render: (row) => <span className="tabular-nums">{row.role === "telecaller" ? row.converted ?? 0 : "—"}</span> },
  { key: "open_tasks", header: "Open tasks", align: "right", render: (row) => <span className="tabular-nums">{row.role === "employee" ? row.open_tasks ?? 0 : "—"}</span> },
  { key: "completed_tasks", header: "Completed tasks", align: "right", render: (row) => <span className="tabular-nums">{row.role === "employee" ? row.completed_tasks ?? 0 : "—"}</span> },
];

/** One product's dashboard: Admin sees the platform, a Team Manager their own teams. */
export function ProductDashboardView({ productId, backHref, backLabel }: { productId: string; backHref: string; backLabel: string }) {
  const [days, setDays] = React.useState("30");
  const { state, retry } = useLoad(() => getProductDashboard(productId, Number(days)), [productId, days]);
  const data = state.status === "ready" ? state.data : null;
  const period = PERIOD_OPTIONS.find((option) => option.value === days)?.label ?? "This period";

  return (
    <DashboardPage>
      <DashboardHeader
        title={data ? data.product.label : "Product dashboard"}
        description={
          data
            ? data.scope === "team"
              ? "Your Loans teams' work on this product: leads, requests, field tasks and people."
              : "Every lead, request, field task and person working on this product."
            : undefined
        }
        meta={
          data ? (
            <>
              <StatusBadge tone="info">{PRODUCT_CATEGORY_LABEL[data.product.category] ?? data.product.category}</StatusBadge>
              {data.product.active === false ? <StatusBadge tone="warning">Inactive</StatusBadge> : null}
              {data.scope === "team" ? <StatusBadge>Your teams</StatusBadge> : null}
            </>
          ) : undefined
        }
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <Select value={days} onValueChange={setDays}>
              <SelectTrigger className="w-44" aria-label="Period">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERIOD_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <DashboardBackLink href={backHref}>{backLabel}</DashboardBackLink>
          </div>
        }
      />
      {state.status === "error" ? (
        state.code === 404 ? (
          <ListEmptyState icon={Layers} title="Product not found" description="It may have been removed from the catalogue." />
        ) : (
          <FetchError status={state.code} message={state.error} onRetry={retry} />
        )
      ) : !data ? (
        <ListLoadingState rows={4} />
      ) : (
        <>
          <MetricGrid>
            <MetricCard label="Leads captured" value={data.leads.captured ?? 0} icon={TrendingUp} hint={period} />
            <MetricCard label="Open leads" value={data.leads.open ?? 0} icon={Layers} hint="Right now" />
            <MetricCard label="Converted" value={data.leads.converted ?? 0} icon={CheckCircle2} hint={period} />
            <MetricCard
              label="Conversion rate"
              value={formatRate(data.leads.conversion_rate)}
              icon={Repeat}
              hint="Of leads captured in the period"
            />
            <MetricCard
              label="Served by fallback"
              value={data.leads.served_by_fallback ?? 0}
              icon={Users}
              hint="Held by a non-specialist"
              attention={(data.leads.served_by_fallback ?? 0) > 0}
            />
            {data.scope === "platform" ? (
              <MetricCard
                label="Unassigned leads"
                value={data.leads.unassigned ?? 0}
                icon={Clock}
                hint="No Telecaller yet"
                attention={(data.leads.unassigned ?? 0) > 0}
              />
            ) : null}
            <MetricCard label="Open field tasks" value={data.tasks.open ?? 0} icon={ClipboardList} hint="Right now" />
            <MetricCard
              label="Tasks on time"
              value={formatRate(data.tasks.on_time_rate)}
              icon={CheckCircle2}
              hint={`${data.tasks.completed ?? 0} completed in the period`}
            />
          </MetricGrid>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <TrendPanel data={data} />
            <RequestsPanel data={data} />
          </div>

          <DashboardPanel
            title="People"
            description={`Specialists and anyone else who handled this product's work. ${period}.`}
            bodyClassName="p-0"
          >
            {(data.staff ?? []).length === 0 ? (
              <div className="p-4">
                <ListEmptyState icon={Users} title="No one has worked on this product yet" description="Assign a specialist from Products & staffing." />
              </div>
            ) : (
              <DataTable columns={STAFF_COLUMNS} rows={data.staff ?? []} rowKey={(row) => row.staff_profile_uuid} minWidth="min-w-[860px]" />
            )}
          </DashboardPanel>
        </>
      )}
    </DashboardPage>
  );
}
