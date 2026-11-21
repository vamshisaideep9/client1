// Formatting and labels for the Agent's commission, transaction and lead
// history views (CS-022). Pure and unit-tested.
import type { AgentLeadHistory } from "@/lib/agent-api";

import { humanizeStatus } from "./agent-earnings-filters";

const WHEN = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});

/** "5 Oct 2026" (IST), or "—" when there is no date. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : WHEN.format(date);
}

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** A deal amount the API sends as a decimal string in rupees ("2500000.00"). */
export function formatDealAmount(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? RUPEES.format(amount) : "—";
}

export type HistoryRequestKind =
  | "loan_application"
  | "service_enquiry"
  | "property_deal"
  | "property_enquiry"
  | "site_visit";

export const HISTORY_KIND_LABEL: Record<HistoryRequestKind, string> = {
  loan_application: "Loan application",
  service_enquiry: "Card / insurance request",
  property_deal: "Property deal",
  property_enquiry: "Property enquiry",
  site_visit: "Site visit",
};

export type HistoryRequest = {
  key: string;
  kind: HistoryRequestKind;
  title: string;
  detail: string | null;
  status: string;
  at: string;
};

/** Every application, request, deal, enquiry and visit on the lead, newest first. */
export function historyRequests(history: AgentLeadHistory): HistoryRequest[] {
  const items: HistoryRequest[] = [
    ...history.applications.map((a) => ({
      key: `loan_application:${a.id}`,
      kind: "loan_application" as const,
      title: a.product_label ?? "Loan",
      detail:
        [
          a.bank_name,
          a.amount_sanctioned
            ? `Sanctioned ${formatDealAmount(a.amount_sanctioned)}`
            : a.amount_requested
              ? `Requested ${formatDealAmount(a.amount_requested)}`
              : null,
          a.disbursed_at ? `Disbursed ${formatWhen(a.disbursed_at)}` : null,
        ]
          .filter(Boolean)
          .join(" · ") || null,
      status: a.status,
      at: a.opened_at,
    })),
    ...history.service_enquiries.map((s) => ({
      key: `service_enquiry:${s.id}`,
      kind: "service_enquiry" as const,
      title: s.product_label ?? "Request",
      detail: s.product_category ? humanizeStatus(s.product_category) : null,
      status: s.status,
      at: s.submitted_at,
    })),
    ...history.deals.map((d) => ({
      key: `property_deal:${d.id}`,
      kind: "property_deal" as const,
      title: d.property_title ?? "Property",
      detail:
        [
          d.property_category ? humanizeStatus(d.property_category) : null,
          d.price_quoted ? `Quoted ${formatDealAmount(d.price_quoted)}` : null,
          d.booking_amount ? `Booked ${formatDealAmount(d.booking_amount)}` : null,
        ]
          .filter(Boolean)
          .join(" · ") || null,
      status: d.status,
      at: d.opened_at,
    })),
    ...history.enquiries.map((q) => ({
      key: `property_enquiry:${q.id}`,
      kind: "property_enquiry" as const,
      title: q.title,
      detail: [q.locality, q.city].filter(Boolean).join(", ") || null,
      status: q.status,
      at: q.created_at,
    })),
    ...history.site_visits.map((v) => ({
      key: `site_visit:${v.id}`,
      kind: "site_visit" as const,
      title: v.title,
      detail: `Visit ${formatWhen(`${v.preferred_date}T06:30:00Z`)} · ${humanizeStatus(v.preferred_time_slot)}`,
      status: v.status,
      at: v.created_at,
    })),
  ];
  return items.sort((a, b) => b.at.localeCompare(a.at));
}

type HistoryEvent = AgentLeadHistory["timeline"][number];

/** One plain-language line per timeline event. */
export function timelineLabel(event: HistoryEvent): string {
  const to = event.to_status ? humanizeStatus(event.to_status) : null;
  const from = event.from_status ? humanizeStatus(event.from_status) : null;
  switch (event.event) {
    case "introduced":
      return "You introduced this lead";
    case "lead_assigned":
      return "Assigned to a telecaller";
    case "agent_lead_expired":
      return "Your 30-day window ended and the lead returned to the pool";
    case "agent_lead_resubmitted":
      return "You resubmitted the lead";
    case "team_lead_status_updated":
      return to ? `Marked ${to.toLowerCase()} by a team manager` : "Status changed by a team manager";
    case "team_lead_reassigned":
      return "Moved to another telecaller";
    case "loan_application_updated":
      return from && to ? `Loan application: ${from} → ${to}` : `Loan application ${to ?? "updated"}`;
    case "property_deal_updated":
      return from && to ? `Property deal: ${from} → ${to}` : `Property deal ${to ?? "updated"}`;
    default:
      return humanizeStatus(event.event);
  }
}

const HIDDEN_LABEL: Record<string, string> = {
  call_notes: "call notes",
  staff_names: "telecaller names",
  deal_amount: "loan and deal amounts",
  client_name: "client names",
};

/** "Your Admin hides call notes and telecaller names." or "". */
export function hiddenFieldsNote(hidden: readonly string[]): string {
  const labels = hidden.map((key) => HIDDEN_LABEL[key]).filter(Boolean);
  if (labels.length === 0) return "";
  const list =
    labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
  return `Your Admin hides ${list}.`;
}
