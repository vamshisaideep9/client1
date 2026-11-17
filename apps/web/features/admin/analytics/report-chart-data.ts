// Pure shaping of Admin report rows into chart data. The charts reuse the
// personal-analytics shapes (AnalyticsTrend, AnalyticsBreakdown) so the same
// chart and table components render both pages.

import type { AgentsReportRow, ReportBucket, TeamPerformanceSummary } from "@/lib/reports-api";
import type { AnalyticsBreakdown, AnalyticsTrend } from "@/lib/staff-analytics-api";

export type JourneyKind = "leads" | "loans" | "deals";
export type JourneyRow = { bucket_start: string; business_line: string; total: number; converted: number };

// Fixed order so a line keeps its color on every chart.
export const LINE_ORDER = ["loans", "real_estate"] as const;
export const LINE_LABEL: Record<string, string> = { loans: "Loans", real_estate: "Real Estate" };

const KIND_NOUN: Record<JourneyKind, string> = { leads: "Leads", loans: "Applications", deals: "Deals" };
const KIND_DESCRIPTION: Record<JourneyKind, string> = {
  leads: "New leads, stacked by business line.",
  loans: "New loan applications, stacked by business line.",
  deals: "New property deals, stacked by business line.",
};

const IST_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** The IST calendar date ("2026-11-03") of a bucket start, whatever the viewer's timezone. */
export function istDate(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso.slice(0, 10) : IST_DATE.format(parsed);
}

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" });
const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

/** "3 Nov" for a week bucket, "Nov 2026" for a month bucket (ISO calendar date in). */
export function formatBucketLabel(isoDate: string, bucket: ReportBucket = "week"): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return bucket === "month" ? MONTH.format(date) : DAY.format(date);
}

function linesFor(rows: readonly JourneyRow[], selectedLine?: string): string[] {
  const known: string[] = selectedLine ? [selectedLine] : [...LINE_ORDER];
  const extra = [...new Set(rows.map((row) => row.business_line))].filter((line) => !known.includes(line));
  return [...known, ...extra.sort()];
}

/**
 * One point per bucket, one series per business line, totals summed. Buckets
 * come back from the API one row per (bucket, line); a line with no activity
 * in a bucket has no row, so it is filled with zero here.
 */
export function journeyTrend(
  rows: readonly JourneyRow[],
  kind: JourneyKind,
  bucket: ReportBucket = "week",
  selectedLine?: string,
): AnalyticsTrend {
  const lines = linesFor(rows, selectedLine);
  const byDay = new Map<string, Record<string, number>>();
  for (const row of rows) {
    const day = istDate(row.bucket_start);
    const values = byDay.get(day) ?? Object.fromEntries(lines.map((line) => [line, 0]));
    values[row.business_line] = (values[row.business_line] ?? 0) + row.total;
    byDay.set(day, values);
  }
  return {
    title: `${KIND_NOUN[kind]} per ${bucket}`,
    description: KIND_DESCRIPTION[kind],
    series: lines.map((line) => ({ key: line, label: LINE_LABEL[line] ?? line })),
    points: [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, values]) => ({ day, values })),
  };
}

export type ConversionPoint = { day: string; total: number; converted: number; rate: number | null };

/** Converted ÷ total per bucket across every line; null when nothing was recorded. */
export function conversionSeries(rows: readonly JourneyRow[]): ConversionPoint[] {
  const byDay = new Map<string, { total: number; converted: number }>();
  for (const row of rows) {
    const day = istDate(row.bucket_start);
    const current = byDay.get(day) ?? { total: 0, converted: 0 };
    byDay.set(day, { total: current.total + row.total, converted: current.converted + row.converted });
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, { total, converted }]) => ({
      day,
      total,
      converted,
      rate: total > 0 ? Math.round((converted / total) * 1000) / 10 : null,
    }));
}

export type AgentItem = { key: string; label: string; value: number; converted: number; note: string };

/** The agents with the most leads, largest first; agents with no leads are left out. */
export function topAgents(rows: readonly AgentsReportRow[], n = 10): AgentItem[] {
  return [...rows]
    .filter((row) => row.leads_total > 0)
    .sort((a, b) => b.leads_total - a.leads_total || a.agent_name.localeCompare(b.agent_name))
    .slice(0, n)
    .map((row) => ({
      key: row.agent_profile_uuid,
      label: `${row.agent_name} (${row.agent_code})`,
      value: row.leads_total,
      converted: row.leads_converted,
      note: `${row.leads_converted} converted`,
    }));
}

/** Agent leads split by business line, in the fixed line order; empty lines are omitted. */
export function teamShare(teams: readonly TeamPerformanceSummary[]): AnalyticsBreakdown {
  const order = (line: string) => {
    const index = (LINE_ORDER as readonly string[]).indexOf(line);
    return index === -1 ? LINE_ORDER.length : index;
  };
  return {
    key: "leads_by_line",
    title: "Leads by line",
    description: "Leads introduced by the selected Agents, by business line.",
    kind: "share",
    unit: "count",
    items: [...teams]
      .sort((a, b) => order(a.business_line) - order(b.business_line))
      .filter((team) => team.leads_total > 0)
      .map((team) => ({
        key: team.business_line,
        label: LINE_LABEL[team.business_line] ?? team.business_line,
        value: team.leads_total,
      })),
  };
}
