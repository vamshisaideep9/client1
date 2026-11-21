import type { components } from "@contracts/generated/schema";
import { apiDownload, apiRequest } from "@/lib/api/client";
import { brandedFilename } from "@/lib/brand";

type Schema = components["schemas"];
export type AttendanceDay = Schema["AttendanceDayRead"];
export type AttendanceRequest = Schema["AttendanceRequestRead"];
export type AttendanceMine = Schema["MyAttendanceRead"];
export type AttendanceLeave = Schema["AttendanceLeaveInput"];
export type AttendanceCorrection = Schema["AttendanceCorrectionInput"];
export type AttendanceAdjustment = Schema["AttendanceAdjustmentInput"];
export type AttendanceDecision = Schema["AttendanceDecisionInput"];
export type AttendanceRoster = Schema["AttendanceRosterRead"];
export type AttendanceInbox = Schema["AttendanceInboxRead"];
export type AttendancePolicy = Schema["AttendancePolicyInput"];
export type AttendancePolicyState = Schema["AttendancePolicyState"];
export type AttendanceHoliday = Schema["AttendanceHolidayRead"];

export function getAttendanceRoster(params: URLSearchParams) {
  return apiRequest<AttendanceRoster>(`${ATTENDANCE_API}/roster?${params}`);
}

export function getAttendanceInbox(params: URLSearchParams) {
  return apiRequest<AttendanceInbox>(`${ATTENDANCE_API}/requests?${params}`);
}

export function decideAttendanceRequest(id: string, body: AttendanceDecision) {
  return apiRequest<AttendanceRequest>(`${ATTENDANCE_API}/requests/${encodeURIComponent(id)}/decision`, {
    method: "POST", body,
  });
}

export function getAttendancePolicy() {
  return apiRequest<AttendancePolicyState>(`${ATTENDANCE_API}/policy`);
}

export function saveAttendancePolicy(body: AttendancePolicy) {
  return apiRequest<AttendancePolicyState>(`${ATTENDANCE_API}/policy`, { method: "PUT", body });
}

export function getAttendanceHolidays(start: string, end: string) {
  const params = new URLSearchParams({ start, end });
  return apiRequest<AttendanceHoliday[]>(`${ATTENDANCE_API}/holidays?${params}`);
}

export function setAttendanceHoliday(day: string, name: string | null) {
  return apiRequest<null>(`${ATTENDANCE_API}/holidays/${encodeURIComponent(day)}`,
    name === null ? { method: "DELETE" } : { method: "PUT", body: { name } });
}

export function exportAttendance(params: URLSearchParams) {
  return apiDownload(`${ATTENDANCE_API}/export?${params}`,
    brandedFilename(`attendance-${params.get("start")}-${params.get("end")}.csv`));
}

const ATTENDANCE_API = "/api/v1/attendance";

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

export function requestAttendanceAdjustment(body: AttendanceAdjustment) {
  return apiRequest<AttendanceRequest>(`${ATTENDANCE_API}/regularizations`, { method: "POST", body });
}

export function cancelAttendanceRequest(id: string) {
  return apiRequest<AttendanceRequest>(
    `${ATTENDANCE_API}/requests/${encodeURIComponent(id)}/cancel`, { method: "POST" },
  );
}
