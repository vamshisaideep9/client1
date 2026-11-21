"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { AdminContestsView } from "@/features/contests/admin-contests-view";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

export default function ContestApprovalsPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const allowed = session?.role === "admin";
  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [allowed, isLoading, router]);
  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return <AdminContestsView />;
}
