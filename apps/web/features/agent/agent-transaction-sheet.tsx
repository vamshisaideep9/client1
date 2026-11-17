"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { FetchError } from "@/features/dashboard/fetch-error";
import { StatusBadge, type StatusTone } from "@/features/dashboard/status-badge";
import {
  getAgentTransaction,
  type AgentPayoutActor,
  type AgentTransactionDetail,
} from "@/lib/agent-api";
import { formatPaise } from "@/lib/format";

import { DEAL_TYPE_LABEL, humanizeStatus } from "./agent-earnings-filters";
import { formatDealAmount, formatWhen } from "./agent-history-format";

const METHOD_LABEL: Record<string, string> = {
  vpa: "UPI",
  bank_account: "Bank transfer",
  cheque: "Cheque",
};

const PAYOUT_TONE: Record<string, StatusTone> = {
  pending_approval: "warning",
  approved: "info",
  initiated: "info",
  processing: "info",
  paid: "success",
  rejected: "danger",
  failed: "danger",
  reversed: "danger",
};

const ROLE_LABEL: Record<string, string> = { admin: "Admin", sub_admin: "Sub Admin" };

function actorLabel(actor: AgentPayoutActor | null): string {
  if (!actor) return "—";
  const role = actor.role ? (ROLE_LABEL[actor.role] ?? humanizeStatus(actor.role)) : null;
  if (actor.name && role) return `${actor.name} (${role})`;
  return actor.name ?? role ?? "—";
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; data: AgentTransactionDetail }
  | { status: "error"; error: string; code: number | null };

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-sm">
      <dt className="text-text-secondary">{label}</dt>
      <dd className="min-w-0 text-right font-medium break-words text-text-primary">{children}</dd>
    </div>
  );
}

/** Payment trail and what a commission transaction paid, in a side sheet. */
export function AgentTransactionSheet({
  transactionId,
  onOpenChange,
}: {
  transactionId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  // Only the latest request may update the sheet, so a slow answer for a
  // transaction the Agent already closed never replaces the one now open.
  const requestRef = React.useRef(0);

  const load = React.useCallback(async (id: string) => {
    const request = ++requestRef.current;
    setState({ status: "loading" });
    const res = await getAgentTransaction(id);
    if (request !== requestRef.current) return;
    setState(
      res.ok
        ? { status: "ready", data: res.data }
        : { status: "error", error: res.error, code: res.status },
    );
  }, []);

  React.useEffect(() => {
    if (transactionId) void load(transactionId);
    else requestRef.current += 1;
  }, [transactionId, load]);

  const data = state.status === "ready" ? state.data : null;
  const payout = data?.payout ?? null;
  const staffHidden = data?.hidden_fields.includes("staff_names") ?? false;

  return (
    <Sheet open={transactionId !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Transaction details</SheetTitle>
          <SheetDescription>How this payment reached you and what it paid for.</SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-5">
          {state.status === "error" ? (
            <FetchError
              status={state.code}
              message={state.error}
              onRetry={() => transactionId && void load(transactionId)}
            />
          ) : !data ? (
            <p className="flex items-center gap-2 text-sm text-text-secondary" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading transaction…
            </p>
          ) : (
            <>
              <section aria-labelledby="txn-summary">
                <h3 id="txn-summary" className="sr-only">
                  Summary
                </h3>
                <p className="text-2xl font-semibold tabular-nums text-brand-heading">
                  {formatPaise(data.amount_paise)}
                </p>
                <p className="text-sm text-text-secondary">
                  {data.description} · {formatWhen(data.created_at)}
                </p>
              </section>

              <section aria-labelledby="txn-trail" className="rounded-lg border border-border p-3">
                <h3 id="txn-trail" className="text-sm font-semibold text-text-primary">
                  Payment trail
                </h3>
                {payout ? (
                  <dl className="mt-2 divide-y divide-border">
                    <Row label="Status">
                      <StatusBadge tone={PAYOUT_TONE[payout.status] ?? "neutral"}>
                        {humanizeStatus(payout.status)}
                      </StatusBadge>
                    </Row>
                    <Row label="Paid by">
                      {METHOD_LABEL[payout.method] ?? humanizeStatus(payout.method)} ·{" "}
                      <span className="font-mono">{payout.destination_hint}</span>
                    </Row>
                    <Row label="Requested">{formatWhen(payout.requested_at)}</Row>
                    <Row label="Approved">{formatWhen(payout.approved_at)}</Row>
                    {payout.issued_at ? <Row label="Cheque issued">{formatWhen(payout.issued_at)}</Row> : null}
                    <Row label="Paid">{formatWhen(payout.paid_at)}</Row>
                    {payout.reversed_at ? <Row label="Reversed">{formatWhen(payout.reversed_at)}</Row> : null}
                    <Row label="Requested by">{actorLabel(payout.requested_by)}</Row>
                    <Row label="Approved by">
                      {payout.approval_mode === "standalone"
                        ? `${actorLabel(payout.requested_by)} · single approval`
                        : actorLabel(payout.approved_by)}
                    </Row>
                  </dl>
                ) : (
                  <p className="mt-2 text-sm text-text-secondary">No payout details are linked to this entry.</p>
                )}
                {staffHidden ? (
                  <p className="mt-2 text-xs text-text-secondary">Staff names are hidden by your Admin.</p>
                ) : null}
              </section>

              <section aria-labelledby="txn-items">
                <h3 id="txn-items" className="text-sm font-semibold text-text-primary">
                  What this paid
                </h3>
                {data.items.length === 0 ? (
                  <p className="mt-2 text-sm text-text-secondary">
                    This entry is not linked to a commission.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {data.items.map((item) => (
                      <li key={item.commission_id} className="rounded-lg border border-border p-3 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-text-primary">
                            {formatPaise(item.amount_paise)}
                          </span>
                          <span className="text-xs text-text-secondary">
                            {DEAL_TYPE_LABEL[item.deal_type] ?? item.deal_type}
                          </span>
                        </div>
                        <p className="mt-1 text-text-primary">
                          {item.client_name ?? "Client"}
                          {" · "}
                          {item.product_label ?? item.property_title ?? "—"}
                          {item.bank_name ? ` · ${item.bank_name}` : ""}
                        </p>
                        <p className="text-xs text-text-secondary">
                          Deal {humanizeStatus(item.deal_status)}
                          {item.deal_amount ? ` · ${formatDealAmount(item.deal_amount)}` : ""}
                          {" · commission entered "}
                          {formatWhen(item.entered_at)}
                        </p>
                        <Link
                          href={`/dashboard/leads/${item.lead_uuid}`}
                          className="mt-1 inline-block text-xs font-medium text-brand-link hover:underline"
                        >
                          Open lead
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
