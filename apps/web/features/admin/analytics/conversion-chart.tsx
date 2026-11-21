"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { MAGNITUDE_COLOR } from "@/features/analytics/analytics-format";

import type { ConversionPoint } from "./report-chart-data";

type TooltipEntry = { payload?: unknown };

function ConversionTooltip({
  active,
  payload,
  formatLabel,
}: {
  active?: boolean;
  payload?: readonly TooltipEntry[];
  formatLabel: (day: string) => string;
}) {
  const point = payload?.[0]?.payload as ConversionPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="min-w-40 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-text-primary">{formatLabel(point.day)}</p>
      <p className="tabular-nums text-text-primary">{point.rate == null ? "No activity" : `${point.rate}%`}</p>
      <p className="tabular-nums text-text-secondary">
        {point.converted} of {point.total} converted
      </p>
    </div>
  );
}

/**
 * Conversion rate per bucket, one line in the magnitude hue. Buckets with no
 * activity have no rate and leave a gap rather than reading as 0%. The table
 * view lives in the surrounding panel; this renders only the plot.
 */
export default function ConversionChart({
  points,
  formatLabel,
}: {
  points: ConversionPoint[];
  formatLabel: (day: string) => string;
}) {
  // Headroom above the highest rate, on round ticks (every 10% up to 40%,
  // every 20% beyond), never over 100%.
  const highest = Math.max(0, ...points.map((point) => point.rate ?? 0)) + 5;
  const step = highest <= 40 ? 10 : 20;
  const top = Math.min(100, Math.ceil(highest / step) * step);
  const ticks = Array.from({ length: top / step + 1 }, (_, index) => index * step);
  return (
    <div className="h-64 w-full sm:h-72" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
          <CartesianGrid vertical={false} stroke="var(--color-border, #e5e7eb)" strokeDasharray="0" />
          <XAxis
            dataKey="day"
            tickFormatter={(value: string) => formatLabel(value)}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <YAxis
            domain={[0, top]}
            ticks={ticks}
            tickFormatter={(value: number) => `${value}%`}
            tickLine={false}
            axisLine={false}
            width={48}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <Tooltip
            cursor={{ stroke: "rgba(42, 120, 214, 0.3)" }}
            content={(props) => (
              <ConversionTooltip
                active={props.active}
                payload={props.payload as readonly TooltipEntry[] | undefined}
                formatLabel={formatLabel}
              />
            )}
          />
          <Line
            type="monotone"
            dataKey="rate"
            name="Conversion rate"
            stroke={MAGNITUDE_COLOR}
            strokeWidth={2}
            dot={{ r: 3, fill: MAGNITUDE_COLOR, strokeWidth: 0 }}
            activeDot={{ r: 5 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
