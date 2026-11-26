"use client";

import * as React from "react";
import { FileCheck2, Loader2, WalletCards } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  DESTINATION_OPTIONS,
  savedDestinationToForm,
  type PayoutDestinationFormState,
} from "@/lib/payout-form";
import { getCancelledCheque, getSavedPayoutDestination } from "@/lib/payouts-api";

export type SavedDestinationTarget =
  | { recipientUserUuid: string }
  | { agentProfileUuid: string };

export function PayoutDestinationFields({
  idPrefix,
  form,
  errors,
  onChange,
  disabled = false,
  savedDestinationTarget = null,
}: {
  idPrefix: string;
  form: PayoutDestinationFormState;
  errors: Record<string, string>;
  onChange: <Key extends keyof PayoutDestinationFormState>(
    key: Key,
    value: PayoutDestinationFormState[Key],
  ) => void;
  disabled?: boolean;
  /** When set, offers to fill the destination from the Agent's saved details. */
  savedDestinationTarget?: SavedDestinationTarget | null;
}) {
  const destinationErrorId = `${idPrefix}-destination-error`;
  const [prefilling, setPrefilling] = React.useState(false);
  const [openingCheque, setOpeningCheque] = React.useState(false);

  async function viewCancelledCheque() {
    if (!savedDestinationTarget) return;
    // Open the tab inside the click so pop-up blockers allow it, then point it
    // at the short-lived link once the (audited) read returns.
    const tab = window.open("", "_blank");
    if (tab) tab.opener = null;
    setOpeningCheque(true);
    const res = await getCancelledCheque(savedDestinationTarget);
    setOpeningCheque(false);
    if (!res.ok) {
      tab?.close();
      if (res.status === 404) {
        toast.info("No cancelled cheque", {
          description: "This recipient hasn't uploaded a cancelled cheque.",
        });
      } else {
        toast.error("Couldn't open the cancelled cheque", { description: res.error });
      }
      return;
    }
    if (tab) {
      tab.location.href = res.data.url;
    } else {
      toast.info("Allow pop-ups to view the cancelled cheque", {
        description: "Your browser blocked the new tab.",
      });
    }
  }

  async function applySavedDetails() {
    if (!savedDestinationTarget) return;
    setPrefilling(true);
    const res = await getSavedPayoutDestination(savedDestinationTarget);
    setPrefilling(false);
    if (!res.ok) {
      if (res.status === 404) {
        toast.info("No saved payout details", {
          description: "This recipient hasn't saved a UPI ID or bank account. Enter the details by hand.",
        });
      } else {
        toast.error("Couldn't load saved payout details", { description: res.error });
      }
      return;
    }
    const next = savedDestinationToForm(form, res.data);
    if (!next) return;
    (Object.keys(next) as (keyof PayoutDestinationFormState)[]).forEach((key) =>
      onChange(key, next[key]),
    );
    toast.success("Filled from the recipient's saved details", {
      description: "Check them before you raise the payout.",
    });
  }

  return (
    <>
      {savedDestinationTarget ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full sm:w-auto"
            disabled={disabled || prefilling}
            onClick={() => void applySavedDetails()}
          >
            {prefilling ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <WalletCards className="h-4 w-4" aria-hidden="true" />
            )}
            Use saved payout details
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full sm:w-auto"
            disabled={disabled || openingCheque}
            onClick={() => void viewCancelledCheque()}
          >
            {openingCheque ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <FileCheck2 className="h-4 w-4" aria-hidden="true" />
            )}
            View cancelled cheque
            <span className="sr-only"> (opens in a new tab)</span>
          </Button>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Label id={`${idPrefix}-destination-label`}>
          Destination
          <RequiredIndicator />
        </Label>
        <RadioGroup
          value={form.destinationType}
          onValueChange={(value) =>
            onChange(
              "destinationType",
              value as PayoutDestinationFormState["destinationType"],
            )
          }
          disabled={disabled}
          className="grid-cols-1 sm:grid-cols-3"
          aria-labelledby={`${idPrefix}-destination-label`}
          aria-required="true"
          aria-invalid={Boolean(errors.destinationType)}
          aria-describedby={errors.destinationType ? destinationErrorId : undefined}
        >
          {DESTINATION_OPTIONS.map((option) => (
            <div key={option.value} className="flex items-center gap-2">
              <RadioGroupItem
                value={option.value}
                id={`${idPrefix}-destination-${option.value}`}
              />
              <Label
                htmlFor={`${idPrefix}-destination-${option.value}`}
                className="font-normal"
              >
                {option.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
        <FieldError id={destinationErrorId} className="text-xs">
          {errors.destinationType}
        </FieldError>
      </div>

      {form.destinationType === "vpa" ? (
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-vpa`}>
            UPI VPA
            <RequiredIndicator />
          </Label>
          <Input
            id={`${idPrefix}-vpa`}
            placeholder="name@bank"
            value={form.vpa}
            maxLength={100}
            disabled={disabled}
            aria-invalid={Boolean(errors.vpa)}
            aria-describedby={errors.vpa ? `${idPrefix}-vpa-error` : undefined}
            onChange={(event) => onChange("vpa", event.target.value)}
          />
          <FieldError id={`${idPrefix}-vpa-error`} className="text-xs">
            {errors.vpa}
          </FieldError>
        </div>
      ) : form.destinationType === "bank_account" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-ifsc`}>
              IFSC
              <RequiredIndicator />
            </Label>
            <Input
              id={`${idPrefix}-ifsc`}
              value={form.ifsc}
              maxLength={20}
              autoCapitalize="characters"
              disabled={disabled}
              aria-invalid={Boolean(errors.ifsc)}
              aria-describedby={errors.ifsc ? `${idPrefix}-ifsc-error` : undefined}
              onChange={(event) => onChange("ifsc", event.target.value)}
            />
            <FieldError id={`${idPrefix}-ifsc-error`} className="text-xs">
              {errors.ifsc}
            </FieldError>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}-account`}>
              Account number
              <RequiredIndicator />
            </Label>
            <Input
              id={`${idPrefix}-account`}
              value={form.accountNumber}
              minLength={6}
              maxLength={40}
              inputMode="numeric"
              autoComplete="off"
              disabled={disabled}
              aria-invalid={Boolean(errors.accountNumber)}
              aria-describedby={
                errors.accountNumber ? `${idPrefix}-account-error` : undefined
              }
              onChange={(event) => onChange("accountNumber", event.target.value)}
            />
            <FieldError id={`${idPrefix}-account-error`} className="text-xs">
              {errors.accountNumber}
            </FieldError>
          </div>
        </div>
      ) : form.destinationType === "cheque" ? (
        <p className="rounded-lg bg-muted p-3 text-xs text-text-secondary">
          No bank details are stored. The cheque reference is recorded after approval and
          issuance.
        </p>
      ) : null}
    </>
  );
}
