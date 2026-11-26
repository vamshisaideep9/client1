// Product specialist dashboards (2026-11-26). The API derives every scope from
// the verified token: platform Admin sees all products and people; a Team
// Manager sees only their own Loans teams. These wrappers carry no
// authorization of their own.

import type { components } from "@contracts/generated/schema";

import { apiRequest, type ApiResponse } from "@/lib/api/client";

type Schemas = components["schemas"];

export type ProductStaffing = Schemas["ProductStaffingResponse"];
export type ProductStaffingRow = Schemas["ProductStaffingRow"];
export type ProductStaffPerson = Schemas["ProductStaffPerson"];
export type ProductCoverage = ProductStaffingRow["coverage"];
export type ManagerProducts = Schemas["ManagerProductsResponse"];
export type ManagerProductRow = Schemas["ManagerProductRow"];
export type ProductDashboard = Schemas["ProductDashboardResponse"];
export type ProductStaffRow = Schemas["ProductStaffRow"];
export type ProductCategory = Schemas["ProductRef"]["category"];

export function getProductStaffing(): Promise<ApiResponse<ProductStaffing>> {
  return apiRequest<ProductStaffing>("/api/v1/admin/product-staffing");
}

export function getManagerProducts(): Promise<ApiResponse<ManagerProducts>> {
  return apiRequest<ManagerProducts>("/api/v1/manager/products");
}

/** `days` is 7, 30 or 90 IST days ending today. */
export function getProductDashboard(productId: string, days: number): Promise<ApiResponse<ProductDashboard>> {
  const params = new URLSearchParams({ days: String(days) });
  return apiRequest<ProductDashboard>(
    `/api/v1/products/${encodeURIComponent(productId)}/dashboard?${params.toString()}`,
  );
}
