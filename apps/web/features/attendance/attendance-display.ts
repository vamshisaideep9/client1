import type { AttendanceDay } from "@/lib/attendance-api";

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

export function monthDays(month: string) {
  const [year, number] = month.split("-").map(Number);
  return Array.from({ length: new Date(Date.UTC(year, number, 0)).getUTCDate() },
    (_, index) => `${month}-${String(index + 1).padStart(2, "0")}`);
}
