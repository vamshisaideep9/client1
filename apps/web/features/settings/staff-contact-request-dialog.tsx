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
  newValueError,
  requestStaffContactChange,
  resendStaffContactChange,
  verifyStaffContactChange,
  type ContactChallenge,
  type ContactField,
} from "@/lib/contact-change";
import { requiredTextError } from "@/lib/form-validation";
import { toE164 } from "@/lib/phone";

const OTP_HINT_ALLOWED = process.env.NEXT_PUBLIC_ENV !== "production";

function devHint(challenge: ContactChallenge) {
  if (challenge.otpHint && OTP_HINT_ALLOWED) {
    toast.info("Dev verification code", { description: challenge.otpHint });
  }
}

// CS-025: Telecallers, Employees and Sub Admins (managers included) cannot
// change their own phone or email. They send a request: the new value is
// proven by a code and one platform Admin approves or rejects it.
export function StaffContactRequestDialog({
  open,
  onOpenChange,
  initialField = "mobile",
  onSubmitted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialField?: ContactField;
  onSubmitted: () => void;
}) {
  const [field, setField] = React.useState<ContactField>(initialField);
  const [value, setValue] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [errors, setErrors] = React.useState<{ value?: string; password?: string }>({});
  const [busy, setBusy] = React.useState(false);
  const [challenge, setChallenge] = React.useState<ContactChallenge | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setField(initialField);
    setValue("");
    setPassword("");
    setErrors({});
    setChallenge(null);
  }, [open, initialField]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const raw = field === "mobile" ? toE164(value) : value.trim().toLowerCase();
    const next = {
      value: newValueError(field, raw) ?? undefined,
      password: requiredTextError(password, "Current password", 128),
    };
    setErrors(next);
    if (next.value || next.password) return;
    setBusy(true);
    const res = await requestStaffContactChange(field, raw, password);
    setBusy(false);
    if (!res.ok) {
      setErrors(/password/i.test(res.error) ? { password: res.error } : { value: res.error });
      return;
    }
    setPassword("");
    setChallenge(res.data);
    devHint(res.data);
  }

  const noun = field === "mobile" ? "number" : "email";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Request a contact change</DialogTitle>
          <DialogDescription>
            {challenge
              ? `Enter the 6-digit code we sent to ${challenge.destinationHint ?? `the new ${noun}`}. An Admin then reviews your request.`
              : "Your Admin manages your contact details. Confirm the new value with a code and an Admin will review it."}
          </DialogDescription>
        </DialogHeader>

        {challenge ? (
          <OtpForm
            submitLabel="Send request"
            onSubmit={async (otp) => {
              const res = await verifyStaffContactChange(challenge.changeId, otp);
              if (res.ok) {
                toast.success("Request sent.", {
                  description: "An Admin will review it. Your details change once it is approved.",
                });
                onOpenChange(false);
                onSubmitted();
              }
              return res;
            }}
            onResend={async () => {
              const res = await resendStaffContactChange(challenge.changeId);
              if (res.ok) devHint(res.data);
              return res;
            }}
          />
        ) : (
          <form onSubmit={submit} noValidate className="space-y-4">
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-text-primary">What do you want to change?</legend>
              <div className="flex flex-wrap gap-2" role="radiogroup">
                {(["mobile", "email"] as const).map((option) => (
                  <Button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={field === option}
                    variant={field === option ? "default" : "outline"}
                    size="sm"
                    onClick={() => {
                      setField(option);
                      setValue("");
                      setErrors({});
                    }}
                  >
                    {option === "mobile" ? "Phone number" : "Email"}
                  </Button>
                ))}
              </div>
            </fieldset>
            <div className="space-y-1.5">
              <Label htmlFor="staff-contact-value">
                {field === "mobile" ? "New mobile number" : "New email"}
                <RequiredIndicator />
              </Label>
              <Input
                id="staff-contact-value"
                type={field === "mobile" ? "tel" : "email"}
                inputMode={field === "mobile" ? "numeric" : "email"}
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setErrors((current) => ({ ...current, value: undefined }));
                }}
                maxLength={field === "mobile" ? 16 : 254}
                autoComplete={field === "mobile" ? "tel-national" : "email"}
                aria-invalid={Boolean(errors.value)}
                aria-describedby={errors.value ? "staff-contact-value-error" : undefined}
              />
              <FieldError id="staff-contact-value-error" className="text-xs">
                {errors.value}
              </FieldError>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="staff-contact-password">
                Current password
                <RequiredIndicator />
              </Label>
              <Input
                id="staff-contact-password"
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setErrors((current) => ({ ...current, password: undefined }));
                }}
                maxLength={128}
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? "staff-contact-password-error" : undefined}
              />
              <FieldError id="staff-contact-password-error" className="text-xs">
                {errors.password}
              </FieldError>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                Send code
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
