"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StatusBadge } from "@/features/dashboard/status-badge";
import type { AgentEarningsRow } from "@/lib/agent-api";
import { formatPaise } from "@/lib/format";

import {
  COMMISSION_STATUS_LABEL,
  DEAL_TYPE_LABEL,
  LEAD_STATUS_LABEL,
  humanizeStatus,
} from "./agent-earnings-filters";
import { formatDealAmount, formatWhen } from "./agent-history-format";

const STATUS_TONE = { pending: "warning", paid: "success", cancelled: "neutral" } as const;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-sm">
      <dt className="text-text-secondary">{label}</dt>
      <dd className="min-w-0 text-right font-medium break-words text-text-primary">{children}</dd>
    </div>
  );
}

/** One commission's client, deal and payment, in a side sheet. */
export function CommissionDetailSheet({
  row,
  hiddenFields,
  onOpenChange,
  onOpenTransaction,
}: {
  row: AgentEarningsRow | null;
  hiddenFields: readonly string[];
  onOpenChange: (open: boolean) => void;
  onOpenTransaction: (transactionId: string) => void;
}) {
  return (
    <Sheet open={row !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Commission details</SheetTitle>
          <SheetDescription>The client, the deal and how this commission was paid.</SheetDescription>
        </SheetHeader>
        {row ? (
          <div className="mt-4 space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-2xl font-semibold tabular-nums text-brand-heading">
                {formatPaise(row.agreed_amount_paise)}
              </span>
              <StatusBadge tone={STATUS_TONE[row.status]}>
                {COMMISSION_STATUS_LABEL[row.status] ?? row.status}
              </StatusBadge>
            </div>
            <section aria-labelledby="commission-client" className="rounded-lg border border-border p-3">
              <h3 id="commission-client" className="text-sm font-semibold text-text-primary">
                Client and lead
              </h3>
              <dl className="mt-2 divide-y divide-border">
                <Row label="Client">
                  {row.client_name ?? (hiddenFields.includes("client_name") ? "Hidden by Admin" : "—")}
                </Row>
                <Row label="Lead status">
                  {row.lead_status ? (LEAD_STATUS_LABEL[row.lead_status] ?? humanizeStatus(row.lead_status)) : "—"}
                </Row>
              </dl>
              {row.lead_uuid ? (
                <Link
                  href={`/dashboard/leads/${row.lead_uuid}`}
                  className="mt-2 inline-block text-sm font-medium text-brand-link hover:underline"
                >
                  Open lead history
                </Link>
              ) : null}
            </section>
            <section aria-labelledby="commission-deal" className="rounded-lg border border-border p-3">
              <h3 id="commission-deal" className="text-sm font-semibold text-text-primary">
                Deal
              </h3>
              <dl className="mt-2 divide-y divide-border">
                <Row label="Type">{DEAL_TYPE_LABEL[row.deal_type] ?? row.deal_type}</Row>
                {row.deal_type === "loan_application" ? (
                  <>
                    <Row label="Product">{row.product_label ?? "—"}</Row>
                    <Row label="Bank">{row.bank_name ?? "—"}</Row>
                  </>
                ) : (
                  <>
                    <Row label="Property">{row.property_title ?? "—"}</Row>
                    <Row label="Category">{humanizeStatus(row.property_category)}</Row>
                  </>
                )}
                <Row label="Deal status">{humanizeStatus(row.deal_status)}</Row>
                <Row label={row.deal_type === "loan_application" ? "Loan amount" : "Deal value"}>
                  {hiddenFields.includes("deal_amount") ? "Hidden by Admin" : formatDealAmount(row.deal_amount)}
                </Row>
              </dl>
            </section>
            <section aria-labelledby="commission-payment" className="rounded-lg border border-border p-3">
              <h3 id="commission-payment" className="text-sm font-semibold text-text-primary">
                Payment
              </h3>
              <dl className="mt-2 divide-y divide-border">
                <Row label="Entered">{formatWhen(row.created_at)}</Row>
                <Row label="Paid">{formatWhen(row.paid_at)}</Row>
              </dl>
              {row.payout_txn_uuid ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => onOpenTransaction(row.payout_txn_uuid as string)}
                >
                  View payment trail
                </Button>
              ) : null}
            </section>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
