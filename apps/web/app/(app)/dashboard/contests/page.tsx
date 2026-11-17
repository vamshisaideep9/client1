"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { SubAdminContestsView } from "@/features/contests/sub-admin-contests-view";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { isContestId } from "@/lib/contests-api";

/** One address per contest for every role: Sub Admins author here; the Admin
 * reviews in Contest approvals (links keep their `?contest=`). */
export default function ContestsPage() {
  const router = useRouter();
  const search = useSearchParams();
  const { session, isLoading } = useAuth();
  const role = session?.role;

  React.useEffect(() => {
    if (isLoading) return;
    if (role === "admin") {
      const contest = search.get("contest");
      router.replace(
        isContestId(contest)
          ? `/dashboard/contest-approvals?contest=${encodeURIComponent(contest)}`
          : "/dashboard/contest-approvals",
      );
    } else if (role !== "sub_admin") {
      router.replace("/dashboard");
    }
  }, [isLoading, role, router, search]);

  if (isLoading || role !== "sub_admin") return <DashboardPageSkeleton />;
  return <SubAdminContestsView />;
}
