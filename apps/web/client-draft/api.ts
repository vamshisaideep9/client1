import { draftResponse, previewNotice } from "./data";
import type { ApiResponse } from "@/lib/api/client";
export type { ApiResponse, ApiValidationIssue } from "@/lib/api/client";

export async function serverFetchJson<T>(path: string): Promise<ApiResponse<T>> {
  const { status, data } = draftResponse(path);
  return status === 200 ? { ok: true, status, data: data as T } : { ok: false, status, error: "Not included in this client draft." };
}

// No writes, credentials, tokens or production API clients enter this bundle.
export async function apiRequest<T>(): Promise<ApiResponse<T>> {
  return { ok: false, status: 0, error: previewNotice };
}
