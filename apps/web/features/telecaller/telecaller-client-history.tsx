"use client";

import * as React from "react";
import { History, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  WORKSPACE_DIALOG_CLASS,
  WorkspaceDialogHeader,
} from "@/features/dashboard/workspace-dialog";
import { FetchError } from "@/features/dashboard/fetch-error";
import { getClientHistory, type TelecallerClientHistory } from "@/lib/telecaller-api";

import { CallLogList } from "./telecaller-call-log";
import { STATUS_LABEL } from "./telecaller-lead-status";
import {
  REQUEST_KIND_LABEL,
  formatAppliedAt,
  requestKey,
  statusLabel,
  type WorkspaceRequest,
} from "./telecaller-requests";

type LoadState =
  | { status: "idle" | "loading" }
  | { status: "ready"; data: TelecallerClientHistory }
  | { status: "error"; error: string; code: number | null };

/**
 * Client-wise call history: every journey this client has had on the line
 * with this Telecaller (an earlier closed lead, the current one), each with
 * what was applied for and the calls made. Only the viewer's own calls.
 */
export function ClientHistoryButton({ leadId, name }: { leadId: string; name: string }) {
  const [open, setOpen] = React.useState(false);
  const [state, setState] = React.useState<LoadState>({ status: "idle" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    const res = await getClientHistory(leadId);
    setState(
      res.ok
        ? { status: "ready", data: res.data }
        : { status: "error", error: res.error, code: res.status },
    );
  }, [leadId]);

  const data = state.status === "ready" ? state.data : null;

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (next) void load();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <Button type="button" variant="outline" onClick={() => onOpenChange(true)}>
        <History className="h-4 w-4" aria-hidden="true" />
        Client history
      </Button>
      <DialogContent showCloseButton={false} className={WORKSPACE_DIALOG_CLASS}>
        <WorkspaceDialogHeader
          title={`${name} · client history`}
          description="Every journey of this client assigned to you, with what they applied for and your calls."
          closeLabel="Close client history"
        />
        <div className="min-h-0 overflow-y-auto overscroll-contain py-4 pr-1">
          <div className="mx-auto max-w-3xl">
            {state.status === "error" ? (
              <FetchError status={state.code} message={state.error} onRetry={() => void load()} />
            ) : !data ? (
              <p className="flex items-center gap-2 text-sm text-text-secondary" role="status">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading history…
              </p>
            ) : (
              <ol className="space-y-6">
                {data.leads.map((journey, index) => {
                  const requests: WorkspaceRequest[] = journey.requests.map((request) => ({
                    ...request,
                    key: requestKey(request),
                    finished: false,
                    detail: null,
                  }));
                  return (
                    <li
                      key={journey.lead_id}
                      className="overflow-hidden rounded-xl border border-border bg-card"
                    >
                      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/25 px-4 py-3">
                        <div>
                          <h3 className="font-semibold text-text-primary">
                            {journey.lead_id === leadId
                              ? "Current journey"
                              : `Earlier journey ${data.leads.length - index}`}
                          </h3>
                          <p className="text-xs text-text-secondary">
                            Started {formatAppliedAt(journey.created_at)}
                          </p>
                        </div>
                        <Badge variant="secondary">
                          {STATUS_LABEL[journey.status] ?? journey.status}
                        </Badge>
                      </header>
                      <div className="space-y-4 p-4">
                        {journey.requests.length > 0 ? (
                          <ul className="flex flex-wrap gap-2" aria-label="Requests on this journey">
                            {journey.requests.map((request) => (
                              <li
                                key={requestKey(request)}
                                className="rounded-lg border border-border px-3 py-2 text-xs"
                              >
                                <span className="font-medium text-text-primary">{request.title}</span>
                                <span className="block text-text-secondary">
                                  {REQUEST_KIND_LABEL[request.kind]} · {statusLabel(request.status)} ·{" "}
                                  {formatAppliedAt(request.applied_at)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-sm text-text-secondary">No application on this journey.</p>
                        )}
                        <CallLogList
                          activities={journey.activities}
                          requests={requests}
                          showRequest
                          emptyText="You haven't logged calls on this journey."
                        />
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
