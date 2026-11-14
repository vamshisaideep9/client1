"use client";

import * as React from "react";
import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import {
  ANALYTICS_RANGES,
  getMyAnalytics,
  type AnalyticsBreakdown,
  type AnalyticsFunnel,
  type AnalyticsKpi,
  type AnalyticsRange,
  type AnalyticsTrend,
  type StaffAnalytics,
} from "@/lib/staff-analytics-api";

import {
  MAGNITUDE_COLOR,
  OTHER_COLOR,
  OTHER_KEY,
  foldShareParts,
  formatDay,
  formatMetric,
  seriesColor,
  shareLabel,
} from "./analytics-format";

// Recharts loads only on this page, after the shell has painted.
const TrendChart = dynamic(() => import("./trend-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full rounded-lg sm:h-72" />,
});

const ROLE_COPY: Record<StaffAnalytics["role"], string> = {
  telecaller: "Your calls, leads and how they are converting.",
  employee: "Your field tasks: workload, completion and timeliness.",
  agent: "Leads you introduced, their progress and your commission.",
  sub_admin: "Banners and offers you created and how reviews went.",
};

type State =
  | { status: "loading" }
  | { status: "ready"; data: StaffAnalytics }
  | { status: "error"; error: string; code: number | null };

function KpiTile({ kpi }: { kpi: AnalyticsKpi }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-4 shadow-sm">
      <p className="text-xs font-medium text-text-secondary">{kpi.label}</p>
      <p className="mt-1 font-heading text-2xl font-semibold tabular-nums text-brand-heading">
        {formatMetric(kpi.value, kpi.unit)}
      </p>
      {kpi.hint ? <p className="mt-0.5 text-xs text-text-secondary">{kpi.hint}</p> : null}
    </div>
  );
}

function Legend({ items }: { items: { key: string; label: string; detail?: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-secondary" aria-label="Legend">
      {items.map((item, index) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ backgroundColor: seriesColor(index) }}
          />
          <span>{item.label}</span>
          {item.detail ? <span className="tabular-nums text-text-primary">{item.detail}</span> : null}
        </li>
      ))}
    </ul>
  );
}

function TableToggle({ summary, children }: { summary: string; children: React.ReactNode }) {
  return (
    <details className="group mt-3">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center text-sm font-medium text-brand-link outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="group-open:hidden">Show as table</span>
        <span className="hidden group-open:inline">Hide table</span>
        <span className="sr-only"> · {summary}</span>
      </summary>
      <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-border">{children}</div>
    </details>
  );
}

function TrendPanel({ trend }: { trend: AnalyticsTrend }) {
  const totals = trend.series.map((series) =>
    trend.points.reduce((sum, point) => sum + (point.values[series.key] ?? 0), 0),
  );
  const empty = totals.every((total) => total === 0);
  return (
    <DashboardPanel title={trend.title} description={trend.description}>
      {trend.series.length > 1 ? (
        <div className="mb-3">
          <Legend
            items={trend.series.map((series, index) => ({
              key: series.key,
              label: series.label,
              detail: String(totals[index]),
            }))}
          />
        </div>
      ) : null}
      {empty ? (
        <p className="py-10 text-center text-sm text-text-secondary">Nothing recorded in this period yet.</p>
      ) : (
        <TrendChart trend={trend} />
      )}
      <TableToggle summary={trend.title}>
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{trend.title}</caption>
          <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Day</th>
              {trend.series.map((series) => (
                <th key={series.key} scope="col" className="px-3 py-2 text-right font-medium">
                  {series.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {[...trend.points].reverse().map((point) => (
              <tr key={point.day}>
                <th scope="row" className="px-3 py-1.5 font-normal text-text-secondary">
                  {formatDay(point.day)}
                </th>
                {trend.series.map((series) => (
                  <td key={series.key} className="px-3 py-1.5 text-right tabular-nums">
                    {point.values[series.key] ?? 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableToggle>
    </DashboardPanel>
  );
}

/** One whole split into a few parts: a segmented bar with a labeled legend. */
function ShareBar({ breakdown }: { breakdown: AnalyticsBreakdown }) {
  const parts = foldShareParts(breakdown.items);
  const total = parts.reduce((sum, item) => sum + item.value, 0);
  const color = (key: string, index: number) => (key === OTHER_KEY ? OTHER_COLOR : seriesColor(index));
  return (
    <div className="space-y-3">
      <div className="flex h-8 w-full gap-0.5 overflow-hidden rounded-md" aria-hidden="true">
        {parts.map((part, index) => (
          <div
            key={part.key}
            className="h-full first:rounded-l-md last:rounded-r-md"
            style={{ width: `${(part.value / total) * 100}%`, backgroundColor: color(part.key, index) }}
            title={`${part.label}: ${formatMetric(part.value, breakdown.unit)}`}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-secondary" aria-label="Legend">
        {parts.map((part, index) => (
          <li key={part.key} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: color(part.key, index) }}
            />
            <span>{part.label}</span>
            <span className="tabular-nums text-text-primary">
              {formatMetric(part.value, breakdown.unit)} · {shareLabel(part.value, total)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Compare parts: one hue, largest first, values labeled. */
function RankedBars({
  items,
  unit,
  label,
}: {
  items: { key: string; label: string; value: number; note?: string }[];
  unit: AnalyticsKpi["unit"];
  label: string;
}) {
  const max = Math.max(...items.map((item) => item.value), 0);
  return (
    <ul className="space-y-3" aria-label={label}>
      {items.map((item) => (
        <li key={item.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
          <span className="min-w-0 truncate text-sm text-text-primary">{item.label}</span>
          <span className="text-right text-sm tabular-nums text-text-primary">
            {formatMetric(item.value, unit)}
            {item.note ? <span className="ml-1 text-xs text-text-secondary">{item.note}</span> : null}
          </span>
          <span className="col-span-2 h-2.5 w-full rounded-full bg-muted" aria-hidden="true">
            <span
              className="block h-full rounded-full"
              style={{
                width: max > 0 ? `${Math.max((item.value / max) * 100, item.value > 0 ? 2 : 0)}%` : "0%",
                backgroundColor: MAGNITUDE_COLOR,
              }}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

function BreakdownPanel({ breakdown }: { breakdown: AnalyticsBreakdown }) {
  return (
    <DashboardPanel title={breakdown.title} description={breakdown.description}>
      {breakdown.items.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-secondary">No data yet.</p>
      ) : breakdown.kind === "share" ? (
        <ShareBar breakdown={breakdown} />
      ) : (
        <RankedBars items={breakdown.items} unit={breakdown.unit} label={breakdown.title} />
      )}
    </DashboardPanel>
  );
}

function FunnelPanel({ funnel }: { funnel: AnalyticsFunnel }) {
  const first = funnel.steps[0]?.value ?? 0;
  return (
    <DashboardPanel title={funnel.title} description={funnel.description}>
      <RankedBars
        label={funnel.title}
        unit="count"
        items={funnel.steps.map((step, index) => ({
          key: step.key,
          label: step.label,
          value: step.value,
          note: index > 0 ? shareLabel(step.value, first) : undefined,
        }))}
      />
    </DashboardPanel>
  );
}

export function StaffAnalyticsView() {
  const [range, setRange] = React.useState<AnalyticsRange>(30);
  const [state, setState] = React.useState<State>({ status: "loading" });
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    setState((current) => (current.status === "ready" ? current : { status: "loading" }));
    void getMyAnalytics(range).then((res) => {
      if (!active) return;
      setState(
        res.ok
          ? { status: "ready", data: res.data }
          : { status: "error", error: res.error, code: res.status },
      );
    });
    return () => {
      active = false;
    };
  }, [range, reloadKey]);

  const data = state.status === "ready" ? state.data : null;

  return (
    <DashboardPage>
      <DashboardHeader
        title="My analytics"
        description={data ? ROLE_COPY[data.role] : "How your work is going."}
        actions={
          <ToggleGroup
            type="single"
            value={String(range)}
            onValueChange={(value) => value && setRange(Number(value) as AnalyticsRange)}
            aria-label="Period"
          >
            {ANALYTICS_RANGES.map((days) => (
              <ToggleGroupItem key={days} value={String(days)} className="px-3">
                {days} days
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        }
      />

      {state.status === "error" ? (
        <FetchError
          status={state.code}
          message={state.error}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      ) : !data ? (
        <div className="space-y-5" role="status" aria-label="Loading analytics">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-24 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-80 rounded-xl" />
        </div>
      ) : (
        <div className="space-y-5">
          <section
            aria-label="Key figures"
            className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5"
          >
            {data.kpis.map((kpi) => (
              <KpiTile key={kpi.key} kpi={kpi} />
            ))}
          </section>

          <TrendPanel trend={data.trend} />

          <div className="grid gap-5 lg:grid-cols-2">
            {data.breakdowns.map((breakdown) => (
              <BreakdownPanel key={breakdown.key} breakdown={breakdown} />
            ))}
            {data.funnel ? <FunnelPanel funnel={data.funnel} /> : null}
          </div>
        </div>
      )}
    </DashboardPage>
  );
}
