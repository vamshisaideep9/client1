"use client";

import * as React from "react";
import { ContactActions } from "@/components/contact-actions";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { FieldError, RequiredIndicator } from "@/components/ui/field-error";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { LongNoteField } from "@/features/dashboard/long-note-field";
import { UserAvatar } from "@/components/user-avatar";
import {
  DashboardBackLink,
  DashboardFormSection,
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import {
  apiIssuesToFieldErrors,
  focusFirstInvalidField,
  type FieldErrors,
} from "@/lib/form-validation";
import { formatMobile } from "@/lib/phone";
import type { LeadActivityCreate, TelecallerLeadDetail } from "@/lib/telecaller-api";
import { cn } from "@/lib/utils";

import { formatReferrer } from "./lead-signal-filters";
import { CallLogPanel } from "./telecaller-call-log";
import { ClientHistoryButton } from "./telecaller-client-history";
import {
  validateCallLog,
  type CallLogField,
} from "./telecaller-lead-detail-validation";
import {
  DISPOSITION_OPTIONS,
  INTEREST_OPTIONS,
  LEAD_STATUS_OPTIONS,
  STATUS_LABEL,
  statusAccentBorderClass,
} from "./telecaller-lead-status";
import { TelecallerLoanAppsSection } from "./telecaller-loan-apps-section";
import {
  CreateDealForm,
  TelecallerPropertyDealsSection,
} from "./telecaller-property-deals-section";
import { TelecallerRequestDetails } from "./telecaller-request-details";
import { TelecallerRequestList } from "./telecaller-request-list";
import {
  buildWorkspaceRequests,
  defaultRequestKey,
  formatAppliedAt,
  parseRequestKey,
  type WorkspaceRequest,
} from "./telecaller-requests";
import { TelecallerTasksSection } from "./telecaller-tasks-section";
import { ManagerNotesPanel } from "@/features/team/manager-notes-panel";
import { useTelecallerLeadDetail } from "./use-telecaller-lead-detail";

type CallFormField = CallLogField | "disposition" | "interestLevel";
type Actions = ReturnType<typeof useTelecallerLeadDetail>;

const GENERAL = "general";

/** The workspace for one selected request: its own pipeline or details. */
function RequestWorkspace({
  lead,
  request,
  actions,
}: {
  lead: TelecallerLeadDetail;
  request: WorkspaceRequest;
  actions: Pick<Actions, "addTxn" | "updateApp" | "createDeal" | "updateDeal">;
}) {
  switch (request.kind) {
    case "loan_application": {
      const application = lead.loan_applications?.find((item) => item.id === request.id);
      return application ? (
        <TelecallerLoanAppsSection
          applications={[application]}
          onAddTxn={actions.addTxn}
          onUpdateApp={actions.updateApp}
        />
      ) : null;
    }
    case "property_deal": {
      const deal = lead.property_deals?.find((item) => item.id === request.id);
      return deal ? (
        <TelecallerPropertyDealsSection
          leadId={lead.id}
          deals={[deal]}
          showCreate={false}
          onCreateDeal={actions.createDeal}
          onUpdateDeal={actions.updateDeal}
        />
      ) : null;
    }
    case "financial_enquiry": {
      const item = lead.financial_enquiries?.find((entry) => entry.id === request.id);
      return item ? <TelecallerRequestDetails request={{ kind: request.kind, item }} /> : null;
    }
    case "property_enquiry": {
      const item = lead.property_enquiries?.find((entry) => entry.id === request.id);
      return item ? <TelecallerRequestDetails request={{ kind: request.kind, item }} /> : null;
    }
    case "site_visit": {
      const item = lead.site_visits?.find((entry) => entry.id === request.id);
      return item ? <TelecallerRequestDetails request={{ kind: request.kind, item }} /> : null;
    }
  }
}

export function TelecallerLeadDetailView({ leadId }: { leadId: string }) {
  const {
    lead,
    status,
    error,
    errorStatus,
    retry,
    updateStatus,
    logCall,
    addTxn,
    raiseTask,
    updateApp,
    createDeal,
    updateDeal,
  } = useTelecallerLeadDetail(leadId);

  const requests = React.useMemo(() => (lead ? buildWorkspaceRequests(lead) : []), [lead]);
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const selected = requests.find((request) => request.key === selectedKey) ?? null;

  // Keep a valid selection as the lead (re)loads: the first visit opens the
  // newest request still in progress; a vanished selection falls back too.
  React.useEffect(() => {
    if (!lead) return;
    if (!selectedKey || !requests.some((request) => request.key === selectedKey)) {
      setSelectedKey(defaultRequestKey(requests));
    }
  }, [lead, requests, selectedKey]);

  const [aboutKey, setAboutKey] = React.useState<string>(GENERAL);
  React.useEffect(() => {
    setAboutKey(selectedKey ?? GENERAL);
  }, [selectedKey]);

  const [disposition, setDisposition] = React.useState<LeadActivityCreate["disposition"] | "">("");
  const [interestLevel, setInterestLevel] = React.useState<
    NonNullable<LeadActivityCreate["interest_level"]> | ""
  >("");
  const [notes, setNotes] = React.useState("");
  const [followUpAt, setFollowUpAt] = React.useState("");
  const [loggingCall, setLoggingCall] = React.useState(false);
  const [updatingStatus, setUpdatingStatus] = React.useState(false);
  const [callErrors, setCallErrors] = React.useState<FieldErrors<CallFormField>>({});
  const callFormRef = React.useRef<HTMLFormElement>(null);

  function showCallErrors(nextErrors: FieldErrors<CallFormField>) {
    setCallErrors(nextErrors);
    requestAnimationFrame(() => {
      if (callFormRef.current) focusFirstInvalidField(callFormRef.current);
    });
  }

  async function onLogCall(e: React.FormEvent) {
    e.preventDefault();
    const nextErrors: FieldErrors<CallFormField> = {
      ...validateCallLog({ followUpAt, notes }),
      disposition: disposition ? undefined : "Choose a call outcome.",
      interestLevel:
        disposition === "connected" && !interestLevel ? "Choose an interest level." : undefined,
    };
    const filteredErrors = Object.fromEntries(
      Object.entries(nextErrors).filter((entry): entry is [CallFormField, string] =>
        Boolean(entry[1]),
      ),
    );
    if (Object.keys(filteredErrors).length > 0) {
      showCallErrors(filteredErrors);
      return;
    }

    setCallErrors({});
    setLoggingCall(true);
    const res = await logCall({
      disposition: disposition as LeadActivityCreate["disposition"],
      interest_level: disposition === "connected" ? interestLevel || null : null,
      notes: notes.trim() || null,
      follow_up_at: followUpAt ? new Date(followUpAt).toISOString() : null,
      request: aboutKey === GENERAL ? null : parseRequestKey(aboutKey),
    });
    setLoggingCall(false);
    if (res.ok) {
      toast.success("Call logged");
      setDisposition("");
      setInterestLevel("");
      setNotes("");
      setFollowUpAt("");
      setCallErrors({});
    } else {
      const serverErrors = apiIssuesToFieldErrors(res.issues, {
        disposition: "disposition",
        interest_level: "interestLevel",
        notes: "notes",
        follow_up_at: "followUpAt",
      });
      if (Object.keys(serverErrors).length > 0) showCallErrors(serverErrors);
      toast.error("Couldn't log this call", { description: res.error });
    }
  }

  async function onStatusChange(next: "working" | "converted" | "closed") {
    setUpdatingStatus(true);
    const res = await updateStatus({ status: next });
    setUpdatingStatus(false);
    if (res.ok) {
      toast.success("Status updated");
    } else {
      toast.error("Couldn't update status", { description: res.error });
    }
  }

  if (status === "loading" && !lead) {
    return (
      <DashboardPage className="space-y-5">
        <Skeleton className="h-9 w-64 rounded-lg" />
        <Skeleton className="h-48 rounded-2xl" />
      </DashboardPage>
    );
  }

  if (status === "error" || !lead) {
    return (
      <DashboardPage>
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      </DashboardPage>
    );
  }

  const leadName = lead.name ?? "Unnamed lead";
  const latest = lead.latest_request;
  const aboutRequest = requests.find((request) => request.key === aboutKey);
  const aboutLabel = aboutRequest
    ? `${aboutRequest.title} · ${formatAppliedAt(aboutRequest.applied_at)}`
    : "General (not one application)";

  return (
    <DashboardPage>
      <DashboardBackLink href="/dashboard/leads">Back to leads</DashboardBackLink>

      <DashboardHeader
        title={leadName}
        description={
          latest
            ? `${formatMobile(lead.mobile)} · Latest: ${latest.title}, applied ${formatAppliedAt(latest.applied_at)}`
            : `${formatMobile(lead.mobile)} · Review progress, record the next action, and keep follow-ups current.`
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <ContactActions mobile={lead.mobile} name={leadName} />
            <ClientHistoryButton leadId={lead.id} name={leadName} />
          </div>
        }
      />

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-5 xl:col-start-1 xl:row-start-1">
          <TelecallerRequestList
            requests={requests}
            activities={lead.activities}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
            footer={
              lead.business_line === "real_estate" ? (
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Open a property deal</h3>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    Start a deal when the client is ready to move on a property.
                  </p>
                  <CreateDealForm leadId={lead.id} onCreate={createDeal} />
                </div>
              ) : null
            }
          />

          {selected ? (
            <RequestWorkspace
              lead={lead}
              request={selected}
              actions={{ addTxn, updateApp, createDeal, updateDeal }}
            />
          ) : null}
        </div>

        <aside className="min-w-0 space-y-5 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:sticky xl:top-24">
          <DashboardPanel
            title="Lead status"
            description="Keep the overall lead state aligned with the latest conversation."
            className={cn("border-l-4", statusAccentBorderClass(lead.status))}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <UserAvatar name={lead.name} size="lg" />
                <div className="min-w-0">
                  <p className="truncate font-medium text-text-primary">{leadName}</p>
                  <p className="text-sm text-text-secondary">{formatMobile(lead.mobile)}</p>
                  {/* Absent when Admin hides "Referred by"; null when nobody referred. */}
                  {lead.referrer !== undefined ? (
                    <p className="mt-0.5 text-xs text-text-secondary" data-testid="lead-referrer">
                      Referred by{" "}
                      <span className="font-medium text-text-primary">
                        {formatReferrer(lead.referrer) ?? "No one (direct lead)"}
                      </span>
                    </p>
                  ) : null}
                </div>
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium",
                  lead.status === "converted"
                    ? "bg-success/10 text-success"
                    : "bg-muted text-text-secondary",
                )}
              >
                {STATUS_LABEL[lead.status] ?? lead.status}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              {LEAD_STATUS_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="sm"
                  variant={lead.status === option.value ? "default" : "outline"}
                  disabled={updatingStatus || lead.status === option.value}
                  onClick={() => void onStatusChange(option.value)}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </DashboardPanel>

          <DashboardPanel
            title="Log a call"
            description="Record the outcome and schedule the next follow-up."
          >
            <form
              ref={callFormRef}
              className="space-y-5"
              noValidate
              onSubmit={(e) => void onLogCall(e)}
            >
              <DashboardFormSection title="Outcome">
                <div>
                  <Label htmlFor="lead-call-about">About</Label>
                  <Select
                    value={aboutKey}
                    // Radix reports "" when the value changes before its options
                    // have rendered; keep the chosen request instead.
                    onValueChange={(value) => value && setAboutKey(value)}
                  >
                    <SelectTrigger id="lead-call-about" className="w-full">
                      {/* Explicit label: the selection can change before the
                          option list has ever rendered. */}
                      <SelectValue className="min-w-0 overflow-hidden">
                        <span className="block min-w-0 truncate">{aboutLabel}</span>
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={GENERAL}>General (not one application)</SelectItem>
                      {requests.map((request) => (
                        <SelectItem key={request.key} value={request.key}>
                          {request.title} · {formatAppliedAt(request.applied_at)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="lead-call-disposition">
                    Call outcome
                    <RequiredIndicator />
                  </Label>
                  <Select
                    value={disposition}
                    onValueChange={(value) => {
                      setDisposition(value as typeof disposition);
                      setCallErrors((current) => ({
                        ...current,
                        disposition: undefined,
                        interestLevel: undefined,
                      }));
                    }}
                  >
                    <SelectTrigger
                      id="lead-call-disposition"
                      className="w-full"
                      aria-required="true"
                      aria-invalid={Boolean(callErrors.disposition)}
                      aria-describedby={
                        callErrors.disposition ? "lead-call-disposition-error" : undefined
                      }
                    >
                      <SelectValue placeholder="Choose an outcome" />
                    </SelectTrigger>
                    <SelectContent>
                      {DISPOSITION_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FieldError id="lead-call-disposition-error">
                    {callErrors.disposition}
                  </FieldError>
                </div>

                {disposition === "connected" ? (
                  <div>
                    <Label htmlFor="lead-call-interest">
                      Interest level
                      <RequiredIndicator />
                    </Label>
                    <Select
                      value={interestLevel}
                      onValueChange={(value) => {
                        setInterestLevel(value as typeof interestLevel);
                        setCallErrors((current) => ({ ...current, interestLevel: undefined }));
                      }}
                    >
                      <SelectTrigger
                        id="lead-call-interest"
                        className="w-full"
                        aria-required="true"
                        aria-invalid={Boolean(callErrors.interestLevel)}
                        aria-describedby={
                          callErrors.interestLevel ? "lead-call-interest-error" : undefined
                        }
                      >
                        <SelectValue placeholder="Choose a level" />
                      </SelectTrigger>
                      <SelectContent>
                        {INTEREST_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FieldError id="lead-call-interest-error">
                      {callErrors.interestLevel}
                    </FieldError>
                  </div>
                ) : null}
              </DashboardFormSection>

              <DashboardFormSection title="Follow-up">
                <div>
                  <Label htmlFor="lead-call-follow-up">Follow up at (optional)</Label>
                  <input
                    id="lead-call-follow-up"
                    name="follow_up_at"
                    type="datetime-local"
                    value={followUpAt}
                    onChange={(e) => {
                      setFollowUpAt(e.target.value);
                      setCallErrors((current) => ({ ...current, followUpAt: undefined }));
                    }}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    aria-invalid={Boolean(callErrors.followUpAt)}
                    aria-describedby={
                      callErrors.followUpAt ? "lead-call-follow-up-error" : undefined
                    }
                  />
                  <FieldError id="lead-call-follow-up-error">
                    {callErrors.followUpAt}
                  </FieldError>
                </div>
                <div>
                  <Label htmlFor="lead-call-notes">Notes (optional)</Label>
                  <LongNoteField
                    id="lead-call-notes"
                    counterId="lead-call-notes-count"
                    name="notes"
                    rows={3}
                    value={notes}
                    onChange={(e) => {
                      setNotes(e.target.value);
                      setCallErrors((current) => ({ ...current, notes: undefined }));
                    }}
                    placeholder="What did the lead say?"
                    aria-invalid={Boolean(callErrors.notes)}
                    aria-describedby={callErrors.notes ? "lead-call-notes-error" : undefined}
                  />
                  <FieldError id="lead-call-notes-error">{callErrors.notes}</FieldError>
                </div>
              </DashboardFormSection>

              <Button type="submit" className="w-full" disabled={loggingCall}>
                {loggingCall ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Log call
              </Button>
            </form>
          </DashboardPanel>
        </aside>

        <div className="min-w-0 xl:col-start-1 xl:row-start-2">
          <ManagerNotesPanel notes={lead.manager_notes} />
          <CallLogPanel activities={lead.activities} requests={requests} selected={selected} />
        </div>
      </div>

      <TelecallerTasksSection tasks={lead.tasks} onRaiseTask={raiseTask} />
    </DashboardPage>
  );
}
