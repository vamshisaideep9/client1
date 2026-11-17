"use client";

import * as React from "react";
import Link from "next/link";
import { BadgeCheck, Mail, Smartphone } from "lucide-react";
import { toast } from "sonner";

import { AddEmailForm } from "@/components/auth/add-email-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getMe, type Me } from "@/lib/auth";
import {
  cancelContactChange,
  CONTACT_FIELD_LABEL,
  getActiveContactChange,
  type ActiveContactChange,
  type ContactField,
} from "@/lib/contact-change";
import { formatMobile } from "@/lib/phone";

import { ContactChangeDialog } from "./contact-change-dialog";
import { StaffContactRequestDialog } from "./staff-contact-request-dialog";

// CS-025 phone and email. Clients, Agents and Admins change them here with a
// password and codes to the old and the new value; Telecallers, Employees and
// Sub Admins send a request an Admin approves. Anyone who lost their number
// uses the support-assisted recovery (/change-mobile).
export function ContactDetailsCard({
  me,
  mode,
  onMeChange,
}: {
  me: Me;
  mode: "self" | "request";
  onMeChange: (me: Me) => void;
}) {
  const [active, setActive] = React.useState<ActiveContactChange | null>(null);
  const [changing, setChanging] = React.useState<ContactField | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [requesting, setRequesting] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  const loadActive = React.useCallback(async () => {
    const res = await getActiveContactChange();
    if (res.ok) setActive(res.data);
  }, []);

  React.useEffect(() => {
    void loadActive();
  }, [loadActive]);

  const emailVerified = me.emailVerified && Boolean(me.email);
  const pendingRequest = active?.kind === "staff_request" && active.status === "pending_approval";

  async function withdraw() {
    if (!active || busy) return;
    setBusy(true);
    const res = await cancelContactChange(active.changeId);
    setBusy(false);
    if (!res.ok) {
      toast.error(res.error || "Couldn't withdraw the request.");
      return;
    }
    toast.success(pendingRequest ? "Request withdrawn." : "Change cancelled.");
    setActive(null);
  }

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-6" aria-labelledby="contact-details-heading">
      <div>
        <h2 id="contact-details-heading" className="text-sm font-semibold text-text-primary">
          Phone and email
        </h2>
        <p className="text-sm text-text-secondary">
          {mode === "self"
            ? "Changing either needs your password and codes sent to the old and the new one. Every device is signed out afterwards."
            : "Your Admin manages these. Send a request with the new value and an Admin reviews it."}
        </p>
      </div>

      <dl className="divide-y divide-border rounded-lg border border-border">
        <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
            <div className="min-w-0">
              <dt className="text-xs text-text-secondary">Mobile number</dt>
              <dd className="font-medium tabular-nums text-text-primary">{formatMobile(me.mobile)}</dd>
            </div>
          </div>
          {mode === "self" ? (
            <Button variant="outline" size="sm" onClick={() => setChanging("mobile")} disabled={pendingRequest}>
              Change phone
            </Button>
          ) : null}
        </div>
        <div className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <Mail className="mt-0.5 h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
            <div className="min-w-0">
              <dt className="text-xs text-text-secondary">Email</dt>
              <dd className="flex flex-wrap items-center gap-2 break-all font-medium text-text-primary">
                {me.email ?? <span className="font-normal text-text-secondary">Not added</span>}
                {me.email ? (
                  emailVerified ? (
                    <Badge variant="outline" className="gap-1 text-success">
                      <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      Verified
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-warning">
                      Not verified
                    </Badge>
                  )
                ) : null}
              </dd>
            </div>
          </div>
          {mode === "self" ? (
            emailVerified ? (
              <Button variant="outline" size="sm" onClick={() => setChanging("email")}>
                Change email
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
                {me.email ? "Verify or replace" : "Add email"}
              </Button>
            )
          ) : null}
        </div>
      </dl>

      {active && active.kind !== "email_add" ? (
        <div className="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/5 p-4 text-sm sm:flex-row sm:items-center sm:justify-between" role="status">
          <p className="text-text-primary">
            {pendingRequest
              ? `Your ${CONTACT_FIELD_LABEL[active.field].toLowerCase()} change to ${active.newValueHint ?? "a new value"} is waiting for an Admin.`
              : `A ${CONTACT_FIELD_LABEL[active.field].toLowerCase()} change is in progress.`}
          </p>
          <div className="flex gap-2">
            {active.kind === "self_service" ? (
              <Button size="sm" onClick={() => setChanging(active.field)}>
                Continue
              </Button>
            ) : null}
            <Button size="sm" variant="outline" onClick={() => void withdraw()} disabled={busy}>
              {pendingRequest ? "Withdraw" : "Cancel"}
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {mode === "request" ? (
          <Button onClick={() => setRequesting(true)} disabled={Boolean(active)}>
            Request a contact change
          </Button>
        ) : null}
        <p className="text-sm text-text-secondary">
          Lost access to your number?{" "}
          <Link href="/change-mobile" className="font-medium text-brand-link underline-offset-4 hover:underline">
            Recover your account
          </Link>
        </p>
      </div>

      {mode === "self" && changing ? (
        <ContactChangeDialog
          field={changing}
          open={changing !== null}
          resume={active}
          onOpenChange={(open) => {
            if (!open) {
              setChanging(null);
              void loadActive();
            }
          }}
        />
      ) : null}

      {mode === "request" ? (
        <StaffContactRequestDialog
          open={requesting}
          onOpenChange={setRequesting}
          onSubmitted={() => void loadActive()}
        />
      ) : null}

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{me.email ? "Verify your email" : "Add your email"}</DialogTitle>
            <DialogDescription>
              We send a code to the address to make sure it is yours.
            </DialogDescription>
          </DialogHeader>
          {adding ? (
            <AddEmailForm
              emailOnFile={me.email}
              staff={false}
              onVerified={async () => {
                setAdding(false);
                const res = await getMe();
                if (res.ok) onMeChange(res.data);
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
