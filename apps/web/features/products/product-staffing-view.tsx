"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, Layers, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
  MetricCard,
  MetricGrid,
} from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { FetchError } from "@/features/dashboard/fetch-error";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { PRODUCT_CATEGORY_LABEL } from "@/features/dashboard/product-specialty";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { useLoad } from "@/features/team/use-load";
import {
  getProductStaffing,
  type ProductStaffPerson,
  type ProductStaffingRow,
} from "@/lib/product-dashboards-api";

import { AssignSpecialistDialog } from "./assign-specialist-dialog";
import {
  ACTIVE_OPTIONS,
  CATEGORY_OPTIONS,
  COVERAGE_LABEL,
  COVERAGE_OPTIONS,
  COVERAGE_TONE,
  DEFAULT_STAFFING_FILTERS,
  addSpecialistHref,
  compareStaffingRows,
  filterStaffingRows,
  productDashboardHref,
  type StaffingFilters,
} from "./product-coverage";

const LINE_LABEL: Record<string, string> = { loans: "Loans", both: "Both lines", real_estate: "Real Estate" };

function People({ people, role }: { people: readonly ProductStaffPerson[]; role: string }) {
  if (people.length === 0) return <span className="text-text-secondary">No {role}</span>;
  return (
    <ul className="space-y-0.5">
      {people.map((person) => (
        <li key={person.staff_profile_uuid} className="min-w-0">
          <span className="text-text-primary">{person.first_name} {person.last_name}</span>{" "}
          <span className="font-mono text-xs text-text-secondary">{person.staff_code}</span>
          {person.status !== "active" ? (
            <span className="ml-1 text-xs text-warning">({person.status === "suspended" ? "suspended" : "inactive"})</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Admin's Products index: every product's specialists, waiting work and coverage. */
export function ProductStaffingView() {
  const router = useRouter();
  const { state, retry } = useLoad(getProductStaffing, []);
  const [filters, setFilters] = React.useState<StaffingFilters>(DEFAULT_STAFFING_FILTERS);
  const [assigning, setAssigning] = React.useState<ProductStaffingRow | null>(null);
  const data = state.status === "ready" ? state.data : null;
  const rows = React.useMemo(
    () => (data ? filterStaffingRows(data.products, filters).sort(compareStaffingRows) : []),
    [data, filters],
  );
  const patch = (next: Partial<StaffingFilters>) => setFilters((current) => ({ ...current, ...next }));
  const filtered =
    filters.search !== "" ||
    filters.category !== DEFAULT_STAFFING_FILTERS.category ||
    filters.coverage !== DEFAULT_STAFFING_FILTERS.coverage ||
    filters.active !== DEFAULT_STAFFING_FILTERS.active;

  const columns: DataColumn<ProductStaffingRow>[] = [
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
    { key: "telecallers", header: "Telecallers", render: (row) => <People people={row.telecallers ?? []} role="Telecaller" /> },
    { key: "officers", header: "Officers", render: (row) => <People people={row.officers ?? []} role="Officer" /> },
    { key: "open_leads", header: "Open leads", align: "right", render: (row) => <span className="tabular-nums">{row.open_leads ?? 0}</span> },
    {
      key: "unassigned",
      header: "Unassigned",
      align: "right",
      render: (row) => (
        <span className={(row.unassigned_leads ?? 0) > 0 ? "font-medium tabular-nums text-warning" : "tabular-nums"}>
          {row.unassigned_leads ?? 0}
        </span>
      ),
    },
    { key: "open_tasks", header: "Open tasks", align: "right", render: (row) => <span className="tabular-nums">{row.open_tasks ?? 0}</span> },
    {
      key: "coverage",
      header: "Coverage",
      render: (row) => <StatusBadge tone={COVERAGE_TONE[row.coverage ?? "none"]}>{COVERAGE_LABEL[row.coverage ?? "none"]}</StatusBadge>,
    },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          {row.active !== false ? (
            <>
              <Button asChild size="sm" variant="outline">
                <Link href={addSpecialistHref("telecaller", row.product_id)}>Add Telecaller</Link>
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link href={addSpecialistHref("employee", row.product_id)}>Add Officer</Link>
              </Button>
              <Button size="sm" variant="outline" onClick={() => setAssigning(row)}>
                Assign existing
              </Button>
            </>
          ) : null}
          <Button asChild size="sm" variant="ghost">
            <Link href={productDashboardHref(row.product_id)}>
              Open dashboard<span className="sr-only"> for {row.label}</span>
            </Link>
          </Button>
        </div>
      ),
    },
  ];

  return (
    <DashboardPage>
      <DashboardHeader
        title="Products & staffing"
        description="Which Telecallers and Officers cover each financial product, and where work is waiting."
        actions={
          <Button asChild>
            <Link href="/dashboard/users">
              <UserPlus className="h-4 w-4" aria-hidden="true" />
              Users & staff
            </Link>
          </Button>
        }
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : !data ? (
        <ListLoadingState rows={6} />
      ) : (
        <>
          <MetricGrid>
            <MetricCard label="Active products" value={data.summary.active_products ?? 0} icon={Layers} />
            <MetricCard
              label="Fully staffed"
              value={`${data.summary.fully_covered ?? 0} of ${data.summary.active_products ?? 0}`}
              icon={CheckCircle2}
              hint="A specialist Telecaller and Officer each"
            />
            <MetricCard label="Open product leads" value={data.summary.open_leads ?? 0} icon={DASHBOARD_ICONS.leads} />
            <MetricCard
              label="Unassigned leads"
              value={data.summary.unassigned_leads ?? 0}
              icon={AlertTriangle}
              attention={(data.summary.unassigned_leads ?? 0) > 0}
              hint="New or released, no Telecaller yet"
            />
          </MetricGrid>

          {(data.summary.unspecialised ?? []).length > 0 ? (
            <DashboardPanel title="Unspecialised staff" description="Active people without a product. They keep covering every product on their line.">
              <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                {(data.summary.unspecialised ?? []).map((item) => (
                  <li key={item.business_line} className="text-text-secondary">
                    <span className="font-medium text-text-primary">{LINE_LABEL[item.business_line] ?? item.business_line}:</span>{" "}
                    <span className="tabular-nums">{item.telecallers ?? 0}</span>{" "}
                    {(item.telecallers ?? 0) === 1 ? "Telecaller" : "Telecallers"} ·{" "}
                    <span className="tabular-nums">{item.officers ?? 0}</span>{" "}
                    {(item.officers ?? 0) === 1 ? "Officer" : "Officers"}
                  </li>
                ))}
              </ul>
            </DashboardPanel>
          ) : null}

          <DashboardPanel title="Products" description="Gaps first. Open a product for its dashboard." bodyClassName="p-0">
            <div className="grid gap-3 border-b border-border p-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_auto]">
              <div className="space-y-1">
                <Label htmlFor="product-staffing-search" className="sr-only">Search products</Label>
                <Input
                  id="product-staffing-search"
                  type="search"
                  placeholder="Search products"
                  value={filters.search}
                  onChange={(event) => patch({ search: event.target.value })}
                />
              </div>
              <FilterSelect label="Category" value={filters.category} onValueChange={(category) => patch({ category })} options={CATEGORY_OPTIONS} />
              <FilterSelect label="Coverage" value={filters.coverage} onValueChange={(coverage) => patch({ coverage })} options={COVERAGE_OPTIONS} />
              <FilterSelect label="Status" value={filters.active} onValueChange={(active) => patch({ active })} options={ACTIVE_OPTIONS} />
              <Button type="button" variant="ghost" disabled={!filtered} onClick={() => setFilters(DEFAULT_STAFFING_FILTERS)}>
                Reset
              </Button>
            </div>
            {rows.length === 0 ? (
              <div className="p-4">
                <ListEmptyState
                  icon={Layers}
                  title={data.products.length === 0 ? "No products in the catalogue" : "No products match these filters"}
                  description={data.products.length === 0 ? "Add financial products from Loan configuration first." : "Change or reset the filters to see more products."}
                />
              </div>
            ) : (
              <DataTable
                columns={columns}
                rows={rows}
                rowKey={(row) => row.product_id}
                onRowClick={(row) => router.push(productDashboardHref(row.product_id))}
                rowActionLabel="Open dashboard"
                minWidth="min-w-[1080px]"
              />
            )}
          </DashboardPanel>
          <AssignSpecialistDialog
            product={assigning}
            available={data.available ?? []}
            onOpenChange={(open) => !open && setAssigning(null)}
            onAssigned={retry}
          />
        </>
      )}
    </DashboardPage>
  );
}
