// Personal analytics for Telecallers, Employees, Agents and Sub Admins.
// The server decides the role and scope from the session; the client chooses
// the period (a calendar range) and optional role filters. The business line
// is the dashboard's active line, sent as the X-Business-Line header.

import type { components, operations } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];

export type StaffAnalytics = Schemas["StaffAnalyticsResponse"];
export type AnalyticsKpi = Schemas["AnalyticsKpi"];
export type AnalyticsTrend = Schemas["AnalyticsTrend"];
export type AnalyticsBreakdown = Schemas["AnalyticsBreakdown"];
export type AnalyticsFunnel = Schemas["AnalyticsFunnel"];
export type AnalyticsUnit = AnalyticsKpi["unit"];

// Legacy fixed periods, still accepted by the API (`?days=`).
export const ANALYTICS_RANGES = [7, 30, 90] as const;
export type AnalyticsRange = (typeof ANALYTICS_RANGES)[number];

export function getMyAnalytics(days: AnalyticsRange): Promise<ApiResponse<StaffAnalytics>> {
  return apiRequest<StaffAnalytics>(`/api/v1/me/analytics?days=${days}`);
}

type AnalyticsQuery = NonNullable<operations["my_analytics_api_v1_me_analytics_get"]["parameters"]["query"]>;
type FilterKey = "call_status" | "interest" | "loan_status" | "lead_source" | "lead_status" | "task_type";

/** Optional role filters; the API rejects a filter that doesn't apply to the caller's role. */
export type StaffAnalyticsFilterValues = { [K in FilterKey]?: NonNullable<AnalyticsQuery[K]> };

export function buildMyAnalyticsQuery(
  range: { dateFrom: string; dateTo: string },
  filters: StaffAnalyticsFilterValues = {},
): string {
  const params = new URLSearchParams({ date_from: range.dateFrom, date_to: range.dateTo });
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return params.toString();
}

export function getMyAnalyticsForRange(
  range: { dateFrom: string; dateTo: string },
  filters: StaffAnalyticsFilterValues = {},
): Promise<ApiResponse<StaffAnalytics>> {
  return apiRequest<StaffAnalytics>(`/api/v1/me/analytics?${buildMyAnalyticsQuery(range, filters)}`);
}
