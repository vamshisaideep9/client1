// Personal analytics for Telecallers, Employees, Agents and Sub Admins.
// The server decides the role and scope from the session; the client only
// chooses the period.

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];

export type StaffAnalytics = Schemas["StaffAnalyticsResponse"];
export type AnalyticsKpi = Schemas["AnalyticsKpi"];
export type AnalyticsTrend = Schemas["AnalyticsTrend"];
export type AnalyticsBreakdown = Schemas["AnalyticsBreakdown"];
export type AnalyticsFunnel = Schemas["AnalyticsFunnel"];
export type AnalyticsUnit = AnalyticsKpi["unit"];

export const ANALYTICS_RANGES = [7, 30, 90] as const;
export type AnalyticsRange = (typeof ANALYTICS_RANGES)[number];

export function getMyAnalytics(days: AnalyticsRange): Promise<ApiResponse<StaffAnalytics>> {
  return apiRequest<StaffAnalytics>(`/api/v1/me/analytics?days=${days}`);
}
