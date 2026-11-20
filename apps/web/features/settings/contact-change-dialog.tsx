"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { OtpForm } from "@/components/auth/otp-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  cancelContactChange,
  newValueError,
  resendContactChange,
  selfServiceStep,
  startContactChange,
  submitNewValue,
  verifyCurrentValue,
  verifyNewValue,
  type ActiveContactChange,
  type ContactChallenge,
  type ContactField,
} from "@/lib/contact-change";
import { requiredTextError } from "@/lib/form-validation";
import { toE164 } from "@/lib/phone";

const OTP_HINT_ALLOWED = process.env.NEXT_PUBLIC_ENV !== "production";

type Step = "password" | "current-code" | "new-value" | "new-code";

function devHint(challenge: ContactChallenge) {
  if (challenge.otpHint && OTP_HINT_ALLOWED) {
    toast.info("Dev verification code", { description: challenge.otpHint });
  }
}

const NOUN: Record<ContactField, string> = { mobile: "phone number", email: "email" };

// CS-025 self-service change for Clients, Agents and Admins: current password,
// a code to the CURRENT value, the new value, a code to the NEW value. The API
// enforces every step; this dialog only walks them in order. On success every
// session ends (this one too), so it signs out and sends the user to Log in.
export function ContactChangeDialog({
  field,
  open,
  onOpenChange,
  resume,
}: {
  field: ContactField;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // An unfinished change of this field to pick up where it stopped.
  resume?: ActiveContactChange | null;
}) {
  const [step, setStep] = React.useState<Step>("password");
  const [changeId, setChangeId] = React.useState<string | null>(null);
  const [destination, setDestination] = React.useState<string | null>(null);
  const [password, setPassword] = React.useState("");
  const [value, setValue] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    if (resume && resume.field === field && resume.kind === "self_service") {
      const next = selfServiceStep(resume.status);
      setChangeId(resume.changeId);
      setDestination(resume.newValueHint);
      setStep(next === "done" ? "password" : next);
    } else {
      setStep("password");
      setChangeId(null);
      setDestination(null);
    }
    setPassword("");
    setValue("");
    setError(null);
  }, [open, resume, field]);

  async function close() {
    // Leaving mid-way withdraws the change so the other field is not blocked.
    if (changeId && step !== "password") await cancelContactChange(changeId);
    onOpenChange(false);
  }

  async function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const invalid = requiredTextError(password, "Current password", 128);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    const res = await startContactChange(field, password);
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setPassword("");
    setChangeId(res.data.changeId);
    setDestination(res.data.destinationHint);
    setStep("current-code");
    devHint(res.data);
  }

  async function submitValue(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !changeId) return;
    const raw = field === "mobile" ? toE164(value) : value.trim().toLowerCase();
    const invalid = newValueError(field, raw);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    const res = await submitNewValue(changeId, raw);
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setDestination(res.data.destinationHint);
    setStep("new-code");
    devHint(res.data);
  }

  const title =
    step === "password"
      ? `Change your ${NOUN[field]}`
      : step === "current-code"
        ? `Confirm your current ${NOUN[field]}`
        : step === "new-value"
          ? `Enter your new ${NOUN[field]}`
          : `Confirm your new ${NOUN[field]}`;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : void close())}>
      <DialogContent preventOutsideClose className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {step === "password"
              ? `For your security we check your password, then send codes to your current and your new ${NOUN[field]}. Every device is signed out when the change is done.`
              : step === "new-value"
                ? field === "mobile"
                  ? "We will call this number with a code."
                  : "We will email a code to this address."
                : `Enter the 6-digit code we sent to ${destination ?? `your ${NOUN[field]}`}.`}
          </DialogDescription>
        </DialogHeader>

        {step === "password" ? (
          <form onSubmit={submitPassword} noValidate className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="contact-change-password">
                Current password
                <RequiredIndicator />
              </Label>
              <Input
                id="contact-change-password"
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                maxLength={128}
                autoComplete="current-password"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "contact-change-error" : undefined}
              />
              <FieldError id="contact-change-error" className="text-xs">
                {error ?? undefined}
              </FieldError>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => void close()} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                Continue
              </Button>
            </DialogFooter>
          </form>
        ) : null}

        {step === "current-code" && changeId ? (
          <OtpForm
            submitLabel="Verify current"
            onSubmit={async (otp) => {
              const res = await verifyCurrentValue(changeId, otp);
              if (res.ok) {
                setError(null);
                setStep("new-value");
              }
              return res;
            }}
            onResend={async () => {
              const res = await resendContactChange(changeId);
              if (res.ok) devHint(res.data);
              return res;
            }}
          />
        ) : null}

        {step === "new-value" ? (
          <form onSubmit={submitValue} noValidate className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="contact-change-value">
                {field === "mobile" ? "New mobile number" : "New email"}
                <RequiredIndicator />
              </Label>
              <Input
                id="contact-change-value"
                type={field === "mobile" ? "tel" : "email"}
                inputMode={field === "mobile" ? "numeric" : "email"}
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setError(null);
                }}
                maxLength={field === "mobile" ? 16 : 254}
                autoComplete={field === "mobile" ? "tel-national" : "email"}
                placeholder={field === "mobile" ? "98765 43210" : "you@example.com"}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "contact-change-value-error" : undefined}
              />
              <FieldError id="contact-change-value-error" className="text-xs">
                {error ?? undefined}
              </FieldError>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => void close()} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                Send code
              </Button>
            </DialogFooter>
          </form>
        ) : null}

        {step === "new-code" && changeId ? (
          <div className="space-y-3">
            <OtpForm
              submitLabel={`Change ${NOUN[field]}`}
              onSubmit={async (otp) => {
                const res = await verifyNewValue(changeId, otp);
                if (res.ok) {
                  // Every session ended server-side, this one included. A full
                  // navigation (not a client route change) so the app guard's
                  // signed-out redirect cannot race it; the login screen then
                  // starts from a clean provider.
                  window.location.replace(`/login?changed=${field}`);
                }
                return res;
              }}
              onResend={async () => {
                const res = await resendContactChange(changeId);
                if (res.ok) devHint(res.data);
                return res;
              }}
            />
            <button
              type="button"
              className="text-sm font-medium text-brand-link underline-offset-4 hover:underline"
              onClick={() => {
                setValue("");
                setError(null);
                setStep("new-value");
              }}
            >
              Use a different {NOUN[field]}
            </button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
