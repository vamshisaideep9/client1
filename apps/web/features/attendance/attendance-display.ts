import type { AttendanceAdjustment, AttendanceDay, AttendanceRequest } from "@/lib/attendance-api";

export const ATTENDANCE_STATUS: Record<AttendanceDay["status"], string> = {
  checked_in: "Logged in",
  present: "Present",
  half_day: "Half day",
  short_day: "Short day",
  absent: "Absent",
  missing_checkout: "Missing logout",
  on_leave: "On leave",
  holiday: "Holiday",
  week_off: "Weekly off",
};

const dateDisplay = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: "Asia/Kolkata" });
const timeDisplay = new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: "Asia/Kolkata" });
const dateKey = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

export const istDay = (value = new Date()) => dateKey.format(value);
export const attendanceDate = (day: string) => dateDisplay.format(new Date(`${day}T12:00:00+05:30`));
export const attendanceTime = (instant: string | null) => instant ? timeDisplay.format(new Date(instant)) : "—";
export const leaveLabel = (key: string) => key.replace(/_/g, " ").replace(/^./, (value) => value.toUpperCase());
export const duration = (minutes: number) => `${Math.floor(minutes / 60)}h ${minutes % 60}m`;

export function previousMonth(now = new Date()): string {
  const [year, month] = istDay(now).split("-").map(Number);
  return new Date(Date.UTC(year, month - 2, 1)).toISOString().slice(0, 7);
}

/** The first day of the current IST month, for the default From date. */
export function monthStart(now = new Date()): string {
  return `${istDay(now).slice(0, 8)}01`;
}

/** Every IST date from `start` to `end` inclusive (empty when reversed). */
export function datesBetween(start: string, end: string): string[] {
  const days: string[] = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  while (cursor <= last && days.length < 400) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}

/** The API's range rule: From on or before To, at most 31 days. */
export function rangeError(start: string, end: string): string | null {
  if (!start || !end) return "Choose a From and a To date.";
  if (start > end) return "From must be on or before To.";
  return datesBetween(start, end).length > 31 ? "Choose a range of up to 31 days." : null;
}

export type AttendanceBadge = { code: string; label: string; tone: string };

/** Every day code, its meaning and its colour, in legend order. */
export const ATTENDANCE_CODES = {
  P: { code: "P", label: "Present", tone: "bg-green-100 text-green-950" },
  HD: { code: "HD", label: "Half day", tone: "bg-orange-100 text-orange-950" },
  LT: { code: "LT", label: "Late login", tone: "bg-amber-100 text-amber-950" },
  SD: { code: "SD", label: "Short day (left early)", tone: "bg-rose-100 text-rose-950" },
  A: { code: "A", label: "Absent", tone: "bg-red-100 text-red-950" },
  H: { code: "H", label: "Holiday", tone: "bg-blue-100 text-blue-950" },
  SUN: { code: "SUN", label: "Weekly off", tone: "bg-slate-200 text-slate-900" },
  OD: { code: "OD", label: "On duty", tone: "bg-cyan-100 text-cyan-950" },
  WOH: { code: "WOH", label: "Work on holiday", tone: "bg-violet-100 text-violet-950" },
  CO: { code: "CO", label: "Sunday work with comp-off", tone: "bg-lime-100 text-lime-950" },
} satisfies Record<string, AttendanceBadge>;

const LEAVE_TONES: Record<string, string> = {
  CL: "bg-sky-100 text-sky-950",
  SL: "bg-teal-100 text-teal-950",
};
const OTHER_LEAVE_TONE = "bg-indigo-100 text-indigo-950";

export const LEAVE_LEGEND: AttendanceBadge[] = [
  { code: "CL", label: "Casual leave", tone: LEAVE_TONES.CL },
  { code: "SL", label: "Sick leave", tone: LEAVE_TONES.SL },
];

export function attendanceCode(day: AttendanceDay): AttendanceBadge | null {
  if (day.adjustments?.includes("comp_off")) return ATTENDANCE_CODES.CO;
  if (day.adjustments?.includes("holiday_work")) return ATTENDANCE_CODES.WOH;
  if (day.adjustments?.includes("on_duty")) return ATTENDANCE_CODES.OD;
  if (day.status === "checked_in" || day.status === "missing_checkout") return null;
  if (day.calendar_status === "week_off" || day.status === "week_off") return ATTENDANCE_CODES.SUN;
  if (day.calendar_status === "holiday" || day.status === "holiday") return ATTENDANCE_CODES.H;
  if (day.status === "absent") return ATTENDANCE_CODES.A;
  if (day.early_exit) return ATTENDANCE_CODES.SD;
  if (day.late) return ATTENDANCE_CODES.LT;
  if (day.status === "half_day") return ATTENDANCE_CODES.HD;
  if (day.status === "present") return ATTENDANCE_CODES.P;
  return null;
}

/** Leave badges from the API (every approved leave type), CL and SL first. */
export function leaveBadges(day: AttendanceDay): AttendanceBadge[] {
  const fromApi = day.leave_badges ?? [];
  const badges = fromApi.length
    ? fromApi
    : (day.leave_codes ?? []).map((code) => LEAVE_LEGEND.find((entry) => entry.code === code)!).filter(Boolean);
  return badges.map(({ code, label }) => ({ code, label, tone: LEAVE_TONES[code] ?? OTHER_LEAVE_TONE }));
}

/** Each badge carries its own meaning, so its tooltip and accessible name match it. */
export function attendanceBadges(day: AttendanceDay): AttendanceBadge[] {
  const status = attendanceCode(day);
  return status ? [status, ...leaveBadges(day)] : leaveBadges(day);
}

/** The codes for a legend: every day code, CL and SL, and other leave types seen. */
export function attendanceLegend(days: readonly AttendanceDay[]): AttendanceBadge[] {
  const extra = new Map<string, AttendanceBadge>();
  for (const day of days) {
    for (const badge of leaveBadges(day)) {
      if (!LEAVE_LEGEND.some((entry) => entry.code === badge.code)) extra.set(badge.code, badge);
    }
  }
  return [...Object.values(ATTENDANCE_CODES), ...LEAVE_LEGEND, ...[...extra.values()].sort((a, b) => a.code.localeCompare(b.code))];
}

export const ADJUSTMENT_LABELS: Record<AttendanceAdjustment["adjustment_type"], string> = {
  late_waiver: "Late waiver",
  early_exit: "Short-day exception",
  on_duty: "On duty",
  holiday_work: "Work on holiday",
  comp_off: "Sunday work with comp-off",
};

export function requestLabel(request: AttendanceRequest): string {
  if (request.kind === "leave") return leaveLabel(request.leave_type ?? "leave");
  if (request.adjustment_type) return ADJUSTMENT_LABELS[request.adjustment_type];
  return "Punch correction";
}

export function monthDays(month: string) {
  const [year, number] = month.split("-").map(Number);
  return Array.from({ length: new Date(Date.UTC(year, number, 0)).getUTCDate() },
    (_, index) => `${month}-${String(index + 1).padStart(2, "0")}`);
}
