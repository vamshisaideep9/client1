"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { StaffAnalyticsView } from "@/features/analytics/staff-analytics-view";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

// Personal analytics for Telecallers, Employees, Agents and Sub Admins. A UX
// gate only: GET /api/v1/me/analytics scopes every number to the session.
const INSIGHT_ROLES = new Set(["telecaller", "employee", "agent", "sub_admin"]);

export default function InsightsPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const allowed = session != null && INSIGHT_ROLES.has(session.role);

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return <StaffAnalyticsView />;
}
