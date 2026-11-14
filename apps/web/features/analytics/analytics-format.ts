import { formatCompactINR, formatINR } from "@/lib/format";
import type { AnalyticsUnit } from "@/lib/staff-analytics-api";

// Categorical slots 1-4 of the validated reference palette (light surface),
// assigned in fixed order by series position, never cycled. Slots 3-4 sit
// below 3:1 on white, so every chart also offers a table view.
export const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"] as const;
// Single-hue magnitude bars (ranked lists, funnel).
export const MAGNITUDE_COLOR = "#2a78d6";

export function seriesColor(index: number): string {
  return SERIES_COLORS[Math.min(index, SERIES_COLORS.length - 1)];
}

export const OTHER_KEY = "other";
// Neutral gray for the folded remainder; never a categorical slot.
export const OTHER_COLOR = "#9ca3af";

type Part = { key: string; label: string; value: number };

/**
 * Parts arrive in a fixed category order (so each keeps its color). With more
 * than four, the smallest fold into "Other" and the rest keep their order.
 */
export function foldShareParts(items: readonly Part[], slots = SERIES_COLORS.length): Part[] {
  if (items.length <= slots) return [...items];
  const keep = new Set(
    [...items]
      .sort((a, b) => b.value - a.value)
      .slice(0, slots - 1)
      .map((item) => item.key),
  );
  const rest = items.filter((item) => !keep.has(item.key)).reduce((sum, item) => sum + item.value, 0);
  return [
    ...items.filter((item) => keep.has(item.key)),
    { key: OTHER_KEY, label: "Other", value: rest },
  ];
}

export function formatMetric(value: number | null | undefined, unit: AnalyticsUnit): string {
  if (value == null) return "—";
  switch (unit) {
    case "percent":
      return `${value.toLocaleString("en-IN", { maximumFractionDigits: 1 })}%`;
    case "hours":
      return value < 48
        ? `${value.toLocaleString("en-IN", { maximumFractionDigits: 1 })} h`
        : `${(value / 24).toLocaleString("en-IN", { maximumFractionDigits: 1 })} days`;
    case "rupees":
      return value >= 100_000 ? formatCompactINR(value) : formatINR(value);
    default:
      return value.toLocaleString("en-IN");
  }
}

const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

/** "13 Nov" for an ISO calendar date (no timezone shift). */
export function formatDay(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return DAY.format(new Date(year, month - 1, day));
}

/** Share of the whole, rounded, for labels ("42%"). */
export function shareLabel(value: number, total: number): string {
  return total > 0 ? `${Math.round((value / total) * 100)}%` : "0%";
}
