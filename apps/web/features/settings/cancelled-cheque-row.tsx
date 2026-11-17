"use client";

import * as React from "react";
import { FileCheck2, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  deleteAgentCheque,
  uploadAgentCheque,
  type AgentPayoutDetails,
} from "@/lib/agent-api";
import { CHEQUE_ACCEPT, validateChequeFile } from "@/lib/agent-payout-details";

const WHEN = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

/**
 * Optional cancelled cheque on the Agent's payout details (CS-022). The file is
 * never shown back here; payout makers open it (audited). Replacing or
 * removing the bank account removes it on the server.
 */
export function CancelledChequeRow({
  details,
  onChanged,
  disabled = false,
}: {
  details: AgentPayoutDetails;
  onChanged: (next: AgentPayoutDetails | null) => void;
  disabled?: boolean;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { confirm, confirmDialog } = useConfirm();
  const uploadedAt = details.cheque_uploaded_at;

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const problem = validateChequeFile(file);
    setError(problem);
    if (problem) return;
    setBusy(true);
    const res = await uploadAgentCheque(file);
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      toast.error("Couldn't upload the cancelled cheque", { description: res.error });
      return;
    }
    toast.success(uploadedAt ? "Cancelled cheque replaced" : "Cancelled cheque uploaded");
    onChanged(res.data);
  }

  async function remove() {
    const ok = await confirm({
      title: "Remove the cancelled cheque?",
      description: "Your bank account and UPI ID stay saved.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    const res = await deleteAgentCheque();
    setBusy(false);
    if (!res.ok) {
      toast.error("Couldn't remove it", { description: res.error });
      return;
    }
    toast.success("Cancelled cheque removed");
    onChanged(null);
  }

  return (
    <div className="mt-4 rounded-lg border border-dashed border-border px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-3">
          <FileCheck2 className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-xs text-text-secondary">Cancelled cheque (optional)</span>
            <span className="block font-medium text-text-primary">
              {uploadedAt ? `Uploaded ${WHEN.format(new Date(uploadedAt))}` : "Not uploaded"}
            </span>
          </span>
        </span>
        <span className="flex flex-wrap gap-2">
          <input
            ref={inputRef}
            id="cancelled-cheque-file"
            type="file"
            accept={CHEQUE_ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-describedby="cancelled-cheque-help"
            onChange={(event) => void onFile(event)}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {uploadedAt ? "Replace" : "Upload"}
            <span className="sr-only"> cancelled cheque</span>
          </Button>
          {uploadedAt ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled || busy}
              onClick={() => void remove()}
            >
              Remove
              <span className="sr-only"> cancelled cheque</span>
            </Button>
          ) : null}
        </span>
      </div>
      <p id="cancelled-cheque-help" className="mt-2 text-xs text-text-secondary">
        JPEG, PNG or PDF, up to 5 MB. It helps Admin confirm your bank account. Changing or removing
        the bank account removes the cheque.
      </p>
      {error ? (
        <p className="mt-1 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </div>
  );
}
