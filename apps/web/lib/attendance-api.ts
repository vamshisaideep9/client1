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
export type AttendanceEmployment = Schema["AttendanceEmploymentRead"];
export type AttendanceEmploymentInput = Schema["AttendanceEmploymentInput"];
export type AttendanceLine = AttendanceEmploymentInput["business_line"];
export type AttendanceMonth = Schema["AttendanceMonthRead"];

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

export function getAttendanceHolidays(start: string, end: string, line?: AttendanceLine) {
  const params = new URLSearchParams({ start, end });
  if (line) params.set("business_line", line);
  return apiRequest<AttendanceHoliday[]>(`${ATTENDANCE_API}/holidays?${params}`);
}

export function setAttendanceHoliday(day: string, name: string | null, line?: AttendanceLine) {
  const scope = line ? `?${new URLSearchParams({ business_line: line })}` : "";
  return apiRequest<null>(`${ATTENDANCE_API}/holidays/${encodeURIComponent(day)}${scope}`,
    name === null ? { method: "DELETE" } : { method: "PUT", body: { name } });
}

export function getAttendanceEmployment(id: string) {
  return apiRequest<AttendanceEmployment | null>(`${ATTENDANCE_API}/employment/${encodeURIComponent(id)}`);
}

export function saveAttendanceEmployment(id: string, body: AttendanceEmploymentInput) {
  return apiRequest<AttendanceEmployment>(`${ATTENDANCE_API}/employment/${encodeURIComponent(id)}`, { method: "PUT", body });
}

export function getAttendanceReviewers(line: AttendanceLine) {
  const params = new URLSearchParams({ business_line: line });
  return apiRequest<AttendanceRoster["members"]>(`${ATTENDANCE_API}/employment/reviewers?${params}`);
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

function certificatePath(id: string) {
  return `${ATTENDANCE_API}/requests/${encodeURIComponent(id)}/certificate`;
}

export function uploadAttendanceCertificate(id: string, file: File) {
  const body = new FormData();
  body.set("file", file);
  return apiRequest(certificatePath(id), { method: "POST", body });
}

export function downloadAttendanceCertificate(id: string) {
  return apiDownload(certificatePath(id), (type) => {
    const extension = type === "image/jpeg" ? "jpg" : type === "image/png" ? "png" : "pdf";
    return `medical-certificate.${extension}`;
  });
}

export function getAttendanceMonth(day: string) {
  return apiRequest<AttendanceMonth>(`${ATTENDANCE_API}/months/${encodeURIComponent(day)}`);
}

export function changeAttendanceMonth(day: string, action: "close" | "reopen", body: Schema["AttendanceMonthAction"]) {
  return apiRequest<AttendanceMonth>(`${ATTENDANCE_API}/months/${encodeURIComponent(day)}/${action}`, { method: "POST", body });
}

export function exportAttendanceMonth(day: string, version?: number) {
  const params = version ? `?version=${version}` : "";
  return apiDownload(`${ATTENDANCE_API}/months/${encodeURIComponent(day)}/export${params}`,
    brandedFilename(`attendance-${day.slice(0, 7)}${version ? `-revision-${version}` : ""}.csv`));
}
