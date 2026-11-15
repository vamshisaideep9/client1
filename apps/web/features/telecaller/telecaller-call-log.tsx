"use client";

import * as React from "react";
import { Maximize2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import {
  WORKSPACE_DIALOG_FILTERED_CLASS,
  WorkspaceDialogHeader,
} from "@/features/dashboard/workspace-dialog";
import type { LeadActivity } from "@/lib/telecaller-api";
import { cn } from "@/lib/utils";

import { DISPOSITION_LABEL, dispositionDotClass, formatDateTime } from "./telecaller-lead-status";
import {
  REQUEST_KIND_LABEL,
  filterCalls,
  formatAppliedAt,
  requestKey,
  type CallFilter,
  type WorkspaceRequest,
} from "./telecaller-requests";

function requestLabel(activity: LeadActivity, byKey: Map<string, WorkspaceRequest>): string {
  if (!activity.request) return "General";
  const request = byKey.get(requestKey(activity.request));
  return request ? request.title : REQUEST_KIND_LABEL[activity.request.kind];
}

/** Timeline of call attempts, newest first. Notes keep their line breaks. */
export function CallLogList({
  activities,
  requests,
  showRequest = false,
  emptyText = "No calls logged yet.",
}: {
  activities: LeadActivity[];
  requests: WorkspaceRequest[];
  showRequest?: boolean;
  emptyText?: string;
}) {
  const byKey = React.useMemo(
    () => new Map(requests.map((request) => [request.key, request])),
    [requests],
  );
  if (activities.length === 0) {
    return <p className="text-sm text-text-secondary">{emptyText}</p>;
  }
  return (
    <ol className="relative space-y-5 border-l border-border pl-6">
      {activities.map((activity) => (
        <li key={activity.id} className="relative">
          <span
            className={cn(
              "absolute -left-[29px] top-1 h-3 w-3 rounded-full ring-4 ring-card",
              dispositionDotClass(activity.disposition),
            )}
            aria-hidden="true"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-text-primary">
              {DISPOSITION_LABEL[activity.disposition] ?? activity.disposition}
              {activity.interest_level ? ` · ${activity.interest_level}` : ""}
            </span>
            <span className="text-xs text-text-secondary">{formatAppliedAt(activity.created_at)}</span>
          </div>
          {showRequest ? (
            <p className="mt-0.5 text-xs font-medium text-brand-link">
              {requestLabel(activity, byKey)}
            </p>
          ) : null}
          {activity.notes ? (
            <p className="mt-1 whitespace-pre-line break-words text-sm text-text-secondary">
              {activity.notes}
            </p>
          ) : null}
          {activity.follow_up_at ? (
            <p className="mt-1 text-xs text-text-secondary">
              Follow up: {formatDateTime(activity.follow_up_at)}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function CallFilterChips({
  value,
  onChange,
  activities,
  requests,
}: {
  value: CallFilter;
  onChange: (value: CallFilter) => void;
  activities: LeadActivity[];
  requests: WorkspaceRequest[];
}) {
  const options: { value: CallFilter; label: string }[] = [
    { value: "all", label: "All calls" },
    ...requests.map((request) => ({ value: request.key, label: request.title })),
    { value: "general", label: "General" },
  ];
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(next) => next && onChange(next)}
      aria-label="Show calls for"
      className="flex w-full flex-wrap justify-start gap-2"
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          className="max-w-full px-3"
        >
          <span className="truncate">{option.label}</span>
          <span className="ml-1.5 tabular-nums text-text-secondary">
            {filterCalls(activities, option.value).length}
          </span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/**
 * Calls for the selected request, with a full-screen window that shows every
 * call on the lead filtered by request (or "General" calls not tied to one).
 */
export function CallLogPanel({
  activities,
  requests,
  selected,
}: {
  activities: LeadActivity[];
  requests: WorkspaceRequest[];
  selected: WorkspaceRequest | null;
}) {
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState<CallFilter>("all");
  const scoped = selected ? filterCalls(activities, selected.key) : activities;

  function openFullScreen() {
    setFilter(selected ? selected.key : "all");
    setOpen(true);
  }

  return (
    <DashboardPanel
      title={selected ? "Calls about this request" : "Call history"}
      description={
        selected
          ? `${scoped.length} of ${activities.length} calls on this lead are about ${selected.title}.`
          : `${activities.length} calls logged`
      }
      action={
        <Button type="button" variant="outline" size="sm" onClick={openFullScreen}>
          <Maximize2 className="h-4 w-4" aria-hidden="true" />
          Full call log
        </Button>
      }
    >
      <CallLogList
        activities={scoped}
        requests={requests}
        emptyText={
          selected
            ? "No calls logged for this request yet. Choose it under “About” when you log a call."
            : "No calls logged yet."
        }
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false} className={WORKSPACE_DIALOG_FILTERED_CLASS}>
          <WorkspaceDialogHeader
            title="Call log"
            description="Every call on this lead. Filter by application, enquiry or visit."
            closeLabel="Close call log"
          />
          <div className="border-b border-border py-3">
            <CallFilterChips
              value={filter}
              onChange={setFilter}
              activities={activities}
              requests={requests}
            />
          </div>
          <div className="min-h-0 overflow-y-auto overscroll-contain py-4 pr-1">
            <div className="mx-auto max-w-3xl">
              <CallLogList
                activities={filterCalls(activities, filter)}
                requests={requests}
                showRequest={filter === "all"}
                emptyText="No calls match this filter."
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </DashboardPanel>
  );
}
