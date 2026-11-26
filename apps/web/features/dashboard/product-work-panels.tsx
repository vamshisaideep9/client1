import Link from "next/link";
import { AlertTriangle, CheckCircle2, Layers } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { DashboardPanel, MetricCard } from "./dashboard-ui";
import {
  PRODUCT_CATEGORY_LABEL,
  productListHref,
  specialistTitle,
  splitProductCounts,
  type ProductWorkCount,
} from "./product-specialty";

type Specialty = { product_id: string; label: string; category: string } | null | undefined;
type WorkKind = "leads" | "tasks";

const COPY: Record<WorkKind, { list: string; open: string; done: string; doneKey: "converted_30d" | "completed_30d"; overdue: string }> = {
  leads: {
    list: "/dashboard/leads",
    open: "Open leads",
    done: "Converted (30 days)",
    doneKey: "converted_30d",
    overdue: "Follow-ups overdue",
  },
  tasks: {
    list: "/dashboard/tasks",
    open: "Open tasks",
    done: "Completed (30 days)",
    doneKey: "completed_30d",
    overdue: "Overdue tasks",
  },
};

/** The header chip on a specialist's home, e.g. "Home Loan specialist". */
export function SpecialtyChip({ specialty }: { specialty: Specialty }) {
  if (!specialty) return null;
  return <Badge variant="secondary">{specialistTitle(specialty.label)}</Badge>;
}

/**
 * "My product" (the specialty's own counts) and the breakdown of every other
 * product the caller holds work for. Unspecialised staff see only the
 * breakdown. Counts cover the caller's own Loans work.
 */
export function ProductWorkPanels({
  kind,
  specialty,
  counts,
}: {
  kind: WorkKind;
  specialty: Specialty;
  counts: readonly ProductWorkCount[] | null | undefined;
}) {
  const copy = COPY[kind];
  const { mine, others } = splitProductCounts(counts, specialty?.product_id);
  const href = productListHref(copy.list, specialty?.product_id);
  return (
    <>
      {specialty ? (
        <DashboardPanel
          title="My product"
          description={`New ${kind === "leads" ? "leads" : "field tasks"} for ${specialty.label} (${(PRODUCT_CATEGORY_LABEL[specialty.category] ?? "product").toLowerCase()}) come to you first.`}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricCard label={copy.open} value={mine?.open ?? 0} icon={Layers} href={href} />
            <MetricCard
              label={copy.overdue}
              value={mine?.overdue ?? 0}
              icon={AlertTriangle}
              href={href}
              attention={(mine?.overdue ?? 0) > 0}
            />
            <MetricCard label={copy.done} value={mine?.[copy.doneKey] ?? 0} icon={CheckCircle2} href={href} />
          </div>
        </DashboardPanel>
      ) : null}
      {others.length > 0 ? (
        <DashboardPanel
          title={specialty ? "Other products" : "Work by product"}
          description={
            specialty
              ? "Work for products without an active specialist, shared across the line."
              : "Your open work grouped by the product each lead is about."
          }
        >
          <ul className="divide-y divide-border">
            {others.map((row) => (
              <li key={row.product_id ?? "none"} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-sm first:pt-0 last:pb-0">
                {row.product_id ? (
                  <Link
                    href={productListHref(copy.list, row.product_id)}
                    className="min-w-0 break-words font-medium text-brand-link underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {row.label ?? "Unnamed product"}
                  </Link>
                ) : (
                  <span className="min-w-0 font-medium text-text-primary">No product recorded</span>
                )}
                <span className="flex flex-wrap gap-x-4 gap-y-1 tabular-nums text-text-secondary">
                  <span>{row.open ?? 0} open</span>
                  <span className={(row.overdue ?? 0) > 0 ? "font-medium text-warning" : undefined}>{row.overdue ?? 0} overdue</span>
                  <span>{row[copy.doneKey] ?? 0} {kind === "leads" ? "converted" : "completed"}</span>
                </span>
              </li>
            ))}
          </ul>
        </DashboardPanel>
      ) : null}
    </>
  );
}
