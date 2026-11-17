"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBadge } from "@/features/dashboard/status-badge";
import type { ApiResponse } from "@/lib/api/client";
import { formatPaise } from "@/lib/format";
import type { Payout, SimulatedGatewayEvent } from "@/lib/payouts-api";

type Outcome = {
  label: string;
  description: string;
  done: string;
  variant: "default" | "outline" | "destructive";
};

// Each outcome is a real RazorpayX webhook event; the API applies it through
// the same settlement path a live webhook takes.
export const SIMULATED_OUTCOMES: Record<SimulatedGatewayEvent, Outcome> = {
  "payout.processed": {
    label: "Payment succeeds",
    description: "The bank credits the recipient. Their ledger shows the payment as paid.",
    done: "Simulated payment succeeded",
    variant: "default",
  },
  "payout.failed": {
    label: "Payment fails",
    description: "The transfer fails. Nothing is credited and the payout is marked failed.",
    done: "Simulated payment failed",
    variant: "outline",
  },
  "payout.rejected": {
    label: "Bank rejects",
    description: "The beneficiary bank rejects the transfer. Nothing is credited.",
    done: "Simulated bank rejection",
    variant: "outline",
  },
  "payout.reversed": {
    label: "Bank reverses the payment",
    description: "Funds come back after settling. A matching debit cancels the credit.",
    done: "Simulated reversal recorded",
    variant: "destructive",
  },
};

export function PayoutGatewaySimulatorDialog({
  payout,
  onOpenChange,
  onSimulate,
}: {
  payout: Payout | null;
  onOpenChange: (open: boolean) => void;
  onSimulate: (id: string, event: SimulatedGatewayEvent) => Promise<ApiResponse<Payout>>;
}) {
  const [pending, setPending] = React.useState<SimulatedGatewayEvent | null>(null);
  const events = payout?.simulate_events ?? [];
  const settled = payout?.status === "paid";

  async function choose(event: SimulatedGatewayEvent) {
    if (!payout) return;
    setPending(event);
    const res = await onSimulate(payout.id, event);
    setPending(null);
    if (res.ok) {
      toast.success(SIMULATED_OUTCOMES[event].done);
      onOpenChange(false);
    } else {
      toast.error("Could not apply the test outcome", { description: res.error });
    }
  }

  return (
    <Dialog open={payout !== null} onOpenChange={(open) => !pending && onOpenChange(open)}>
      <DialogContent className="max-w-lg">
        {payout ? (
          <>
            <DialogHeader>
              <div className="flex items-center justify-center gap-2 sm:justify-start">
                <StatusBadge tone="warning">Test mode</StatusBadge>
                <span className="text-xs text-text-secondary">Development only</span>
              </div>
              <DialogTitle>Razorpay test payout</DialogTitle>
              <DialogDescription>
                Simulated gateway. No real money moves. Choose what the gateway reports for this
                payout.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-surface p-4">
                <p className="text-2xl font-semibold tabular-nums text-text-primary">
                  {formatPaise(payout.amount_paise)}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                  <div>
                    <dt className="text-text-secondary">Recipient</dt>
                    <dd className="font-medium text-text-primary">
                      {payout.recipient_name ?? "Unknown recipient"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-text-secondary">Destination</dt>
                    <dd className="font-medium text-text-primary">{payout.destination_hint}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-text-secondary">Gateway reference</dt>
                    <dd className="break-all font-mono text-xs text-text-primary">
                      {payout.gateway_payout_id}
                    </dd>
                  </div>
                </dl>
              </div>

              {events.length === 0 ? (
                <p className="rounded-lg bg-muted p-3 text-sm text-text-secondary">
                  This payout has no test outcome to apply in its current state.
                </p>
              ) : (
                <ul className="space-y-2" aria-label="Gateway outcomes">
                  {events.map((event) => {
                    const outcome = SIMULATED_OUTCOMES[event];
                    const descriptionId = `simulated-outcome-${event.replace(".", "-")}`;
                    return (
                      <li
                        key={event}
                        className="flex items-start justify-between gap-3 rounded-lg border border-border p-3"
                      >
                        <p id={descriptionId} className="text-sm text-text-secondary">
                          {outcome.description}
                        </p>
                        <Button
                          size="sm"
                          variant={outcome.variant}
                          className="shrink-0"
                          aria-describedby={descriptionId}
                          disabled={pending !== null}
                          onClick={() => void choose(event)}
                        >
                          {pending === event ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                          {outcome.label}
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={pending !== null}>
                {settled || events.length === 0 ? "Close" : "Decide later"}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
