"use client";

import * as React from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  PANEL_DIALOG_CLASS,
  WorkspaceDialogHeader,
} from "@/features/dashboard/workspace-dialog";
import type { ApiResponse } from "@/lib/api/client";
import { formatCompactINR, formatINR } from "@/lib/format";
import {
  apiIssuesToFieldErrors,
  focusFirstInvalidField,
  type FieldErrors,
} from "@/lib/form-validation";
import type { LoanTxnCreate } from "@/lib/telecaller-api";
import { cn } from "@/lib/utils";

import {
  validateLoanTransaction,
  type LoanTransactionField,
} from "./telecaller-lead-detail-validation";

/** Today's date in the viewer's own timezone, as the date input expects. */
export function localDateInputValue(now = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** "₹5,00,000 · ₹5 L" style preview for a typed amount, or null. */
export function amountPreview(raw: string): string | null {
  const value = Number(raw);
  if (!raw.trim() || !Number.isFinite(value) || value <= 0) return null;
  const exact = formatINR(value);
  const compact = formatCompactINR(value);
  return exact === compact ? exact : `${exact} · ${compact}`;
}

function AdornedInput({
  prefix,
  suffix,
  className,
  ...props
}: React.ComponentProps<typeof Input> & { prefix?: string; suffix?: string }) {
  return (
    <div className="relative">
      {prefix ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-text-secondary"
        >
          {prefix}
        </span>
      ) : null}
      <Input
        {...props}
        className={cn("h-11 tabular-nums", prefix && "pl-7", suffix && "pr-8", className)}
      />
      {suffix ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-text-secondary"
        >
          {suffix}
        </span>
      ) : null}
    </div>
  );
}

export function AddTxnDialog({
  applicationId,
  loanTypeName,
  defaultBankName,
  onAdd,
}: {
  applicationId: string;
  loanTypeName: string;
  defaultBankName?: string | null;
  onAdd: (applicationId: string, payload: LoanTxnCreate) => Promise<ApiResponse<unknown>>;
}) {
  const [open, setOpen] = React.useState(false);
  const [bankName, setBankName] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [rate, setRate] = React.useState("");
  const [txnDate, setTxnDate] = React.useState("");
  const [errors, setErrors] = React.useState<FieldErrors<LoanTransactionField>>({});
  const [saving, setSaving] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  function reset() {
    setBankName(defaultBankName ?? "");
    setAmount("");
    setRate("");
    setTxnDate(localDateInputValue());
    setErrors({});
  }

  function onOpenChange(next: boolean) {
    if (saving) return;
    if (next) reset();
    setOpen(next);
  }

  function clearError(field: LoanTransactionField) {
    setErrors((current) => (current[field] ? { ...current, [field]: undefined } : current));
  }

  function focusInvalid() {
    requestAnimationFrame(() => {
      if (formRef.current) focusFirstInvalidField(formRef.current);
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const validation = validateLoanTransaction({
      bankName,
      amount,
      interestRate: rate,
      txnDate,
    });
    setErrors(validation);
    if (Object.keys(validation).length > 0) {
      focusInvalid();
      return;
    }

    setSaving(true);
    const res = await onAdd(applicationId, {
      bank_name: bankName.trim(),
      amount: amount.trim(),
      interest_rate: rate.trim(),
      txn_date: txnDate,
    });
    setSaving(false);
    if (res.ok) {
      toast.success("Transaction added");
      setOpen(false);
      return;
    }

    setErrors(
      apiIssuesToFieldErrors(res.issues, {
        bank_name: "bankName",
        amount: "amount",
        interest_rate: "interestRate",
        txn_date: "txnDate",
      }),
    );
    focusInvalid();
    toast.error("Couldn't add transaction", { description: res.error });
  }

  const fieldId = (field: string) => `txn-${applicationId}-${field}`;
  const preview = amountPreview(amount);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" className="w-full sm:w-auto">
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add transaction
        </Button>
      </DialogTrigger>
      <DialogContent preventOutsideClose showCloseButton={false} className={cn(PANEL_DIALOG_CLASS, "!max-w-lg")}>
        <WorkspaceDialogHeader
          title="Add transaction"
          description={`${loanTypeName} · Entries can't be edited or deleted once saved.`}
          closeLabel="Close add transaction"
        />
        <form
          ref={formRef}
          noValidate
          onSubmit={(e) => void onSubmit(e)}
          className="min-h-0 space-y-5 overflow-y-auto overscroll-contain px-0.5 pt-4"
        >
          <div className="space-y-1.5">
            <Label htmlFor={fieldId("bank")}>
              Bank<RequiredIndicator />
            </Label>
            <Input
              id={fieldId("bank")}
              name="bank_name"
              className="h-11"
              autoComplete="off"
              value={bankName}
              onChange={(e) => {
                setBankName(e.target.value);
                clearError("bankName");
              }}
              placeholder="e.g. HDFC Bank"
              maxLength={200}
              aria-required="true"
              aria-invalid={Boolean(errors.bankName)}
              aria-describedby={errors.bankName ? fieldId("bank-error") : undefined}
            />
            <FieldError id={fieldId("bank-error")}>{errors.bankName}</FieldError>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor={fieldId("amount")}>
              Amount<RequiredIndicator />
            </Label>
            <AdornedInput
              id={fieldId("amount")}
              name="amount"
              prefix="₹"
              type="number"
              inputMode="decimal"
              min="0.01"
              max="999999999999.99"
              step="0.01"
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                clearError("amount");
              }}
              placeholder="500000"
              aria-required="true"
              aria-invalid={Boolean(errors.amount)}
              aria-describedby={cn(
                fieldId("amount-preview"),
                errors.amount && fieldId("amount-error"),
              )}
            />
            <p id={fieldId("amount-preview")} className="min-h-4 text-xs text-text-secondary tabular-nums">
              {preview ?? "Enter the amount in rupees."}
            </p>
            <FieldError id={fieldId("amount-error")}>{errors.amount}</FieldError>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={fieldId("rate")}>
                Interest rate<RequiredIndicator />
              </Label>
              <AdornedInput
                id={fieldId("rate")}
                name="interest_rate"
                suffix="%"
                type="number"
                inputMode="decimal"
                min="0"
                max="100"
                step="0.001"
                value={rate}
                onChange={(e) => {
                  setRate(e.target.value);
                  clearError("interestRate");
                }}
                placeholder="8.5"
                aria-required="true"
                aria-invalid={Boolean(errors.interestRate)}
                aria-describedby={errors.interestRate ? fieldId("rate-error") : undefined}
              />
              <FieldError id={fieldId("rate-error")}>{errors.interestRate}</FieldError>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor={fieldId("date")}>
                Transaction date<RequiredIndicator />
              </Label>
              <Input
                id={fieldId("date")}
                name="txn_date"
                type="date"
                className="h-11"
                value={txnDate}
                onChange={(e) => {
                  setTxnDate(e.target.value);
                  clearError("txnDate");
                }}
                aria-required="true"
                aria-invalid={Boolean(errors.txnDate)}
                aria-describedby={errors.txnDate ? fieldId("date-error") : undefined}
              />
              <FieldError id={fieldId("date-error")}>{errors.txnDate}</FieldError>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="h-11 sm:h-9"
              disabled={saving}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" className="h-11 sm:h-9" disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              Save transaction
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
