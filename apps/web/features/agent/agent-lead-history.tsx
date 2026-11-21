"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { CallLogList } from "@/features/telecaller/telecaller-call-log";
import { formatAppliedAt } from "@/features/telecaller/telecaller-requests";
import { getAgentLeadHistory, type AgentLeadHistory } from "@/lib/agent-api";
import type { LeadActivity } from "@/lib/telecaller-api";

import { humanizeStatus } from "./agent-earnings-filters";
import {
  HISTORY_KIND_LABEL,
  hiddenFieldsNote,
  historyRequests,
  timelineLabel,
} from "./agent-history-format";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; data: AgentLeadHistory }
  | { status: "error"; error: string; code: number | null };

/**
 * Everything that happened to a lead the Agent introduced (CS-022): what the
 * client applied for, the status timeline and the telecaller's calls. The
 * request and call layout follows the Telecaller client history.
 */
export function AgentLeadHistorySection({ leadId }: { leadId: string }) {
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    const res = await getAgentLeadHistory(leadId);
    setState(
      res.ok
        ? { status: "ready", data: res.data }
        : { status: "error", error: res.error, code: res.status },
    );
  }, [leadId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "error") {
    return (
      <DashboardPanel title="History">
        <FetchError status={state.code} message={state.error} onRetry={() => void load()} />
      </DashboardPanel>
    );
  }
  if (state.status === "loading") {
    return (
      <DashboardPanel title="History">
        <p className="flex items-center gap-2 text-sm text-text-secondary" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading history…
        </p>
      </DashboardPanel>
    );
  }

  const history = state.data;
  const requests = historyRequests(history);
  const staffByCall = new Map(history.calls.map((call) => [call.id, call.staff_name]));
  const activities: LeadActivity[] = history.calls.map((call) => ({
    id: call.id,
    lead_uuid: history.lead_id,
    created_at: call.created_at,
    disposition: call.disposition,
    interest_level: call.interest_level,
    follow_up_at: call.follow_up_at,
    notes: call.notes,
    request: null,
  }));
  const note = hiddenFieldsNote(history.hidden_fields.filter((key) => key !== "deal_amount"));

  return (
    <>
      <DashboardPanel
        title="Applications and deals"
        description="What this client applied for, and where each request stands."
      >
        {requests.length === 0 ? (
          <p className="text-sm text-text-secondary">Nothing applied for yet.</p>
        ) : (
          <ul className="space-y-2" aria-label="Applications and deals">
            {requests.map((request) => (
              <li
                key={request.key}
                className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
              >
                <div className="min-w-0">
                  <p className="font-medium break-words text-text-primary">{request.title}</p>
                  <p className="text-xs text-text-secondary">
                    {HISTORY_KIND_LABEL[request.kind]} · {formatAppliedAt(request.at)}
                  </p>
                  {request.detail ? (
                    <p className="text-xs break-words text-text-secondary">{request.detail}</p>
                  ) : null}
                </div>
                <StatusBadge>{humanizeStatus(request.status)}</StatusBadge>
              </li>
            ))}
          </ul>
        )}
        {history.hidden_fields.includes("deal_amount") ? (
          <p className="mt-3 text-xs text-text-secondary">Loan and deal amounts are hidden by your Admin.</p>
        ) : null}
      </DashboardPanel>

      <div className="grid gap-4 lg:grid-cols-2">
        <DashboardPanel title="Status timeline" description="Oldest first">
          <ol className="relative space-y-4 border-l border-border pl-6" aria-label="Status timeline">
            {history.timeline.map((event, index) => (
              <li key={`${event.event}-${event.at}-${index}`} className="relative">
                <span
                  className="absolute -left-[29px] top-1 h-3 w-3 rounded-full bg-brand-cta ring-4 ring-card"
                  aria-hidden="true"
                />
                <p className="text-sm font-medium text-text-primary">{timelineLabel(event)}</p>
                <p className="text-xs text-text-secondary">{formatAppliedAt(event.at)}</p>
              </li>
            ))}
          </ol>
        </DashboardPanel>

        <DashboardPanel title="Calls" description="Telecaller call outcomes, newest first">
          <CallLogList
            activities={activities}
            requests={[]}
            emptyText="No calls logged yet."
            byline={(activity) => {
              const name = staffByCall.get(activity.id);
              return name ? `by ${name}` : null;
            }}
          />
          {note ? <p className="mt-3 text-xs text-text-secondary">{note}</p> : null}
        </DashboardPanel>
      </div>
    </>
  );
}
