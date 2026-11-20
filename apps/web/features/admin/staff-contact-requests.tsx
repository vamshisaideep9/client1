"use client";

import * as React from "react";
import { ArrowRight, Loader2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";
import {
  approveContactChangeRequest,
  CONTACT_FIELD_LABEL,
  listContactChangeRequests,
  rejectContactChangeRequest,
  type ContactChangeRequestRow,
} from "@/lib/contact-change";
import {
  piiFreeOperationalTextError,
  requiredTextError,
  type FieldErrors,
} from "@/lib/form-validation";
import { formatMobile } from "@/lib/phone";

import { ContactHistoryButton } from "./contact-history-dialog";

function shown(row: ContactChangeRequestRow, value: string | null | undefined): string {
  if (!value) return "None";
  return row.field === "mobile" ? formatMobile(value) : value;
}

// CS-025 staff contact-change requests: a Telecaller, Employee or Sub Admin
// proved the new value with a code; ONE platform Admin (never the requester,
// enforced by the API) approves or rejects with their password.
export function StaffContactRequests() {
  const [rows, setRows] = React.useState<ContactChangeRequestRow[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [active, setActive] = React.useState<ContactChangeRequestRow | null>(null);
  const [password, setPassword] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [errors, setErrors] = React.useState<FieldErrors<"password" | "reason">>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<"approve" | "reject" | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    const res = await listContactChangeRequests();
    if (res.ok) setRows(res.data);
    else setError(res.error);
    setLoading(false);
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  function close() {
    setActive(null);
    setPassword("");
    setReason("");
    setErrors({});
    setFormError(null);
  }

  async function act(kind: "approve" | "reject") {
    if (!active || busy) return;
    const next: FieldErrors<"password" | "reason"> = {
      password: requiredTextError(password, "Current Admin password", 128),
      reason:
        kind === "reject"
          ? piiFreeOperationalTextError(reason, "Rejection reason", {
              required: true,
              minLength: 3,
              maxLength: 500,
            })
          : undefined,
    };
    setErrors(next);
    setFormError(null);
    if (next.password || next.reason) return;
    setBusy(kind);
    const res =
      kind === "approve"
        ? await approveContactChangeRequest(active.id, password)
        : await rejectContactChangeRequest(active.id, reason.trim(), password);
    setBusy(null);
    if (!res.ok) {
      setFormError(res.error);
      toast.error("Could not update this request", { description: res.error });
      return;
    }
    toast.success(kind === "approve" ? "Change applied and their sessions ended" : "Request rejected");
    close();
    void load();
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Staff requests</h3>
          <p className="text-sm text-text-secondary">
            The new value was confirmed with a code. One Admin approves or rejects.
          </p>
        </div>
        {rows.length > 0 ? (
          <Badge className="bg-warning/10 text-warning">{rows.length} open</Badge>
        ) : null}
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-brand-link" aria-label="Loading" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-border bg-card p-4 text-sm text-text-secondary">
          <p>{error}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border bg-card/60 p-5 text-sm text-text-secondary">
          No staff contact changes are waiting.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="font-medium text-text-primary">
                  {row.requester_name} · {row.requester_role.replaceAll("_", " ")}
                </p>
                <p className="text-xs text-text-secondary">{CONTACT_FIELD_LABEL[row.field]}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2 break-all text-sm text-text-secondary">
                  <span>{shown(row, row.current_value)}</span>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0" aria-label="to" />
                  <span className="text-text-primary">{shown(row, row.requested_value)}</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {row.current_changed ? <Badge variant="destructive">Changed since</Badge> : null}
                <ContactHistoryButton authUserUuid={row.auth_user_uuid} name={row.requester_name} />
                <Button size="sm" onClick={() => setActive(row)}>
                  Review
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={active !== null} onOpenChange={(open) => !open && close()}>
        <DialogContent preventOutsideClose className="max-w-lg">
          {active ? (
            <>
              <DialogHeader>
                <DialogTitle>Review contact change</DialogTitle>
                <DialogDescription>
                  {active.requester_name} · {CONTACT_FIELD_LABEL[active.field]}:{" "}
                  {shown(active, active.current_value)} → {shown(active, active.requested_value)}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                {active.current_changed ? (
                  <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-text-secondary">
                    <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
                    Their current value changed after this request. Approving will cancel it; ask
                    them to send a new request.
                  </div>
                ) : null}
                <p className="text-sm text-text-secondary">
                  Approving replaces the value at once and signs them out on every device.
                </p>
                <div className="space-y-2">
                  <Label htmlFor="contact-admin-password">
                    Your current Admin password <RequiredIndicator />
                  </Label>
                  <Input
                    id="contact-admin-password"
                    type="password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setErrors((current) => ({ ...current, password: undefined }));
                    }}
                    autoComplete="current-password"
                    maxLength={128}
                    aria-invalid={Boolean(errors.password)}
                    aria-describedby={errors.password ? "contact-admin-password-error" : undefined}
                  />
                  <FieldError id="contact-admin-password-error">{errors.password}</FieldError>
                </div>
                <div className="space-y-2 border-t border-border pt-4">
                  <Label htmlFor="contact-reject-reason">PII-free rejection reason</Label>
                  <Textarea
                    id="contact-reject-reason"
                    value={reason}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setErrors((current) => ({ ...current, reason: undefined }));
                    }}
                    placeholder="Required only when rejecting; no phone numbers or emails"
                    maxLength={500}
                    aria-invalid={Boolean(errors.reason)}
                    aria-describedby={errors.reason ? "contact-reject-reason-error" : undefined}
                  />
                  <FieldError id="contact-reject-reason-error">{errors.reason}</FieldError>
                </div>
                {formError ? (
                  <p className="text-sm text-destructive" role="alert">
                    {formError}
                  </p>
                ) : null}
              </div>
              <DialogFooter className="gap-2 sm:gap-2">
                <Button variant="outline" onClick={() => void act("reject")} disabled={busy !== null}>
                  {busy === "reject" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  Reject
                </Button>
                <Button onClick={() => void act("approve")} disabled={busy !== null}>
                  {busy === "approve" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  Approve and apply
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
