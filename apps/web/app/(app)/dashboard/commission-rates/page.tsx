"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { CommissionRatesView } from "@/features/admin/commission-rates-view";
import { DashboardRouteGuard } from "@/features/dashboard/dashboard-route-guard";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";

export default function CommissionRatesPage() {
  return <DashboardRouteGuard><Suspense fallback={<DashboardPageSkeleton />}><RatesPage /></Suspense></DashboardRouteGuard>;
}
function RatesPage() {
  const search = useSearchParams();
  return <CommissionRatesView productId={search.get("product") || undefined} />;
}
