import type { components } from "@contracts/generated/schema";
import { apiRequest } from "@/lib/api/client";

type S = components["schemas"];
export type CommissionRate = S["CommissionRateRead"];
export type ProductCommissionRates = S["ProductCommissionRates"];
export type CommissionRateInput = S["CommissionRateInput"];
export type AgentCommissionRate = S["AgentCommissionRateRead"];

export const listCommissionRates = () =>
  apiRequest<S["CommissionRateListResponse"]>("/api/v1/commission-rates");
export const getAgentCommissionRates = () =>
  apiRequest<S["AgentCommissionRatesResponse"]>("/api/v1/agent/commission-rates");
export const setCommissionRate = (productId: string, body: CommissionRateInput) =>
  apiRequest<ProductCommissionRates>(`/api/v1/commission-rates/${encodeURIComponent(productId)}`, { method: "PUT", body });
export const approveCommissionRate = (id: string) =>
  apiRequest<ProductCommissionRates>(`/api/v1/commission-rates/${encodeURIComponent(id)}/approve`, { method: "POST" });
export const rejectCommissionRate = (id: string, note: string) =>
  apiRequest<ProductCommissionRates>(`/api/v1/commission-rates/${encodeURIComponent(id)}/reject`, { method: "POST", body: { note } });
export const withdrawCommissionRate = (id: string) =>
  apiRequest<ProductCommissionRates>(`/api/v1/commission-rates/${encodeURIComponent(id)}/withdraw`, { method: "POST" });
