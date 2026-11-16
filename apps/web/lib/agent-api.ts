// Agent client — home summary, lead introduction/tracking (Agent Dashboard slice 1).
//
// Thin typed wrapper over /api/v1/agent via lib/api/client.ts, same pattern
// as lib/telecaller-api.ts. Wire shape (snake_case, generated) is surfaced as-is.

import type { components } from "@contracts/generated/schema";

import { uploadFileToPresignedPost } from "@/lib/agent-application";
import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];
export type AgentHome = Schemas["AgentHomeResponse"];
export type AgentLead = Schemas["AgentLeadRead"];
export type AgentLeadCreate = Schemas["AgentLeadCreate"];
export type AgentLeadUpdate = Schemas["AgentLeadUpdate"];
export type AgentEarnings = Schemas["AgentEarningsResponse"];
export type AgentEarningsRow = Schemas["AgentEarningsRow"];
export type AgentTransactionDetail = Schemas["AgentTransactionDetail"];
export type AgentPayoutActor = Schemas["AgentPayoutActor"];
export type AgentLeadHistory = Schemas["AgentLeadHistoryRead"];

export async function getAgentHome(): Promise<ApiResponse<AgentHome>> {
  return apiRequest<AgentHome>("/api/v1/agent/home");
}

/** Every commission on the Agent's line; the history page filters these rows. */
export async function getAgentEarnings(): Promise<ApiResponse<AgentEarnings>> {
  return apiRequest<AgentEarnings>("/api/v1/agent/earnings");
}

/** One of the Agent's own transactions with its payout trail. */
export async function getAgentTransaction(
  transactionId: string,
): Promise<ApiResponse<AgentTransactionDetail>> {
  return apiRequest<AgentTransactionDetail>(
    `/api/v1/agent/transactions/${encodeURIComponent(transactionId)}`,
  );
}

/** Applications, deals, calls and timeline of a lead this Agent introduced. */
export async function getAgentLeadHistory(leadId: string): Promise<ApiResponse<AgentLeadHistory>> {
  return apiRequest<AgentLeadHistory>(`/api/v1/agent/leads/${encodeURIComponent(leadId)}/history`);
}

export async function listAgentLeads(statusFilter?: string): Promise<ApiResponse<AgentLead[]>> {
  const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return apiRequest<AgentLead[]>(`/api/v1/agent/leads${query}`);
}

export async function getAgentLead(leadId: string): Promise<ApiResponse<AgentLead>> {
  return apiRequest<AgentLead>(`/api/v1/agent/leads/${leadId}`);
}

export async function introduceAgentLead(
  payload: AgentLeadCreate,
): Promise<ApiResponse<AgentLead>> {
  return apiRequest<AgentLead>("/api/v1/agent/leads", { method: "POST", body: payload });
}

export async function updateAgentLead(
  leadId: string,
  payload: AgentLeadUpdate,
): Promise<ApiResponse<AgentLead>> {
  return apiRequest<AgentLead>(`/api/v1/agent/leads/${leadId}`, { method: "PATCH", body: payload });
}

/** Restart this Agent's 30-day window on their expired, unregistered lead. */
export async function resubmitAgentLead(leadId: string): Promise<ApiResponse<AgentLead>> {
  return apiRequest<AgentLead>(`/api/v1/agent/leads/${leadId}/resubmit`, { method: "POST" });
}

export type AgentPayoutDetails = Schemas["AgentPayoutDetailsRead"];
export type AgentPayoutDetailsUpdate = Schemas["AgentPayoutDetailsUpdate"];
export type AgentBankAccount = Schemas["AgentBankAccount"];

/** The Agent's saved payout destination, masked. */
export async function getAgentPayoutDetails(): Promise<ApiResponse<AgentPayoutDetails>> {
  return apiRequest<AgentPayoutDetails>("/api/v1/agent/payout-details");
}

/** Partial update: omit a field to keep it, send null to remove it. */
export async function saveAgentPayoutDetails(
  payload: AgentPayoutDetailsUpdate,
): Promise<ApiResponse<AgentPayoutDetails>> {
  return apiRequest<AgentPayoutDetails>("/api/v1/agent/payout-details", {
    method: "PUT",
    body: payload,
  });
}

export async function deleteAgentPayoutDetails(): Promise<ApiResponse<unknown>> {
  return apiRequest<unknown>("/api/v1/agent/payout-details", { method: "DELETE" });
}

export type AgentChequeContentType = Schemas["AgentChequePresignRequest"]["content_type"];

/**
 * Optional cancelled cheque: presign -> direct-to-storage POST -> confirm,
 * the same sequence as client loan documents. The API re-checks the size and
 * the file's bytes on confirmation.
 */
export async function uploadAgentCheque(file: File): Promise<ApiResponse<AgentPayoutDetails>> {
  const contentType = file.type as AgentChequeContentType;
  const presign = await apiRequest<Schemas["AgentChequePresignResponse"]>(
    "/api/v1/agent/payout-details/cheque/presign",
    { method: "POST", body: { content_type: contentType } },
  );
  if (!presign.ok) return presign;
  const { object_key, upload_url, fields } = presign.data;
  const upload = await uploadFileToPresignedPost(upload_url, fields, file);
  if (!upload.ok) {
    return { ok: false, status: 0, error: "The upload didn't finish. Check your connection and try again." };
  }
  return apiRequest<AgentPayoutDetails>("/api/v1/agent/payout-details/cheque", {
    method: "PUT",
    body: { object_key, content_type: contentType },
  });
}

export async function deleteAgentCheque(): Promise<ApiResponse<unknown>> {
  return apiRequest<unknown>("/api/v1/agent/payout-details/cheque", { method: "DELETE" });
}
