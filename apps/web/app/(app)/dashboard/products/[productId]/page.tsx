"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";
import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { ProductDashboardView } from "@/features/products/product-dashboard-view";

// One dashboard per product. UX gate only: GET /products/{id}/dashboard gives
// platform Admin every lead and person, a Team Manager with Loans view access
// only their own teams, and everyone else 403.
const PRODUCT_ROLES = new Set(["admin", "sub_admin"]);

export default function ProductDashboardPage() {
  const router = useRouter();
  const params = useParams<{ productId: string }>();
  const { session, isLoading } = useAuth();
  const allowed = session != null && PRODUCT_ROLES.has(session.role);

  React.useEffect(() => {
    if (!isLoading && !allowed) router.replace("/dashboard");
  }, [isLoading, allowed, router]);

  if (isLoading || !allowed) return <DashboardPageSkeleton />;
  return (
    <ProductDashboardView
      productId={params.productId}
      backHref="/dashboard/products"
      backLabel={session?.role === "admin" ? "Products & staffing" : "Products"}
    />
  );
}
