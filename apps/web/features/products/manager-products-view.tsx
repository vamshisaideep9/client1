"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Layers } from "lucide-react";

import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { PRODUCT_CATEGORY_LABEL } from "@/features/dashboard/product-specialty";
import { useLoad } from "@/features/team/use-load";
import { getManagerProducts, type ManagerProductRow } from "@/lib/product-dashboards-api";

import { productDashboardHref } from "./product-coverage";

/** A Team Manager's Products index: their Loans teams' products, read-only. */
export function ManagerProductsView() {
  const router = useRouter();
  const { state, retry } = useLoad(getManagerProducts, []);
  const columns: DataColumn<ManagerProductRow>[] = [
    {
      key: "product",
      header: "Product",
      render: (row) => (
        <DataTablePrimaryCell
          title={row.label}
          subtitle={`${PRODUCT_CATEGORY_LABEL[row.category] ?? row.category}${row.active === false ? " · inactive" : ""}`}
        />
      ),
    },
    { key: "specialists", header: "Team specialists", align: "right", render: (row) => <span className="tabular-nums">{row.specialists ?? 0}</span> },
    { key: "open_leads", header: "Open leads", align: "right", render: (row) => <span className="tabular-nums">{row.open_leads ?? 0}</span> },
    { key: "open_tasks", header: "Open tasks", align: "right", render: (row) => <span className="tabular-nums">{row.open_tasks ?? 0}</span> },
  ];

  return (
    <DashboardPage>
      <DashboardHeader
        title="Products"
        description="Products your Loans team members specialise in or are working on. Open one for its dashboard."
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : state.status === "loading" ? (
        <ListLoadingState rows={4} />
      ) : state.data.products.length === 0 ? (
        <ListEmptyState
          icon={Layers}
          title="No team products yet"
          description="Products appear here once a member of your Loans team specialises in one or holds work for it."
        />
      ) : (
        <DashboardPanel title="Team products" bodyClassName="p-0">
          <DataTable
            columns={columns}
            rows={state.data.products}
            rowKey={(row) => row.product_id}
            onRowClick={(row) => router.push(productDashboardHref(row.product_id))}
            rowActionLabel="Open dashboard"
          />
        </DashboardPanel>
      )}
    </DashboardPage>
  );
}
