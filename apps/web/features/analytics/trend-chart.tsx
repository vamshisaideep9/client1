"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AnalyticsTrend } from "@/lib/staff-analytics-api";

import { formatDay, seriesColor } from "./analytics-format";

type Row = { day: string } & Record<string, number | string>;

type TooltipEntry = { dataKey?: unknown; value?: unknown };

function TrendTooltip({
  active,
  payload,
  label,
  trend,
}: {
  active?: boolean;
  payload?: readonly TooltipEntry[];
  label?: unknown;
  trend: AnalyticsTrend;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((sum, entry) => sum + Number(entry.value ?? 0), 0);
  return (
    <div className="min-w-40 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1.5 font-medium text-text-primary">{formatDay(String(label))}</p>
      <ul className="space-y-1">
        {trend.series.map((series, index) => {
          const value = Number(payload.find((entry) => entry.dataKey === series.key)?.value ?? 0);
          return (
            <li key={series.key} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-text-secondary">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: seriesColor(index) }}
                />
                {series.label}
              </span>
              <span className="tabular-nums text-text-primary">{value}</span>
            </li>
          );
        })}
      </ul>
      {trend.series.length > 1 ? (
        <p className="mt-1.5 flex justify-between border-t border-border pt-1.5 text-text-primary">
          <span>Total</span>
          <span className="tabular-nums">{total}</span>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Day-by-day stacked bars (one hue per series in fixed order). The legend and
 * the table view live in the surrounding panel; this renders only the plot.
 */
export default function TrendChart({ trend }: { trend: AnalyticsTrend }) {
  const rows: Row[] = trend.points.map((point) => ({ day: point.day, ...point.values }));
  const lastIndex = trend.series.length - 1;
  return (
    <div className="h-64 w-full sm:h-72" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }} barCategoryGap="20%">
          <CartesianGrid vertical={false} stroke="var(--color-border, #e5e7eb)" strokeDasharray="0" />
          <XAxis
            dataKey="day"
            tickFormatter={(value: string) => formatDay(value)}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            width={44}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <Tooltip
            cursor={{ fill: "rgba(42, 120, 214, 0.08)" }}
            content={(props) => (
              <TrendTooltip
                active={props.active}
                payload={props.payload as readonly TooltipEntry[] | undefined}
                label={props.label}
                trend={trend}
              />
            )}
          />
          {trend.series.map((series, index) => (
            <Bar
              key={series.key}
              dataKey={series.key}
              name={series.label}
              stackId="trend"
              fill={seriesColor(index)}
              stroke="#ffffff"
              strokeWidth={1}
              radius={index === lastIndex ? [4, 4, 0, 0] : 0}
              isAnimationActive={false}
              maxBarSize={28}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
