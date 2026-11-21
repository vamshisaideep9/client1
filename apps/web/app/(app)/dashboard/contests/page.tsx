"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { MyContestsView } from "@/features/contests/my-contests-view";
import { SubAdminContestsView } from "@/features/contests/sub-admin-contests-view";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { isContestId } from "@/lib/contests-api";

const PARTICIPANTS = new Set(["agent", "telecaller", "employee"]);

/** One address per contest for every role: Sub Admins author here,
 * participants follow their contests here, and the Admin reviews in Contest
 * approvals (links keep their `?contest=`). */
export default function ContestsPage() {
  const router = useRouter();
  const search = useSearchParams();
  const { session, isLoading } = useAuth();
  const role = session?.role;
  const allowed = role === "sub_admin" || (role !== undefined && PARTICIPANTS.has(role));

  React.useEffect(() => {
    if (isLoading) return;
    if (role === "admin") {
      const contest = search.get("contest");
      router.replace(
        isContestId(contest)
          ? `/dashboard/contest-approvals?contest=${encodeURIComponent(contest)}`
          : "/dashboard/contest-approvals",
      );
    } else if (!allowed) {
      router.replace("/dashboard");
    }
  }, [allowed, isLoading, role, router, search]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return role === "sub_admin" ? <SubAdminContestsView /> : <MyContestsView />;
}
