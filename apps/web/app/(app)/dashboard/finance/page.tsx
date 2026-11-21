"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

import { useAuth } from "@/components/auth/session-provider";
import { FinanceOverview } from "@/features/sub-admin/finance-overview";
import { ScopedFinanceOverview } from "@/features/sub-admin/scoped-finance-overview";
import { useMe } from "@/features/dashboard/me-provider";

export default function FinancePage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const { me } = useMe();
  const allowed = session?.role === "sub_admin";

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [allowed, isLoading, router]);

  if (isLoading || !allowed) {
    return (
      <DashboardPageSkeleton />
    );
  }
  return me?.subAdminAccess ? <ScopedFinanceOverview /> : <FinanceOverview />;
}
