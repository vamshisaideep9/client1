// Read-only transaction history for the authenticated dashboard.

import type { components, paths } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];

export type TransactionType = Schemas["TransactionType"];
export type TransactionStatus = Schemas["TransactionStatus"];
export type TransactionDetail = Schemas["TransactionDetail"];
export type TransactionPage = Schemas["TransactionSearchResponse"];
export type TransactionQuery = NonNullable<
  paths["/api/v1/transactions/search"]["get"]["parameters"]["query"]
>;

export type Transaction = {
  id: string;
  type: TransactionType;
  status: TransactionStatus;
  amountPaise: number;
  currency: string;
  description: string;
  createdAt: string;
};

export function mapTransaction(raw: Schemas["TransactionRead"]): Transaction {
  return {
    id: raw.id,
    type: raw.type,
    status: raw.status,
    amountPaise: raw.amount_paise,
    currency: raw.currency,
    description: raw.description,
    createdAt: raw.created_at,
  };
}

export function getTransactions(query: TransactionQuery) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return apiRequest<TransactionPage>(`/api/v1/transactions/search?${params}`);
}

export function getTransaction(id: string): Promise<ApiResponse<TransactionDetail>> {
  return apiRequest<TransactionDetail>(`/api/v1/transactions/${encodeURIComponent(id)}`);
}
