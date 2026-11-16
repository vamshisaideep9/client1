"use client";

import * as React from "react";
import dynamic from "next/dynamic";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { shareLabel } from "@/features/analytics/analytics-format";
import { Legend, RankedBars, ShareBar, TableToggle } from "@/features/analytics/staff-analytics-view";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import type { AgentsReportResponse, ReportKind } from "@/lib/reports-api";

import {
  conversionSeries,
  formatBucketLabel,
  journeyTrend,
  teamShare,
  topAgents,
  type JourneyKind,
  type JourneyRow,
} from "./report-chart-data";
import { CHART_LIMIT, TOP_AGENTS, useReportChart } from "./use-report-chart";
import type { ReportFilterInput, ReportResponse } from "./use-report";

// Recharts loads only when a chart is on screen, after the page has painted.
const chartSkeleton = () => <Skeleton className="h-64 w-full rounded-lg sm:h-72" />;
const TrendChart = dynamic(() => import("@/features/analytics/trend-chart"), {
  ssr: false,
  loading: chartSkeleton,
});
const ConversionChart = dynamic(() => import("./conversion-chart"), { ssr: false, loading: chartSkeleton });

const EMPTY_MESSAGE = "No activity in this date range.";

function Empty() {
  return <p className="py-10 text-center text-sm text-text-secondary">{EMPTY_MESSAGE}</p>;
}

const cell = "px-3 py-1.5";
const headCell = "px-3 py-2 font-medium";

function JourneyCharts({
  kind,
  rows,
  total,
  bucket,
  businessLine,
}: {
  kind: JourneyKind;
  rows: JourneyRow[];
  total: number;
  bucket: "week" | "month";
  businessLine?: string;
}) {
  const trend = journeyTrend(rows, kind, bucket, businessLine);
  const conversion = conversionSeries(rows);
  const label = (day: string) => formatBucketLabel(day, bucket);
  const periodHeader = bucket === "month" ? "Month" : "Week starting";
  const totals = trend.series.map((series) =>
    trend.points.reduce((sum, point) => sum + (point.values[series.key] ?? 0), 0),
  );
  const empty = rows.length === 0;

  return (
    <>
      {total > rows.length ? (
        <p className="text-xs text-text-secondary lg:col-span-5">
          The charts cover the first {CHART_LIMIT.toLocaleString("en-IN")} of {total.toLocaleString("en-IN")} period
          rows. Narrow the date range to chart the rest.
        </p>
      ) : null}
      <DashboardPanel title={trend.title} description={trend.description} className="lg:col-span-3">
        {empty ? (
          <Empty />
        ) : (
          <>
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
            <TrendChart trend={trend} formatLabel={label} />
            <TableToggle summary={trend.title}>
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{trend.title}</caption>
                <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
                  <tr>
                    <th scope="col" className={headCell}>
                      {periodHeader}
                    </th>
                    {trend.series.map((series) => (
                      <th key={series.key} scope="col" className={`${headCell} text-right`}>
                        {series.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {[...trend.points].reverse().map((point) => (
                    <tr key={point.day}>
                      <th scope="row" className={`${cell} font-normal text-text-secondary`}>
                        {label(point.day)}
                      </th>
                      {trend.series.map((series) => (
                        <td key={series.key} className={`${cell} text-right tabular-nums`}>
                          {point.values[series.key] ?? 0}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableToggle>
          </>
        )}
      </DashboardPanel>

      <DashboardPanel
        title="Conversion rate"
        description={`Converted out of the total each ${bucket}, across the lines shown.`}
        className="lg:col-span-2"
      >
        {empty ? (
          <Empty />
        ) : (
          <>
            <ConversionChart points={conversion} formatLabel={label} />
            <TableToggle summary="Conversion rate">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Conversion rate</caption>
                <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
                  <tr>
                    <th scope="col" className={headCell}>
                      {periodHeader}
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Total
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Converted
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Rate
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {[...conversion].reverse().map((point) => (
                    <tr key={point.day}>
                      <th scope="row" className={`${cell} font-normal text-text-secondary`}>
                        {label(point.day)}
                      </th>
                      <td className={`${cell} text-right tabular-nums`}>{point.total}</td>
                      <td className={`${cell} text-right tabular-nums`}>{point.converted}</td>
                      <td className={`${cell} text-right tabular-nums`}>
                        {point.rate == null ? "—" : `${point.rate}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableToggle>
          </>
        )}
      </DashboardPanel>
    </>
  );
}

function AgentCharts({ data }: { data: AgentsReportResponse }) {
  const top = topAgents(data.rows, TOP_AGENTS);
  const share = teamShare(data.team_summaries);
  const shareTotal = share.items.reduce((sum, item) => sum + item.value, 0);
  const topTitle = `Top ${TOP_AGENTS} agents by leads`;

  return (
    <>
      <DashboardPanel
        title={topTitle}
        description="Leads each Agent introduced in this period, with how many converted."
        className="lg:col-span-3"
      >
        {top.length === 0 ? (
          <Empty />
        ) : (
          <>
            <RankedBars items={top} unit="count" label={topTitle} />
            <TableToggle summary={topTitle}>
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{topTitle}</caption>
                <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
                  <tr>
                    <th scope="col" className={headCell}>
                      Agent
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Leads
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Converted
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {top.map((item) => (
                    <tr key={item.key}>
                      <th scope="row" className={`${cell} font-normal text-text-secondary`}>
                        {item.label}
                      </th>
                      <td className={`${cell} text-right tabular-nums`}>{item.value}</td>
                      <td className={`${cell} text-right tabular-nums`}>{item.converted}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableToggle>
          </>
        )}
      </DashboardPanel>

      <DashboardPanel title={share.title} description={share.description} className="lg:col-span-2">
        {share.items.length === 0 ? (
          <Empty />
        ) : (
          <>
            <ShareBar breakdown={share} />
            <TableToggle summary={share.title}>
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{share.title}</caption>
                <thead className="sticky top-0 bg-muted text-xs text-text-secondary">
                  <tr>
                    <th scope="col" className={headCell}>
                      Line
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Leads
                    </th>
                    <th scope="col" className={`${headCell} text-right`}>
                      Share
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {share.items.map((item) => (
                    <tr key={item.key}>
                      <th scope="row" className={`${cell} font-normal text-text-secondary`}>
                        {item.label}
                      </th>
                      <td className={`${cell} text-right tabular-nums`}>{item.value}</td>
                      <td className={`${cell} text-right tabular-nums`}>{shareLabel(item.value, shareTotal)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableToggle>
          </>
        )}
      </DashboardPanel>
    </>
  );
}

function ChartsBody({ kind, data, filters }: { kind: ReportKind; data: ReportResponse; filters: ReportFilterInput }) {
  if (kind === "agents") return <AgentCharts data={data as AgentsReportResponse} />;
  return (
    <JourneyCharts
      kind={kind}
      rows={data.rows as JourneyRow[]}
      total={data.total}
      bucket={filters.bucket ?? "week"}
      businessLine={filters.businessLine}
    />
  );
}

/**
 * Charts for one Admin report tab. They read the report separately from the
 * paginated table (see useReportChart), so they always show the whole
 * filtered period whatever the table's sort or page.
 */
export function ReportCharts({ kind, filters }: { kind: ReportKind; filters: ReportFilterInput }) {
  const { data, loading, error, reload } = useReportChart(kind, filters);

  if (error) {
    return (
      <div role="alert" className="rounded-xl border border-border bg-card p-6 text-center">
        <p className="text-sm text-text-secondary">Couldn&apos;t load the charts. {error}</p>
        <Button variant="outline" className="mt-4" onClick={() => void reload()}>
          Try again
        </Button>
      </div>
    );
  }

  if (!data) {
    return (
      <div role="status" aria-label="Loading charts" className="grid gap-4 lg:grid-cols-5">
        <Skeleton className="h-80 rounded-xl lg:col-span-3" />
        <Skeleton className="h-80 rounded-xl lg:col-span-2" />
      </div>
    );
  }

  return (
    <section
      aria-label="Charts"
      aria-busy={loading}
      className="grid gap-4 transition-opacity data-[busy=true]:opacity-60 lg:grid-cols-5"
      data-busy={loading}
    >
      <ChartsBody kind={kind} data={data} filters={filters} />
    </section>
  );
}
