import type { AttendanceAdjustment, AttendanceDay, AttendanceRequest } from "@/lib/attendance-api";

export const ATTENDANCE_STATUS: Record<AttendanceDay["status"], string> = {
  checked_in: "Checked in",
  present: "Present",
  half_day: "Half day",
  short_day: "Short day",
  absent: "Absent",
  missing_checkout: "Missing check-out",
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

export function attendanceCode(day: AttendanceDay): { code: string; tone: string } | null {
  if (day.adjustments?.includes("comp_off")) return { code: "CO", tone: "bg-lime-100 text-lime-950" };
  if (day.adjustments?.includes("holiday_work")) return { code: "POH", tone: "bg-violet-100 text-violet-950" };
  if (day.adjustments?.includes("on_duty")) return { code: "OD", tone: "bg-cyan-100 text-cyan-950" };
  if (day.status === "checked_in" || day.status === "missing_checkout") return null;
  if (day.calendar_status === "week_off" || day.status === "week_off") {
    return { code: "SUN", tone: "bg-slate-200 text-slate-900" };
  }
  if (day.calendar_status === "holiday" || day.status === "holiday") {
    return { code: "H", tone: "bg-blue-100 text-blue-950" };
  }
  if (day.status === "absent") return { code: "A", tone: "bg-red-100 text-red-950" };
  if (day.early_exit) return { code: "EE", tone: "bg-rose-100 text-rose-950" };
  if (day.late) return { code: "LT", tone: "bg-amber-100 text-amber-950" };
  if (day.status === "half_day") return { code: "HD", tone: "bg-orange-100 text-orange-950" };
  if (day.status === "present") return { code: "P", tone: "bg-green-100 text-green-950" };
  return null;
}

const LEAVE_BADGES = {
  CL: { code: "CL", label: "Casual leave", tone: "bg-sky-100 text-sky-950" },
  SL: { code: "SL", label: "Sick leave", tone: "bg-teal-100 text-teal-950" },
};

export function attendanceBadges(day: AttendanceDay) {
  const status = attendanceCode(day);
  const leave = (day.leave_codes ?? []).map((code) => LEAVE_BADGES[code]);
  return status ? [{ ...status, label: ATTENDANCE_STATUS[day.status] }, ...leave] : leave;
}

export const ADJUSTMENT_LABELS: Record<AttendanceAdjustment["adjustment_type"], string> = {
  late_waiver: "Late waiver",
  early_exit: "Early-exit exception",
  on_duty: "On duty",
  holiday_work: "Holiday work",
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
