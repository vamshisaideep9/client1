"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatDay, seriesColor } from "@/features/analytics/analytics-format";

export type ProductTrendPoint = { week_start: string; captured?: number; converted?: number };

export const PRODUCT_TREND_SERIES = [
  { key: "captured", label: "Captured" },
  { key: "converted", label: "Converted" },
] as const;

type TooltipEntry = { dataKey?: unknown; value?: unknown };

function TrendTooltip({ active, payload, label }: { active?: boolean; payload?: readonly TooltipEntry[]; label?: unknown }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-40 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1.5 font-medium text-text-primary">Week of {formatDay(String(label))}</p>
      <ul className="space-y-1">
        {PRODUCT_TREND_SERIES.map((series, index) => (
          <li key={series.key} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-text-secondary">
              <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: seriesColor(index) }} />
              {series.label}
            </span>
            <span className="tabular-nums text-text-primary">
              {Number(payload.find((entry) => entry.dataKey === series.key)?.value ?? 0)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Weekly leads captured against leads converted, side by side (two measures of
 * one count scale on one axis). The legend and the table view live in the
 * surrounding panel; this renders only the plot.
 */
export default function ProductTrendChart({ points }: { points: readonly ProductTrendPoint[] }) {
  const rows = points.map((point) => ({
    day: point.week_start,
    captured: point.captured ?? 0,
    converted: point.converted ?? 0,
  }));
  return (
    <div className="h-64 w-full sm:h-72" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }} barCategoryGap="24%" barGap={2}>
          <CartesianGrid vertical={false} stroke="var(--color-border, #e5e7eb)" strokeDasharray="0" />
          <XAxis
            dataKey="day"
            tickFormatter={(value: string) => formatDay(value)}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={44} tick={{ fontSize: 11, fill: "#6b7280" }} />
          <Tooltip
            cursor={{ fill: "rgba(42, 120, 214, 0.08)" }}
            content={(props) => (
              <TrendTooltip
                active={props.active}
                payload={props.payload as readonly TooltipEntry[] | undefined}
                label={props.label}
              />
            )}
          />
          {PRODUCT_TREND_SERIES.map((series, index) => (
            <Bar
              key={series.key}
              dataKey={series.key}
              name={series.label}
              fill={seriesColor(index)}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
              maxBarSize={22}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
