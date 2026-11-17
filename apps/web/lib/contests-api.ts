// Contests client (CS-027): Sub Admin authoring, platform Admin review and
// prizes, and the participant pages. Thin typed wrapper over /api/v1/contests
// and /api/v1/my-contests; wire shapes are the generated contract types.

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];
export type Contest = Schemas["ContestRead"];
export type ContestDefinition = Schemas["ContestDefinition"];
export type ContestCriteria = Schemas["ContestCriteria"];
export type ContestStatus = Schemas["ContestStatus"];
export type ContestAudience = Schemas["ContestAudience"];
export type ContestMetric = Schemas["ContestMetric"];
export type ContestWinMode = Schemas["ContestWinMode"];
export type ContestStandings = Schemas["ContestStandingsResponse"];
export type StandingRow = Schemas["StandingRow"];
export type ContestProgress = Schemas["ContestProgress"];
export type MyContestSummary = Schemas["MyContestSummary"];
export type MyContestDetail = Schemas["MyContestDetail"];
export type LeaderboardEntry = Schemas["LeaderboardEntry"];
export type ContestPrizePayoutRequest = Schemas["ContestPrizePayoutRequest"];

export type ContestListQuery = {
  status?: ContestStatus[];
  audience?: ContestAudience;
  businessLine?: "loans" | "real_estate";
  q?: string;
  mine?: boolean;
};

export const CONTEST_PAGE_LIMIT = 200;

export async function listContests(query: ContestListQuery = {}): Promise<ApiResponse<Contest[]>> {
  const params = new URLSearchParams({ limit: String(CONTEST_PAGE_LIMIT) });
  for (const status of query.status ?? []) params.append("status", status);
  if (query.audience) params.set("audience", query.audience);
  if (query.businessLine) params.set("business_line", query.businessLine);
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.mine) params.set("mine", "true");
  const res = await apiRequest<Schemas["ContestListResponse"]>(`/api/v1/contests?${params}`);
  if (!res.ok) return res;
  return { ok: true, status: res.status, data: res.data.contests };
}

export function getContest(id: string): Promise<ApiResponse<Contest>> {
  return apiRequest<Contest>(`/api/v1/contests/${id}`);
}

export function createContest(body: ContestDefinition): Promise<ApiResponse<Contest>> {
  return apiRequest<Contest>("/api/v1/contests", { method: "POST", body });
}

export function updateContest(id: string, body: ContestDefinition): Promise<ApiResponse<Contest>> {
  return apiRequest<Contest>(`/api/v1/contests/${id}`, { method: "PUT", body });
}

export function deleteContest(id: string): Promise<ApiResponse<unknown>> {
  return apiRequest<unknown>(`/api/v1/contests/${id}`, { method: "DELETE" });
}

function command(id: string, action: string, body?: unknown): Promise<ApiResponse<Contest>> {
  return apiRequest<Contest>(`/api/v1/contests/${id}/${action}`, {
    method: "POST",
    ...(body === undefined ? {} : { body }),
  });
}

export const submitContest = (id: string) => command(id, "submit");
export const withdrawContest = (id: string) => command(id, "withdraw");
export const cancelContest = (id: string, reason: string) => command(id, "cancel", { reason });
export const approveContest = (id: string) => command(id, "approve");
export const rejectContest = (id: string, note: string) => command(id, "reject", { note });
export const recalculateContest = (id: string) => command(id, "recalculate");
export const finalizeContest = (id: string) => command(id, "finalize");

export function getStandings(id: string): Promise<ApiResponse<ContestStandings>> {
  return apiRequest<ContestStandings>(`/api/v1/contests/${id}/standings`);
}

export function requestPrizePayout(
  contestId: string,
  resultId: string,
  body: ContestPrizePayoutRequest,
): Promise<ApiResponse<Schemas["ContestPrizePayoutResponse"]>> {
  return apiRequest<Schemas["ContestPrizePayoutResponse"]>(
    `/api/v1/contests/${contestId}/results/${resultId}/payout`,
    { method: "POST", body },
  );
}

export function markPrizePaid(
  contestId: string,
  resultId: string,
  reference: string,
): Promise<ApiResponse<Schemas["ContestResultPayment"]>> {
  return apiRequest<Schemas["ContestResultPayment"]>(
    `/api/v1/contests/${contestId}/results/${resultId}/mark-paid`,
    { method: "POST", body: { reference } },
  );
}

export async function listMyContests(): Promise<ApiResponse<MyContestSummary[]>> {
  const res = await apiRequest<Schemas["MyContestListResponse"]>("/api/v1/my-contests");
  if (!res.ok) return res;
  return { ok: true, status: res.status, data: res.data.contests };
}

export function getMyContest(id: string): Promise<ApiResponse<MyContestDetail>> {
  return apiRequest<MyContestDetail>(`/api/v1/my-contests/${id}`);
}
