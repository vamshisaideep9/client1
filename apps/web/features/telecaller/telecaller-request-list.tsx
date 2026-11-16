"use client";

import * as React from "react";
import {
  Building2,
  CalendarClock,
  ChevronDown,
  CreditCard,
  Handshake,
  Landmark,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import type { LeadActivity, RequestKind } from "@/lib/telecaller-api";
import { cn } from "@/lib/utils";

import {
  REQUEST_KIND_LABEL,
  filterCalls,
  formatAppliedAt,
  statusLabel,
  type WorkspaceRequest,
} from "./telecaller-requests";

const KIND_ICON: Record<RequestKind, LucideIcon> = {
  loan_application: Landmark,
  financial_enquiry: CreditCard,
  property_enquiry: Building2,
  site_visit: CalendarClock,
  property_deal: Handshake,
};

function RequestCard({
  request,
  selected,
  calls,
  onSelect,
}: {
  request: WorkspaceRequest;
  selected: boolean;
  calls: number;
  onSelect: () => void;
}) {
  const Icon = KIND_ICON[request.kind];
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={cn(
          "flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none sm:p-4",
          selected
            ? "border-brand-cta bg-nav-tint"
            : "border-border bg-card hover:border-brand-cta/60 hover:bg-muted/30",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg",
            selected ? "bg-brand-cta text-white" : "bg-muted text-brand-heading",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="min-w-0 break-words font-medium text-text-primary">{request.title}</span>
            <Badge variant="secondary" className="shrink-0">
              {statusLabel(request.status)}
            </Badge>
          </span>
          <span className="mt-0.5 block text-xs text-text-secondary">
            {REQUEST_KIND_LABEL[request.kind]}
            {request.detail ? ` · ${request.detail}` : ""}
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-secondary">
            <span>
              Applied <time dateTime={request.applied_at}>{formatAppliedAt(request.applied_at)}</time>
            </span>
            <span className="tabular-nums">
              {calls === 1 ? "1 call" : `${calls} calls`}
            </span>
          </span>
        </span>
      </button>
    </li>
  );
}

/**
 * Everything the client asked for on this lead, newest first. Finished
 * requests (disbursed, closed, done) fold under "Previous" so a client who
 * comes back does not see their old loans mixed into the new one.
 */
export function TelecallerRequestList({
  requests,
  activities,
  selectedKey,
  onSelect,
  footer,
}: {
  requests: WorkspaceRequest[];
  activities: LeadActivity[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  footer?: React.ReactNode;
}) {
  const active = requests.filter((request) => !request.finished);
  const previous = requests.filter((request) => request.finished);
  const selectedIsPrevious = previous.some((request) => request.key === selectedKey);

  const renderCards = (items: WorkspaceRequest[]) => (
    <ul className="space-y-2">
      {items.map((request) => (
        <RequestCard
          key={request.key}
          request={request}
          selected={request.key === selectedKey}
          calls={filterCalls(activities, request.key).length}
          onSelect={() => onSelect(request.key)}
        />
      ))}
    </ul>
  );

  return (
    <DashboardPanel
      title="Applications & requests"
      description="What the client asked for and when. Choose one to work on it."
    >
      {requests.length === 0 ? (
        <p className="text-sm text-text-secondary">
          No application, enquiry or site visit on this lead yet.
        </p>
      ) : (
        <div className="space-y-4">
          {active.length > 0 ? renderCards(active) : (
            <p className="text-sm text-text-secondary">Nothing in progress right now.</p>
          )}
          {previous.length > 0 ? (
            <details className="group" open={selectedIsPrevious || active.length === 0}>
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg text-sm font-medium text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <ChevronDown
                  className="h-4 w-4 text-text-secondary transition-transform group-open:rotate-180 motion-reduce:transition-none"
                  aria-hidden="true"
                />
                Previous applications ({previous.length})
              </summary>
              <div className="mt-2">{renderCards(previous)}</div>
            </details>
          ) : null}
        </div>
      )}
      {footer ? <div className="mt-4 border-t border-border pt-4">{footer}</div> : null}
    </DashboardPanel>
  );
}
