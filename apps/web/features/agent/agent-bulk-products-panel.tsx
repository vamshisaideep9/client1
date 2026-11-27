"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { getAgentLeadBulkProducts, type AgentLeadBulkProducts } from "@/lib/agent-api";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: AgentLeadBulkProducts };

/**
 * The choices the Requirement column accepts, from the same catalogue the
 * upload matches against: active loans, credit cards and insurance products on
 * the Loans line, or property types on Real Estate. Write a name or a code.
 */
export function AgentBulkProductsPanel() {
  const [state, setState] = React.useState<State>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    const response = await getAgentLeadBulkProducts();
    setState(response.ok ? { status: "ready", data: response.data } : { status: "error", message: response.error });
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const realEstate = state.status === "ready" && state.data.business_line === "real_estate";
  return (
    <DashboardPanel
      id="bulk-products"
      title={realEstate ? "Property types" : "Active products"}
      description={
        realEstate
          ? "Write one of these in the Requirement column, by name or code."
          : "Only these products are accepted in the Requirement column. Write a product name or its code."
      }
    >
      {state.status === "loading" ? (
        <div role="status" aria-label="Loading active products" className="space-y-2">
          <Skeleton className="h-5 w-32 rounded" />
          <Skeleton className="h-8 w-full max-w-md rounded-full" />
        </div>
      ) : state.status === "error" ? (
        <div role="alert" className="space-y-2 text-sm">
          <p className="text-text-secondary">Couldn&apos;t load your active products. {state.message}</p>
          <Button size="sm" variant="outline" onClick={() => void load()}>Try again</Button>
        </div>
      ) : state.data.groups.length === 0 ? (
        <p className="text-sm text-text-secondary">No products are active right now, so leave the Requirement column empty.</p>
      ) : (
        <div className="space-y-4">
          {state.data.groups.map((group) => (
            <section key={group.category} aria-labelledby={`bulk-products-${group.category}`}>
              <h3 id={`bulk-products-${group.category}`} className="mb-2 text-sm font-semibold text-text-primary">
                {group.label} <span className="font-normal text-text-secondary">({group.products.length})</span>
              </h3>
              <ul className="flex flex-wrap gap-2" aria-label={group.label}>
                {group.products.map((product) => (
                  <li
                    key={product.code}
                    className="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs"
                  >
                    <span className="truncate font-medium text-text-primary">{product.label}</span>
                    <code className="truncate text-[11px] text-text-secondary" aria-label={`code ${product.code}`}>
                      {product.code}
                    </code>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </DashboardPanel>
  );
}
