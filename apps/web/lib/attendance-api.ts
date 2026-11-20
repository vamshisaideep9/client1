import type { components } from "@contracts/generated/schema";
import { apiRequest } from "@/lib/api/client";

type Schema = components["schemas"];
export type AttendanceDay = Schema["AttendanceDayRead"];
export type AttendanceRequest = Schema["AttendanceRequestRead"];
export type AttendanceMine = Schema["MyAttendanceRead"];
export type AttendanceLeave = Schema["AttendanceLeaveInput"];
export type AttendanceCorrection = Schema["AttendanceCorrectionInput"];

export const ATTENDANCE_API = "/api/v1/attendance";

export function getMyAttendance(month?: string) {
  const [year, numericMonth] = month?.split("-") ?? [];
  const query = year && numericMonth ? `?year=${year}&month=${Number(numericMonth)}` : "";
  return apiRequest<AttendanceMine>(`${ATTENDANCE_API}/me${query}`);
}

export function setAttendanceClock(checkingIn: boolean) {
  return apiRequest<AttendanceDay>(`${ATTENDANCE_API}/${checkingIn ? "check-in" : "check-out"}`, {
    method: "POST",
  });
}

export function requestAttendanceLeave(body: AttendanceLeave) {
  return apiRequest<AttendanceRequest>(`${ATTENDANCE_API}/leave`, { method: "POST", body });
}

export function requestAttendanceCorrection(body: AttendanceCorrection) {
  return apiRequest<AttendanceRequest>(`${ATTENDANCE_API}/corrections`, { method: "POST", body });
}

export function cancelAttendanceRequest(id: string) {
  return apiRequest<AttendanceRequest>(
    `${ATTENDANCE_API}/requests/${encodeURIComponent(id)}/cancel`, { method: "POST" },
  );
}
