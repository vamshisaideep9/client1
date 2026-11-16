"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { TeamMemberView } from "@/features/team/team-member-view";

// Sub Admin route. UX gate only: the manager API resolves the team against
// the caller's own staff profile and refuses anyone outside it.
export default function TeamMemberPage() {
  const router = useRouter();
  const params = useParams<{ teamId: string; memberId: string }>();
  const { session, isLoading } = useAuth();
  const allowed = session?.role === "sub_admin";

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return <TeamMemberView teamId={params.teamId} memberId={params.memberId} />;
}
