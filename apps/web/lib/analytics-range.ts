// Calendar date-range helpers shared by every analytics dashboard (personal
// "My analytics" and Admin Analytics). Ranges are inclusive India Standard
// Time calendar dates as "YYYY-MM-DD" strings, which is exactly what the API
// accepts as date_from/date_to. Pure functions, unit-tested in
// analytics-range.test.ts.

import { toIsoDateIST } from "@/lib/reports";

export type DateRangeValue = { dateFrom: string; dateTo: string };

/** The API rejects longer periods (one leap year of days). */
export const MAX_RANGE_DAYS = 366;

export type RangePreset =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year";

export const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last_7_days", label: "Last 7 days" },
  { key: "last_30_days", label: "Last 30 days" },
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "this_quarter", label: "This quarter" },
  { key: "this_year", label: "This year" },
];

const DAY_MS = 24 * 60 * 60 * 1000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function iso(y: number, m0: number, d: number): string {
  // Date.UTC normalises overflow (e.g. day 0 = last day of previous month).
  const date = new Date(Date.UTC(y, m0, d));
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function parts(isoDate: string): { y: number; m0: number; d: number } {
  const [y, m, d] = isoDate.split("-").map(Number);
  return { y, m0: m - 1, d };
}

export function todayIST(now: Date): string {
  return toIsoDateIST(now);
}

export function shiftIsoDate(isoDate: string, days: number): string {
  const { y, m0, d } = parts(isoDate);
  return iso(y, m0, d + days);
}

/** Inclusive number of days in the range. */
export function rangeSpanDays(range: DateRangeValue): number {
  const { y: fy, m0: fm, d: fd } = parts(range.dateFrom);
  const { y: ty, m0: tm, d: td } = parts(range.dateTo);
  return Math.round((Date.UTC(ty, tm, td) - Date.UTC(fy, fm, fd)) / DAY_MS) + 1;
}

export function resolveRangePreset(preset: RangePreset, now: Date): DateRangeValue {
  const today = todayIST(now);
  const { y, m0 } = parts(today);
  switch (preset) {
    case "today":
      return { dateFrom: today, dateTo: today };
    case "yesterday": {
      const yesterday = shiftIsoDate(today, -1);
      return { dateFrom: yesterday, dateTo: yesterday };
    }
    case "last_7_days":
      return { dateFrom: shiftIsoDate(today, -6), dateTo: today };
    case "last_30_days":
      return { dateFrom: shiftIsoDate(today, -29), dateTo: today };
    case "this_month":
      return { dateFrom: iso(y, m0, 1), dateTo: today };
    case "last_month":
      return { dateFrom: iso(y, m0 - 1, 1), dateTo: iso(y, m0, 0) };
    case "this_quarter":
      return { dateFrom: iso(y, m0 - (m0 % 3), 1), dateTo: today };
    case "this_year":
      return { dateFrom: iso(y, 0, 1), dateTo: today };
  }
}

/** The preset a range corresponds to today, if any (for highlighting it). */
export function matchingPreset(range: DateRangeValue, now: Date): RangePreset | null {
  for (const { key } of RANGE_PRESETS) {
    const candidate = resolveRangePreset(key, now);
    if (candidate.dateFrom === range.dateFrom && candidate.dateTo === range.dateTo) return key;
  }
  return null;
}

/** Why a range can't be applied, or null when it is valid. */
export function rangeError(range: DateRangeValue, now: Date): string | null {
  if (!range.dateFrom || !range.dateTo) return "Choose a start and an end date.";
  if (range.dateFrom > range.dateTo) return "The start date must be on or before the end date.";
  if (range.dateTo > todayIST(now)) return "The end date can't be in the future.";
  if (rangeSpanDays(range) > MAX_RANGE_DAYS) return `Choose a period of at most ${MAX_RANGE_DAYS} days.`;
  return null;
}

const SHORT = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const LONG = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function asUtcDate(isoDate: string): Date {
  const { y, m0, d } = parts(isoDate);
  return new Date(Date.UTC(y, m0, d));
}

/** "15 Nov 2026", "1 – 15 Nov 2026", "28 Oct – 15 Nov 2026" or "Dec 2025 – Jan 2026" style labels. */
export function formatRangeLabel(range: DateRangeValue): string {
  if (range.dateFrom === range.dateTo) return LONG.format(asUtcDate(range.dateTo));
  const from = asUtcDate(range.dateFrom);
  const to = asUtcDate(range.dateTo);
  const sameYear = from.getUTCFullYear() === to.getUTCFullYear();
  return `${(sameYear ? SHORT : LONG).format(from)} – ${LONG.format(to)}`;
}

/** Calendar widgets work in local Date objects; keep the calendar day intact. */
export function isoToLocalDate(isoDate: string): Date {
  const { y, m0, d } = parts(isoDate);
  return new Date(y, m0, d);
}

export function localDateToIso(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
