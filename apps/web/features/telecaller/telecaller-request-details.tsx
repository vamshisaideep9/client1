"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import type {
  TelecallerFinancialEnquiry,
  TelecallerPropertyEnquiry,
  TelecallerSiteVisit,
} from "@/lib/telecaller-api";

import { REQUEST_KIND_LABEL, formatAppliedAt, statusLabel } from "./telecaller-requests";

const SLOT_LABEL: Record<string, string> = {
  morning: "Morning",
  afternoon: "Afternoon",
  evening: "Evening",
};

function formatDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

function Fields({ rows }: { rows: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
      {rows.map((row) => (
        <div key={row.label} className="min-w-0">
          <dt className="text-xs text-text-secondary">{row.label}</dt>
          <dd className="mt-0.5 break-words text-sm text-text-primary">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export type DetailRequest =
  | { kind: "financial_enquiry"; item: TelecallerFinancialEnquiry }
  | { kind: "property_enquiry"; item: TelecallerPropertyEnquiry }
  | { kind: "site_visit"; item: TelecallerSiteVisit };

/** Read-only details for requests that have no pipeline of their own. */
export function TelecallerRequestDetails({ request }: { request: DetailRequest }) {
  if (request.kind === "financial_enquiry") {
    const { item } = request;
    return (
      <DashboardPanel
        title={item.product_name}
        description={REQUEST_KIND_LABEL.financial_enquiry}
        action={<Badge variant="secondary">{statusLabel(item.status)}</Badge>}
      >
        <Fields
          rows={[
            { label: "Product type", value: statusLabel(item.product_category) },
            { label: "Applied", value: formatAppliedAt(item.submitted_at) },
          ]}
        />
      </DashboardPanel>
    );
  }

  if (request.kind === "property_enquiry") {
    const { item } = request;
    return (
      <DashboardPanel
        title={item.title}
        description={`${REQUEST_KIND_LABEL.property_enquiry} · ${item.locality}, ${item.city}`}
        action={<Badge variant="secondary">{statusLabel(item.status)}</Badge>}
      >
        <Fields
          rows={[
            { label: "Submitted on", value: formatAppliedAt(item.created_at) },
            { label: "Location", value: `${item.locality}, ${item.city}` },
            {
              label: "Client's message",
              value: item.message ? (
                <span className="whitespace-pre-line">{item.message}</span>
              ) : (
                "No message"
              ),
            },
          ]}
        />
      </DashboardPanel>
    );
  }

  const { item } = request;
  return (
    <DashboardPanel
      title={item.title}
      description={`${REQUEST_KIND_LABEL.site_visit} · ${item.locality}, ${item.city}`}
      action={<Badge variant="secondary">{statusLabel(item.status)}</Badge>}
    >
      <Fields
        rows={[
          // When the client sent the request, not when the visit happens.
          { label: "Submitted on", value: formatAppliedAt(item.created_at) },
          {
            label: "Visit on",
            value: `${formatDay(item.preferred_date)} · ${SLOT_LABEL[item.preferred_time_slot] ?? item.preferred_time_slot}`,
          },
          { label: "Location", value: `${item.locality}, ${item.city}` },
        ]}
      />
    </DashboardPanel>
  );
}
