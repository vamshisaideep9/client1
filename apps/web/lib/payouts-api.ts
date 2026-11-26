// Admin payouts client: maker-checker queue (create / approve / reject / list)
// plus the recipient-search picker for the create form.
//
// Thin typed wrapper over /api/v1/payouts via lib/api/client.ts, same pattern
// as lib/admin-api.ts. Wire shape (snake_case, generated) is surfaced as-is.

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];
export type Payout = Schemas["PayoutRead"];
export type PayoutStatus = Schemas["PayoutStatus"];
export type PayoutCreate = Schemas["PayoutCreate"];
export type PayoutRecipient = Schemas["PayoutRecipientRead"];

// GET /payouts requests limit explicitly (see PAYOUT_PAGE_LIMIT) rather than
// relying on the endpoint's own default, so a filter switch and the initial
// load always agree on how much can be truncated.
export const PAYOUT_PAGE_LIMIT = 100;

export async function listPayouts(statusFilter?: string): Promise<ApiResponse<Payout[]>> {
  const params = new URLSearchParams({ limit: String(PAYOUT_PAGE_LIMIT) });
  // NOTE: the query param is `status_filter`, not `status` — getting this
  // wrong silently returns the unfiltered list with no error.
  if (statusFilter) params.set("status_filter", statusFilter);
  const res = await apiRequest<Schemas["PayoutListResponse"]>(`/api/v1/payouts?${params}`);
  if (!res.ok) return res;
  return { ok: true, status: res.status, data: res.data.payouts };
}

export async function createPayout(body: PayoutCreate): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>("/api/v1/payouts", { method: "POST", body });
}

export async function approvePayout(id: string): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/approve`, { method: "POST" });
}

export async function rejectPayout(id: string, reason: string): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/reject`, {
    method: "POST",
    body: { reason },
  });
}

export type SimulatedGatewayEvent = Schemas["PayoutGatewaySimulation"]["event"];

/**
 * Development-only RazorpayX test mode: apply a chosen gateway outcome. The
 * API returns 404 unless the simulator is enabled on a mock-payments server,
 * so the UI only offers it for events listed in `payout.simulate_events`.
 */
export async function simulatePayoutGateway(
  id: string,
  event: SimulatedGatewayEvent,
): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/simulate-gateway`, {
    method: "POST",
    body: { event },
  });
}

export async function issueManualCheque(
  id: string,
  reference: string,
): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/manual/issue`, {
    method: "POST",
    body: { reference },
  });
}

export async function clearManualCheque(id: string): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/manual/clear`, { method: "POST" });
}

export async function failManualCheque(
  id: string,
  reason: string,
): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/manual/fail`, {
    method: "POST",
    body: { reason },
  });
}

export async function reverseManualCheque(
  id: string,
  reason: string,
): Promise<ApiResponse<Payout>> {
  return apiRequest<Payout>(`/api/v1/payouts/${id}/manual/reverse`, {
    method: "POST",
    body: { reason },
  });
}

export async function searchPayoutRecipients(
  q: string,
  businessLine?: "loans" | "real_estate",
): Promise<ApiResponse<PayoutRecipient[]>> {
  const params = new URLSearchParams({ q, limit: "20" });
  if (businessLine) params.set("business_line", businessLine);
  const res = await apiRequest<Schemas["PayoutRecipientListResponse"]>(
    `/api/v1/payouts/recipients?${params}`,
  );
  if (!res.ok) return res;
  return { ok: true, status: res.status, data: res.data.recipients };
}

export type SavedPayoutDestination = Schemas["SavedPayoutDestinationRead"];

/**
 * The bank account / UPI ID an Agent saved, for prefilling one payout. Every
 * call is audited server-side, so only fetch on an explicit maker action.
 */
export async function getSavedPayoutDestination(
  target: { recipientUserUuid: string } | { agentProfileUuid: string },
): Promise<ApiResponse<SavedPayoutDestination>> {
  const path =
    "agentProfileUuid" in target
      ? `/api/v1/payouts/agents/${encodeURIComponent(target.agentProfileUuid)}/saved-destination`
      : `/api/v1/payouts/recipients/${encodeURIComponent(target.recipientUserUuid)}/saved-destination`;
  return apiRequest<SavedPayoutDestination>(path);
}

export type CancelledCheque = Schemas["CancelledChequeRead"];

/**
 * A short-lived link to the cancelled cheque an Agent attached to their payout
 * details. Same access as the saved-destination prefill; every view is audited.
 */
export async function getCancelledCheque(
  target: { recipientUserUuid: string } | { agentProfileUuid: string },
): Promise<ApiResponse<CancelledCheque>> {
  const path =
    "agentProfileUuid" in target
      ? `/api/v1/payouts/agents/${encodeURIComponent(target.agentProfileUuid)}/cancelled-cheque`
      : `/api/v1/payouts/recipients/${encodeURIComponent(target.recipientUserUuid)}/cancelled-cheque`;
  return apiRequest<CancelledCheque>(path);
}
