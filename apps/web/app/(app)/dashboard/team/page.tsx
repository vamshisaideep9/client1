"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { MyTeamView } from "@/features/team/my-team-view";

// Sub Admin route. UX gate only: /api/v1/manager scopes everything to the
// caller's own live teams, and RLS limits rows to those teams' members.
export default function MyTeamPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const allowed = session?.role === "sub_admin";

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return <MyTeamView />;
}
