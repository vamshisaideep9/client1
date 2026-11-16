"use client";

import * as React from "react";
import { Landmark, Loader2, Smartphone } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  deleteAgentPayoutDetails,
  getAgentPayoutDetails,
  saveAgentPayoutDetails,
  type AgentPayoutDetails,
} from "@/lib/agent-api";
import {
  EMPTY_PAYOUT_DETAILS_DRAFT,
  buildPayoutDetailsPayload,
  validatePayoutDetailsDraft,
  type PayoutDetailsDraft,
} from "@/lib/agent-payout-details";
import { apiIssuesToFieldErrors, focusFirstInvalidField } from "@/lib/form-validation";

type Errors = Partial<Record<keyof PayoutDetailsDraft | "form", string>>;

// Agent Account settings: where commissions are paid. Saved values are never
// shown back in full; the Agent sees masked hints and re-enters a destination
// to change it. Payout admins can prefill a payout from these details.
export function PayoutDetailsCard() {
  const [details, setDetails] = React.useState<AgentPayoutDetails | null>(null);
  const [loadState, setLoadState] = React.useState<"loading" | "ready" | "error">("loading");
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<PayoutDetailsDraft>(EMPTY_PAYOUT_DETAILS_DRAFT);
  const [errors, setErrors] = React.useState<Errors>({});
  const [saving, setSaving] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);
  const { confirm, confirmDialog } = useConfirm();

  const load = React.useCallback(async () => {
    setLoadState("loading");
    const res = await getAgentPayoutDetails();
    if (res.ok) {
      setDetails(res.data);
      setEditing(!res.data.saved);
      setLoadState("ready");
    } else {
      setLoadState("error");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function update<K extends keyof PayoutDetailsDraft>(key: K, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key] && !current.form) return current;
      const next = { ...current };
      delete next[key];
      delete next.form;
      return next;
    });
  }

  function showErrors(next: Errors) {
    setErrors(next);
    if (Object.keys(next).length > 0) {
      requestAnimationFrame(() => {
        if (formRef.current) focusFirstInvalidField(formRef.current);
      });
    }
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next = validatePayoutDetailsDraft(draft);
    showErrors(next);
    if (Object.keys(next).length > 0) return;
    setSaving(true);
    const res = await saveAgentPayoutDetails(buildPayoutDetailsPayload(draft));
    setSaving(false);
    if (res.ok) {
      setDetails(res.data);
      setDraft(EMPTY_PAYOUT_DETAILS_DRAFT);
      setEditing(false);
      toast.success("Payout details saved");
      return;
    }
    const serverErrors = apiIssuesToFieldErrors(res.issues, {
      upi_id: "upiId",
      "bank.account_holder_name": "accountHolderName",
      "bank.account_number": "accountNumber",
      "bank.ifsc": "ifsc",
      "bank.bank_name": "bankName",
    });
    if (Object.keys(serverErrors).length > 0) showErrors(serverErrors as Errors);
    toast.error("Couldn't save your payout details", { description: res.error });
  }

  async function remove(which: "upi" | "bank") {
    const onlyOne = !(details?.upi_hint && details?.bank_hint);
    const ok = await confirm({
      title: which === "upi" ? "Remove your UPI ID?" : "Remove your bank account?",
      description: onlyOne
        ? "You won't have any payout details saved. Admins will ask you where to send payments."
        : "Your other saved payout method stays as it is.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!ok) return;
    setSaving(true);
    const res = onlyOne
      ? await deleteAgentPayoutDetails()
      : await saveAgentPayoutDetails(which === "upi" ? { upi_id: null } : { bank: null });
    setSaving(false);
    if (!res.ok) {
      toast.error("Couldn't remove it", { description: res.error });
      return;
    }
    toast.success(which === "upi" ? "UPI ID removed" : "Bank account removed");
    await load();
  }

  return (
    <section className="rounded-xl border border-border bg-card p-6" aria-labelledby="payout-details-title">
      <h2 id="payout-details-title" className="text-base font-semibold text-text-primary">
        Payout details
      </h2>
      <p className="mt-1 text-sm text-text-secondary">
        Where your commissions are paid. Add a UPI ID, a bank account, or both. Saved details are
        encrypted and shown only partly here.
      </p>

      {loadState === "loading" ? (
        <Skeleton className="mt-5 h-24 rounded-lg" />
      ) : loadState === "error" ? (
        <div className="mt-5 flex items-center justify-between gap-2 text-sm">
          <p className="text-text-secondary">Couldn&apos;t load your payout details.</p>
          <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      ) : details && !details.available ? (
        <p className="mt-5 rounded-lg bg-muted p-3 text-sm text-text-secondary">
          Saving payout details isn&apos;t available right now. Please try again later.
        </p>
      ) : (
        <>
          {details?.saved ? (
            <ul className="mt-5 space-y-2">
              {details.upi_hint ? (
                <SavedRow
                  icon={<Smartphone className="h-4 w-4" aria-hidden="true" />}
                  label="UPI ID"
                  value={details.upi_hint}
                  onRemove={() => void remove("upi")}
                  disabled={saving}
                />
              ) : null}
              {details.bank_hint ? (
                <SavedRow
                  icon={<Landmark className="h-4 w-4" aria-hidden="true" />}
                  label="Bank account"
                  value={details.bank_hint}
                  onRemove={() => void remove("bank")}
                  disabled={saving}
                />
              ) : null}
            </ul>
          ) : null}

          {editing ? (
            <form ref={formRef} noValidate onSubmit={(e) => void onSubmit(e)} className="mt-5 space-y-5">
              {details?.saved ? (
                <p className="text-xs text-text-secondary">
                  Fill in only what you want to add or replace. Anything you leave blank stays as it is.
                </p>
              ) : null}
              <div className="space-y-2">
                <Label htmlFor="payout-upi">UPI ID</Label>
                <Input
                  id="payout-upi"
                  value={draft.upiId}
                  onChange={(e) => update("upiId", e.target.value)}
                  placeholder="name@bank"
                  autoComplete="off"
                  inputMode="email"
                  maxLength={320}
                  aria-invalid={Boolean(errors.upiId)}
                  aria-describedby={errors.upiId ? "payout-upi-error" : undefined}
                />
                <FieldError id="payout-upi-error">{errors.upiId}</FieldError>
              </div>

              <fieldset className="space-y-4 border-t border-border pt-5">
                <legend className="text-sm font-semibold text-text-primary">Bank account</legend>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2 sm:col-span-2">
                    <Label htmlFor="payout-holder">
                      Account holder name
                      {hasBank(draft) ? <RequiredIndicator /> : null}
                    </Label>
                    <Input
                      id="payout-holder"
                      value={draft.accountHolderName}
                      onChange={(e) => update("accountHolderName", e.target.value)}
                      autoComplete="off"
                      maxLength={100}
                      aria-invalid={Boolean(errors.accountHolderName)}
                      aria-describedby={errors.accountHolderName ? "payout-holder-error" : undefined}
                    />
                    <FieldError id="payout-holder-error">{errors.accountHolderName}</FieldError>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="payout-account">
                      Account number
                      {hasBank(draft) ? <RequiredIndicator /> : null}
                    </Label>
                    <Input
                      id="payout-account"
                      value={draft.accountNumber}
                      onChange={(e) => update("accountNumber", e.target.value.replace(/\D/g, ""))}
                      inputMode="numeric"
                      autoComplete="off"
                      maxLength={18}
                      aria-invalid={Boolean(errors.accountNumber)}
                      aria-describedby={errors.accountNumber ? "payout-account-error" : undefined}
                    />
                    <FieldError id="payout-account-error">{errors.accountNumber}</FieldError>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="payout-ifsc">
                      IFSC
                      {hasBank(draft) ? <RequiredIndicator /> : null}
                    </Label>
                    <Input
                      id="payout-ifsc"
                      value={draft.ifsc}
                      onChange={(e) => update("ifsc", e.target.value.toUpperCase())}
                      autoCapitalize="characters"
                      autoComplete="off"
                      maxLength={11}
                      placeholder="HDFC0001234"
                      aria-invalid={Boolean(errors.ifsc)}
                      aria-describedby={errors.ifsc ? "payout-ifsc-error" : undefined}
                    />
                    <FieldError id="payout-ifsc-error">{errors.ifsc}</FieldError>
                  </div>
                  <div className="space-y-2 sm:col-span-2">
                    <Label htmlFor="payout-bank-name">Bank name</Label>
                    <Input
                      id="payout-bank-name"
                      value={draft.bankName}
                      onChange={(e) => update("bankName", e.target.value)}
                      autoComplete="off"
                      maxLength={100}
                    />
                  </div>
                </div>
              </fieldset>

              <FieldError id="payout-form-error">{errors.form}</FieldError>
              <div className="flex flex-wrap justify-end gap-2">
                {details?.saved ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={saving}
                    onClick={() => {
                      setDraft(EMPTY_PAYOUT_DETAILS_DRAFT);
                      setErrors({});
                      setEditing(false);
                    }}
                  >
                    Cancel
                  </Button>
                ) : null}
                <Button type="submit" disabled={saving}>
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  Save payout details
                </Button>
              </div>
            </form>
          ) : (
            <div className="mt-4 flex justify-end">
              <Button type="button" variant="outline" onClick={() => setEditing(true)}>
                Change payout details
              </Button>
            </div>
          )}
        </>
      )}
      {confirmDialog}
    </section>
  );
}

function hasBank(draft: PayoutDetailsDraft): boolean {
  return [draft.accountHolderName, draft.accountNumber, draft.ifsc, draft.bankName].some(
    (value) => value.trim() !== "",
  );
}

function SavedRow({
  icon,
  label,
  value,
  onRemove,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  onRemove: () => void;
  disabled: boolean;
}) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-4 py-3">
      <span className="flex min-w-0 items-center gap-3">
        <span className="text-text-secondary">{icon}</span>
        <span className="min-w-0">
          <span className="block text-xs text-text-secondary">{label}</span>
          <span className="block font-medium text-text-primary">{value}</span>
        </span>
      </span>
      <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onRemove}>
        Remove
        <span className="sr-only"> {label}</span>
      </Button>
    </li>
  );
}
