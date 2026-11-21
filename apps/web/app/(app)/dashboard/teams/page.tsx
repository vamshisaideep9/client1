"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { TeamsView } from "@/features/admin/teams/teams-view";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

// Admin-only route. UX gate only: GET /api/v1/admin/teams requires a platform
// Admin and every write requires the Main Admin, in the API and in RLS.
export default function TeamsPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const allowed = session?.role === "admin";

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return <TeamsView />;
}
