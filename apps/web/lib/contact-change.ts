// CS-025 phone/email changes, adding an email, staff requests and the Admin
// queue + history. Thin wrappers over the generated contract; the API is the
// authority for every step (this module never decides who may do what).

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";
import type { AuthResult } from "@/lib/auth";

type Schemas = components["schemas"];

export type ContactField = "mobile" | "email";
export type ContactChangeKind = Schemas["ContactChangeChallengeResponse"]["kind"];
export type ContactChangeStatus = Schemas["ContactChangeChallengeResponse"]["status"];

export type ContactChallenge = {
  changeId: string;
  kind: ContactChangeKind;
  field: ContactField;
  status: ContactChangeStatus;
  expiresAt: string;
  message: string;
  destinationHint: string | null;
  deliveryChannel: "voice" | "email" | "none" | null;
  otpHint?: string;
};

export type ActiveContactChange = {
  changeId: string;
  kind: ContactChangeKind;
  field: ContactField;
  status: ContactChangeStatus;
  newValueHint: string | null;
  expiresAt: string;
  createdAt: string;
};

export type ContactChangeRequestRow = Schemas["ContactChangeAdminRead"];
export type ContactHistoryEntry = Schemas["ContactHistoryEntry"];

function toResult<T, U>(res: ApiResponse<T>, map: (data: T) => U): AuthResult<U> {
  if (res.ok) return { ok: true, data: map(res.data) };
  return { ok: false, error: res.error, status: res.status, issues: res.issues };
}

function toChallenge(data: Schemas["ContactChangeChallengeResponse"]): ContactChallenge {
  return {
    changeId: data.change_id,
    kind: data.kind,
    field: data.field,
    status: data.status,
    expiresAt: data.expires_at,
    message: data.message,
    destinationHint: data.destination_hint ?? null,
    deliveryChannel: data.delivery_channel ?? null,
    otpHint: data.otp_hint ?? undefined,
  };
}

async function post<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
  return apiRequest<T>(path, { method: "POST", body });
}

// --- Adding an email (also the blocking "Add your email" step) ------------

export async function addEmail(email: string, currentPassword: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>("/api/v1/auth/email/add", {
    email,
    current_password: currentPassword,
  } satisfies Schemas["EmailAddRequest"]);
  return toResult(res, toChallenge);
}

export async function resendAddEmail(changeId: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(
    "/api/v1/auth/email/add/resend",
    { change_id: changeId } satisfies Schemas["ContactChangeIdRequest"],
  );
  return toResult(res, toChallenge);
}

export async function verifyAddEmail(changeId: string, otp: string) {
  const res = await post<Schemas["MeResponse"]>("/api/v1/auth/email/add/verify", {
    change_id: changeId,
    otp,
  } satisfies Schemas["ContactChangeOtpRequest"]);
  return toResult(res, (data) => data);
}

// --- Self-service change (Client, Agent, Admin) ----------------------------

const BASE = "/api/v1/auth/contact-change";

export async function getActiveContactChange(): Promise<AuthResult<ActiveContactChange | null>> {
  const res = await apiRequest<Schemas["ActiveContactChangeResponse"]>(`${BASE}/active`, {
    method: "GET",
  });
  return toResult(res, (data) =>
    data.change
      ? {
          changeId: data.change.change_id,
          kind: data.change.kind,
          field: data.change.field,
          status: data.change.status,
          newValueHint: data.change.new_value_hint ?? null,
          expiresAt: data.change.expires_at,
          createdAt: data.change.created_at,
        }
      : null,
  );
}

export async function startContactChange(field: ContactField, currentPassword: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/start`, {
    field,
    current_password: currentPassword,
  } satisfies Schemas["ContactChangeStartRequest"]);
  return toResult(res, toChallenge);
}

export async function resendContactChange(changeId: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/resend`, {
    change_id: changeId,
  } satisfies Schemas["ContactChangeIdRequest"]);
  return toResult(res, toChallenge);
}

export async function verifyCurrentValue(changeId: string, otp: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/verify-current`, {
    change_id: changeId,
    otp,
  } satisfies Schemas["ContactChangeOtpRequest"]);
  return toResult(res, toChallenge);
}

export async function submitNewValue(changeId: string, value: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/new-value`, {
    change_id: changeId,
    value,
  } satisfies Schemas["ContactChangeNewValueRequest"]);
  return toResult(res, toChallenge);
}

export async function verifyNewValue(changeId: string, otp: string) {
  const res = await post<Schemas["ContactChangeCompletedResponse"]>(`${BASE}/verify-new`, {
    change_id: changeId,
    otp,
  } satisfies Schemas["ContactChangeOtpRequest"]);
  return toResult(res, (data) => ({ message: data.message, signedOut: data.signed_out ?? true }));
}

export async function cancelContactChange(changeId: string) {
  const res = await post<Schemas["MessageResponse"]>(`${BASE}/cancel`, {
    change_id: changeId,
  } satisfies Schemas["ContactChangeIdRequest"]);
  return toResult(res, () => undefined);
}

// --- Staff requests (Telecaller, Employee, Sub Admin) ----------------------

export async function requestStaffContactChange(
  field: ContactField,
  value: string,
  currentPassword: string,
) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/requests`, {
    field,
    value,
    current_password: currentPassword,
  } satisfies Schemas["StaffContactChangeRequest"]);
  return toResult(res, toChallenge);
}

export async function resendStaffContactChange(changeId: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/requests/resend`, {
    change_id: changeId,
  } satisfies Schemas["ContactChangeIdRequest"]);
  return toResult(res, toChallenge);
}

export async function verifyStaffContactChange(changeId: string, otp: string) {
  const res = await post<Schemas["ContactChangeChallengeResponse"]>(`${BASE}/requests/verify`, {
    change_id: changeId,
    otp,
  } satisfies Schemas["ContactChangeOtpRequest"]);
  return toResult(res, toChallenge);
}

// --- Platform Admin --------------------------------------------------------

const ADMIN = "/api/v1/admin/contact-change-requests";

export async function listContactChangeRequests() {
  const res = await apiRequest<Schemas["ContactChangeAdminListResponse"]>(ADMIN, {
    method: "GET",
  });
  return toResult(res, (data) => data.requests);
}

export async function approveContactChangeRequest(id: string, currentPassword: string) {
  const res = await post<Schemas["MessageResponse"]>(`${ADMIN}/${id}/approve`, {
    current_password: currentPassword,
  } satisfies Schemas["ContactChangeAdminApproveRequest"]);
  return toResult(res, (data) => data.message);
}

export async function rejectContactChangeRequest(
  id: string,
  reason: string,
  currentPassword: string,
) {
  const res = await post<Schemas["MessageResponse"]>(`${ADMIN}/${id}/reject`, {
    reason,
    current_password: currentPassword,
  } satisfies Schemas["ContactChangeAdminRejectRequest"]);
  return toResult(res, (data) => data.message);
}

export async function getContactHistory(authUserUuid: string) {
  const res = await apiRequest<Schemas["ContactHistoryResponse"]>(
    `/api/v1/admin/users/${encodeURIComponent(authUserUuid)}/contact-history`,
    { method: "GET" },
  );
  return toResult(res, (data) => data.entries);
}

// --- Pure helpers (unit-tested) --------------------------------------------

export const CONTACT_METHOD_LABEL: Record<ContactHistoryEntry["method"], string> = {
  self_service: "Changed by the account holder",
  email_added: "Email added",
  admin_approved: "Approved by an Admin",
  lost_number_recovery: "Lost-number recovery",
};

export const CONTACT_FIELD_LABEL: Record<ContactField, string> = {
  mobile: "Phone number",
  email: "Email",
};

/** Which screen a self-service change shows for its server status. */
export function selfServiceStep(
  status: ContactChangeStatus,
): "current-code" | "new-value" | "new-code" | "done" {
  if (status === "awaiting_current_otp") return "current-code";
  if (status === "awaiting_new_value") return "new-value";
  if (status === "awaiting_new_otp") return "new-code";
  return "done";
}

const E164 = /^\+[1-9]\d{6,14}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Client-side shape check only; the API validates again. */
export function newValueError(field: ContactField, value: string): string | null {
  const v = value.trim();
  if (!v) return field === "mobile" ? "Enter the new number." : "Enter the new email.";
  if (field === "mobile") {
    return E164.test(v) ? null : "Enter a valid 10-digit mobile number.";
  }
  return EMAIL.test(v) ? null : "Enter a valid email address.";
}
