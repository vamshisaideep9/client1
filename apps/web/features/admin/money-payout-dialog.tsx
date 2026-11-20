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
import {
  PayoutDestinationFields,
  type SavedDestinationTarget,
} from "@/features/admin/payout-destination-fields";
import type { ApiResponse } from "@/lib/api/client";
import { apiIssuesToFieldErrors, focusFirstInvalidField } from "@/lib/form-validation";
import {
  validatePayoutDestinationForm,
  type PayoutDestinationFormState,
} from "@/lib/payout-form";

const EMPTY_DESTINATION: PayoutDestinationFormState = {
  destinationType: "",
  vpa: "",
  ifsc: "",
  accountNumber: "",
  accountName: "",
};

export function MoneyPayoutDialog({
  open,
  onOpenChange,
  title,
  description,
  idPrefix,
  lockedCopy,
  submitLabel,
  conflictTitle,
  onSubmit,
  savedDestinationTarget = null,
  summary,
  successDescription = "Awaiting a different admin's approval.",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description: React.ReactNode;
  idPrefix: string;
  lockedCopy: string;
  submitLabel: string;
  conflictTitle: string;
  onSubmit: (form: PayoutDestinationFormState) => Promise<ApiResponse<unknown>>;
  savedDestinationTarget?: SavedDestinationTarget | null;
  summary?: React.ReactNode;
  successDescription?: string;
}) {
  const [form, setForm] = React.useState<PayoutDestinationFormState>(EMPTY_DESTINATION);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const contentRef = React.useRef<HTMLDivElement>(null);

  function resetAndClose() {
    setForm(EMPTY_DESTINATION);
    setErrors({});
    onOpenChange(false);
  }

  function set<Key extends keyof PayoutDestinationFormState>(
    key: Key,
    value: PayoutDestinationFormState[Key],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function showErrors(next: Record<string, string>) {
    setErrors(next);
    if (Object.keys(next).length > 0) {
      requestAnimationFrame(() => {
        if (contentRef.current) focusFirstInvalidField(contentRef.current);
      });
    }
  }

  async function submit() {
    const next = validatePayoutDestinationForm(form);
    showErrors(next);
    if (Object.keys(next).length > 0) return;

    setBusy(true);
    const response = await onSubmit(form);
    setBusy(false);
    if (response.ok) {
      toast.success("Payout raised", { description: successDescription });
      resetAndClose();
      return;
    }
    if (response.status === 409) {
      toast.warning(conflictTitle, {
        description: "Close this and check the ledger before trying again.",
      });
      return;
    }
    const serverErrors = apiIssuesToFieldErrors(response.issues, {
      destination_type: "destinationType",
      "destination.vpa": "vpa",
      "destination.ifsc": "ifsc",
      "destination.account_number": "accountNumber",
    });
    if (Object.keys(serverErrors).length > 0) showErrors(serverErrors);
    toast.error("Could not raise the payout", { description: response.error });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        if (next) onOpenChange(true);
        else resetAndClose();
      }}
    >
      <DialogContent preventOutsideClose ref={contentRef} className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {summary}
          <p className="rounded-lg bg-muted p-3 text-xs text-text-secondary">{lockedCopy}</p>
          <PayoutDestinationFields
            idPrefix={idPrefix}
            form={form}
            errors={errors}
            onChange={set}
            disabled={busy}
            savedDestinationTarget={savedDestinationTarget}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={resetAndClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
