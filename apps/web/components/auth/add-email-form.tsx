"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { OtpForm } from "@/components/auth/otp-form";
import { Button } from "@/components/ui/button";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { emailVerifyConfirm, emailVerifyInitiate, type AuthResult } from "@/lib/auth";
import {
  addEmail,
  newValueError,
  resendAddEmail,
  verifyAddEmail,
  type ContactChallenge,
} from "@/lib/contact-change";
import { requiredTextError } from "@/lib/form-validation";

const OTP_HINT_ALLOWED = process.env.NEXT_PUBLIC_ENV !== "production";

function devHint(otpHint: string | undefined) {
  if (otpHint && OTP_HINT_ALLOWED) {
    toast.info("Dev verification code", { description: otpHint });
  }
}

type Mode =
  | { kind: "choose" }
  | { kind: "verify-on-file" }
  | { kind: "add" }
  | { kind: "add-code"; challenge: ContactChallenge };

// CS-025: an account without a verified email adds one with a code. The
// address on file (if any) can be verified as is; a Client, Agent or Admin may
// add a different one after re-entering their password. Staff (Telecaller,
// Employee, Sub Admin) may only verify the address their Admin set; a
// different one is a request to an Admin (onRequestChange).
export function AddEmailForm({
  emailOnFile,
  staff,
  onVerified,
  onRequestChange,
}: {
  emailOnFile: string | null;
  staff: boolean;
  onVerified: () => void | Promise<void>;
  onRequestChange?: () => void;
}) {
  const [mode, setMode] = React.useState<Mode>(
    emailOnFile ? { kind: "choose" } : { kind: "add" },
  );
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [errors, setErrors] = React.useState<{ email?: string; password?: string }>({});
  const [busy, setBusy] = React.useState(false);

  async function sendToOnFile() {
    if (busy) return;
    setBusy(true);
    const res = await emailVerifyInitiate();
    setBusy(false);
    if (!res.ok) {
      toast.error(res.error || "Couldn't send the code.");
      return;
    }
    devHint(res.data.otpHint);
    setMode({ kind: "verify-on-file" });
  }

  async function submitAdd(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const value = email.trim().toLowerCase();
    const next = {
      email: newValueError("email", value) ?? undefined,
      password: requiredTextError(password, "Current password", 128),
    };
    setErrors(next);
    if (next.email || next.password) return;
    setBusy(true);
    const res = await addEmail(value, password);
    setBusy(false);
    if (!res.ok) {
      if (/password/i.test(res.error)) setErrors({ password: res.error });
      else setErrors({ email: res.error });
      return;
    }
    setPassword("");
    devHint(res.data.otpHint);
    setMode({ kind: "add-code", challenge: res.data });
  }

  async function finish(result: AuthResult<unknown>) {
    if (result.ok) {
      toast.success("Email verified.");
      await onVerified();
    }
    return result;
  }

  if (mode.kind === "verify-on-file" && emailOnFile) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-text-secondary">
          Enter the 6-digit code we sent to{" "}
          <span className="font-medium text-text-primary">{emailOnFile}</span>.
        </p>
        <OtpForm
          submitLabel="Verify email"
          onSubmit={async (otp) => finish(await emailVerifyConfirm(otp))}
          onResend={async () => {
            const res = await emailVerifyInitiate();
            if (res.ok) devHint(res.data.otpHint);
            return res;
          }}
        />
      </div>
    );
  }

  if (mode.kind === "add-code") {
    const { challenge } = mode;
    return (
      <div className="space-y-4">
        <p className="text-sm text-text-secondary">
          Enter the 6-digit code we sent to{" "}
          <span className="font-medium text-text-primary">
            {challenge.destinationHint ?? "your email"}
          </span>
          .
        </p>
        <OtpForm
          submitLabel="Verify email"
          onSubmit={async (otp) => finish(await verifyAddEmail(challenge.changeId, otp))}
          onResend={async () => {
            const res = await resendAddEmail(challenge.changeId);
            if (res.ok) devHint(res.data.otpHint);
            return res;
          }}
        />
        <button
          type="button"
          className="text-sm font-medium text-brand-link underline-offset-4 hover:underline"
          onClick={() => setMode({ kind: "add" })}
        >
          Use a different email
        </button>
      </div>
    );
  }

  if (mode.kind === "choose" && emailOnFile) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-muted/40 p-4">
          <p className="text-sm text-text-secondary">Email on your account</p>
          <p className="mt-1 break-all font-medium text-text-primary">{emailOnFile}</p>
        </div>
        <Button className="w-full" onClick={() => void sendToOnFile()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
          Send a code to this email
        </Button>
        {staff ? (
          <p className="text-sm text-text-secondary">
            Not your email?{" "}
            <button
              type="button"
              className="font-medium text-brand-link underline-offset-4 hover:underline"
              onClick={onRequestChange}
            >
              Ask your Admin to change it
            </button>
          </p>
        ) : (
          <Button variant="outline" className="w-full" onClick={() => setMode({ kind: "add" })}>
            Use a different email
          </Button>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submitAdd} noValidate className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="add-email-address">
          Email
          <RequiredIndicator />
        </Label>
        <Input
          id="add-email-address"
          type="email"
          inputMode="email"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setErrors((current) => ({ ...current, email: undefined }));
          }}
          maxLength={254}
          autoComplete="email"
          placeholder="you@example.com"
          aria-invalid={Boolean(errors.email)}
          aria-describedby={errors.email ? "add-email-address-error" : undefined}
        />
        <FieldError id="add-email-address-error" className="text-xs">
          {errors.email}
        </FieldError>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="add-email-password">
          Current password
          <RequiredIndicator />
        </Label>
        <Input
          id="add-email-password"
          type="password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            setErrors((current) => ({ ...current, password: undefined }));
          }}
          maxLength={128}
          autoComplete="current-password"
          aria-invalid={Boolean(errors.password)}
          aria-describedby={errors.password ? "add-email-password-error" : undefined}
        />
        <FieldError id="add-email-password-error" className="text-xs">
          {errors.password}
        </FieldError>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row-reverse">
        <Button type="submit" disabled={busy} className="sm:flex-1">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
          Send code
        </Button>
        {emailOnFile ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => setMode({ kind: "choose" })}
            disabled={busy}
            className="sm:flex-1"
          >
            Back
          </Button>
        ) : null}
      </div>
    </form>
  );
}
