"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

import { useAuth } from "@/components/auth/session-provider";
import { PayoutsView } from "@/features/admin/payouts-view";
import { useMe } from "@/features/dashboard/me-provider";
import { assignedLines } from "@/lib/sub-admin-access";

// AppGuard already enforces auth; this adds the Admin-or-granted-Sub-Admin UX
// gate. The API dependency and payout RLS policy remain the authorization wall.

export default function PayoutsPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const { me } = useMe();
  const allowed =
    session != null &&
    (session.role === "admin" ||
      (session.role === "sub_admin" && (me?.subAdminAccess
        ? assignedLines(me.subAdminAccess, "account_manager", "view").length > 0
        : session.staffFeatures.includes("payout_requests"))));

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) {
    return (
      <DashboardPageSkeleton />
    );
  }
  return <PayoutsView />;
}
