"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Check, Copy, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { LeadRefBadge } from "@/features/dashboard/lead-ref";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ResubmissionBadge } from "@/features/dashboard/resubmission-badge";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { DashboardBackLink, DashboardPage, DashboardHeader, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { formatMobile } from "@/lib/phone";
import { agentLeadUpdate } from "@/lib/agent-lead-update";
import { cn } from "@/lib/utils";

import { AgentLeadHistorySection } from "./agent-lead-history";
import { useAgentLeadDetail } from "./use-agent-lead-detail";
import { AGENT_LEAD_EXPIRY_POLICY, formatAgentLeadExpiry, isAgentLeadExpiryDue } from "./lead-expiry";
import { ResubmitLeadButton } from "./resubmit-lead-button";

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  assigned: "Assigned",
  working: "Working",
  converted: "Converted",
  closed: "Closed",
  released: "Released",
  expired: "Expired",
};

export function AgentLeadDetailView({ leadId }: { leadId: string }) {
  const searchParams = useSearchParams();
  const fromPage = Number(searchParams.get("page") ?? 1);
  const backHref = Number.isSafeInteger(fromPage) && fromPage > 1 ? `/dashboard/leads?page=${fromPage}` : "/dashboard/leads";
  const { lead, status, error, errorStatus, retry, update, resubmit } = useAgentLeadDetail(leadId);
  const [notes, setNotes] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const copyTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const editable = lead?.editable ?? false;

  React.useEffect(() => {
    const requirement = lead?.requirement as Record<string, unknown> | null;
    setNotes(typeof requirement?.notes === "string" ? requirement.notes : "");
    setEmail(typeof requirement?.email === "string" ? requirement.email : "");
  }, [lead]);

  React.useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    const payload = agentLeadUpdate(lead?.requirement as Record<string, unknown> | null, notes, email);
    if (!payload) { toast.info("No changes to save"); return; }
    setSaving(true);
    const res = await update(payload);
    setSaving(false);
    if (res.ok) {
      toast.success("Updated");
    } else {
      toast.error("Couldn't update this lead", { description: (res as { error?: string }).error });
    }
  }

  async function copyRegistrationLink() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/register`);
      setCopied(true);
      // Keep the toast alongside the button's own state swap below — it gives
      // screen-reader users a live-region announcement even if they miss the
      // visual icon/label change.
      toast.success("Registration link copied");
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy the registration link");
    }
  }

  if (status === "loading") {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-5 px-4 sm:px-6 lg:px-10">
        <DashboardBackLink href={backHref}>Back to leads</DashboardBackLink>
        <Skeleton className="h-9 w-64 rounded-lg" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    );
  }

  if (status === "error" || !lead) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:px-10">
        <DashboardBackLink href={backHref}>Back to leads</DashboardBackLink>
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      </div>
    );
  }

  const readOnlyReason =
    lead.status === "expired"
      ? lead.resubmittable
        ? "This lead expired and returned to the open pool. Resubmit it to restart your 30-day window."
        : "This lead returned to the open pool and can no longer be edited here."
      : isAgentLeadExpiryDue(lead.status, lead.expires_at, lead.expired_at)
        ? "This lead's conversion window ended and it is awaiting pool release."
        : "A telecaller is already working this lead, so it can no longer be edited here.";

  return (
    <DashboardPage className="max-w-4xl">
      <DashboardBackLink href={backHref}>Back to leads</DashboardBackLink>
      <DashboardHeader
        title={lead.name ?? "Lead details"}
        meta={<LeadRefBadge value={lead.lead_ref} />}
        description="Registration, attribution and operational progress"
      />
      <ResubmissionBadge count={lead.resubmit_count} at={lead.last_resubmitted_at} />
      <DashboardPanel
        title={lead.name ?? "Unnamed lead"}
        description={formatMobile(lead.mobile)}
        action={
          <span
            className={cn(
              "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium",
              lead.status === "converted" ? "bg-success/10 text-success" : "bg-muted text-text-secondary",
            )}
          >
            {STATUS_LABEL[lead.status] ?? lead.status}
          </span>
        }
      >
        <p className="text-sm text-text-secondary">
          {lead.registered
            ? "Registered: this person has verified their account. Your introduction and staff assignment are shown separately in their workspace."
            : "Not registered on the platform yet."}
        </p>
        {!lead.registered ? (
          <Button
            className="mt-3 min-w-[13rem] justify-center"
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void copyRegistrationLink()}
          >
            {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
            <span aria-live="polite">{copied ? "Copied" : "Copy registration link"}</span>
          </Button>
        ) : null}
        <p className="mt-3 text-sm font-medium text-text-primary">
          {formatAgentLeadExpiry(lead.status, lead.expires_at, lead.expired_at, {
            resubmittable: lead.resubmittable,
          })}
        </p>
        {lead.status !== "converted" && lead.status !== "closed" ? (
          <p className="mt-1 text-xs text-text-secondary">{AGENT_LEAD_EXPIRY_POLICY}</p>
        ) : null}
        {lead.resubmittable ? (
          <ResubmitLeadButton className="mt-3" leadName={lead.name} onResubmit={resubmit} />
        ) : null}
      </DashboardPanel>

      <DashboardPanel title="Requirement">
        {typeof (lead.requirement as Record<string, unknown> | null)?.property_type_label === "string" ? (
          <p className="mb-3 text-sm">Property type: {String((lead.requirement as Record<string, unknown>).property_type_label)}</p>
        ) : null}
        {typeof (lead.requirement as Record<string, unknown> | null)?.interest_title === "string" ? (
          <p className="mb-3 text-sm">
            <span className="text-text-secondary">Interested in: </span>
            <span className="font-medium text-text-primary">
              {String((lead.requirement as Record<string, unknown>).interest_title)}
            </span>
          </p>
        ) : null}
        {editable ? (
          <form className="space-y-3" onSubmit={(e) => void onSave(e)}>
            <div>
              <Label htmlFor="lead-email">Email (optional)</Label>
              <Input id="lead-email" type="email" value={email} maxLength={254} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="notes">What are they looking for?</Label>
              <Textarea
                id="notes"
                rows={3}
                maxLength={1000}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Save
            </Button>
          </form>
        ) : (
          <>
            {email ? <p className="mb-2 break-all text-sm">Email: {email}</p> : null}
            <p className="text-sm text-text-secondary">{notes || "No requirement notes."}</p>
            <p className="mt-3 text-xs text-text-secondary">{readOnlyReason}</p>
          </>
        )}
      </DashboardPanel>

      <AgentLeadHistorySection leadId={lead.id} />
    </DashboardPage>
  );
}
