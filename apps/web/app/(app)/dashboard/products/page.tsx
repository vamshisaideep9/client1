"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { ManagerProductsView } from "@/features/products/manager-products-view";
import { ProductStaffingView } from "@/features/products/product-staffing-view";

// Admin and Team Manager route. UX gate only: GET /admin/product-staffing
// requires a platform Admin, and GET /manager/products a Team Manager with
// Loans view access; the API and RLS derive each scope from the token.
const PRODUCT_ROLES = new Set(["admin", "sub_admin"]);

export default function ProductsPage() {
  const router = useRouter();
  const { session, isLoading } = useAuth();
  const allowed = session != null && PRODUCT_ROLES.has(session.role);

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return session?.role === "admin" ? <ProductStaffingView /> : <ManagerProductsView />;
}
