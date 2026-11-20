"use client";

import { AgentLeadBulkView } from "@/features/agent/agent-lead-bulk-view";
import { DashboardRouteGuard } from "@/features/dashboard/dashboard-route-guard";

export default function BulkLeadPage() {
  return <DashboardRouteGuard><AgentLeadBulkView /></DashboardRouteGuard>;
}
