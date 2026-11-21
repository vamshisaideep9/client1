"use client";

import * as React from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { FetchError } from "@/features/dashboard/fetch-error";
import { formatPaise } from "@/lib/format";
import { getTransaction, type TransactionDetail, type TransactionType } from "@/lib/transactions";

export const TRANSACTION_SOURCE: Record<TransactionType, string> = {
  cashback: "Cashback",
  referral_bonus: "Referral bonus",
  commission: "Commission",
  contest_reward: "Contest reward",
};

const METHOD = { vpa: "UPI", bank_account: "Bank transfer", cheque: "Cheque" };
const STATUS_COPY = {
  pending_approval: "Waiting for payout approval.",
  approved: "The payout is approved and waiting to be sent.",
  initiated: "The payout was sent for processing.",
  processing: "The payment is being processed.",
  paid: "The payment settled.",
  failed: "The payment failed.",
  rejected: "The payout request was rejected.",
  reversed: "The original payment was reversed. A separate debit offsets the credit.",
  pending: "The transaction is pending.",
};

function showTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}

function Details({ data }: { data: TransactionDetail }) {
  const payment = data.payment;
  const status = payment?.status ?? (data.amount_paise < 0 ? "reversed" : data.status);
  const steps = payment
    ? [
        ["Requested", payment.requested_at],
        ["Approved", payment.approved_at],
        ["Cheque issued", payment.issued_at],
        ["Settled", payment.paid_at],
        ["Reversed", payment.reversed_at],
      ]
    : [["Ledger entry recorded", data.created_at]];

  return (
    <div className="space-y-5">
      <div>
        <p className="text-2xl font-semibold tabular-nums text-brand-heading">{formatPaise(data.amount_paise)}</p>
        <p className="mt-1 text-sm text-text-secondary">
          {STATUS_COPY[status]}
        </p>
      </div>
      <dl className="grid gap-3 rounded-lg border border-border p-3 text-sm">
        <div><dt className="text-text-secondary">Transaction ID</dt><dd className="break-all font-medium">{data.display_id}</dd></div>
        <div><dt className="text-text-secondary">Source</dt><dd className="font-medium">{TRANSACTION_SOURCE[data.type]}</dd></div>
        {payment ? (
          <>
            <div><dt className="text-text-secondary">Payment method</dt><dd className="break-words font-medium">{METHOD[payment.method]} · {payment.destination_hint}</dd></div>
            {payment.reference ? (
              <div><dt className="text-text-secondary">Payment reference</dt><dd className="break-all font-medium">{payment.reference}</dd></div>
            ) : null}
          </>
        ) : null}
      </dl>
      <section aria-label="Payment timeline" className="rounded-lg border border-border p-3">
        <h3 className="text-sm font-semibold">Timeline</h3>
        <ol className="mt-2 divide-y divide-border">
          {steps.map(([label, at]) =>
            at ? (
              <li className="flex flex-wrap justify-between gap-x-3 gap-y-1 py-2 text-sm" key={label}>
                <span>{label}</span>
                <time dateTime={at} className="text-text-secondary">{showTime(at)} IST</time>
              </li>
            ) : null,
          )}
        </ol>
      </section>
    </div>
  );
}

export function TransactionDetailSheet({
  transactionId,
  onOpenChange,
  onCloseAutoFocus,
}: {
  transactionId: string | null;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const [loaded, setLoaded] = React.useState<{
    id: string;
    result: Awaited<ReturnType<typeof getTransaction>>;
  } | null>(null);
  const [reload, setReload] = React.useState(0);
  const result = loaded?.id === transactionId ? loaded.result : null;

  React.useEffect(() => {
    if (!transactionId) return;
    let active = true;
    setLoaded(null);
    void getTransaction(transactionId).then((response) => {
      if (active) setLoaded({ id: transactionId, result: response });
    });
    return () => { active = false; };
  }, [transactionId, reload]);

  return (
    <Sheet open={transactionId !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" onCloseAutoFocus={onCloseAutoFocus}>
        <SheetHeader>
          <SheetTitle>Transaction details</SheetTitle>
          <SheetDescription>Payment status and timeline for this ledger entry.</SheetDescription>
        </SheetHeader>
        <div className="mt-4">
          {result?.ok ? <Details data={result.data} /> : result ? (
            <FetchError status={result.status} message={result.error} onRetry={() => setReload((value) => value + 1)} />
          ) : (
            <p role="status" className="text-sm text-text-secondary">Loading transaction…</p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
