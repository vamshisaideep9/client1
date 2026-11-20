import type {
  LeadActivity,
  LeadRequestSummary,
  RequestKind,
  RequestRef,
  TelecallerLeadDetail,
} from "@/lib/telecaller-api";

// Everything a client asked for on one lead (loan applications, card/insurance
// requests, property enquiries, site visits, property deals), so a Telecaller
// can work each one separately and file calls against it.

export const REQUEST_KIND_LABEL: Record<RequestKind, string> = {
  loan_application: "Loan application",
  financial_enquiry: "Card / insurance request",
  property_enquiry: "Property enquiry",
  site_visit: "Site visit",
  property_deal: "Property deal",
};

const FINISHED_STATUSES: Record<RequestKind, ReadonlySet<string>> = {
  loan_application: new Set(["disbursed", "closed", "rejected"]),
  financial_enquiry: new Set(),
  property_enquiry: new Set(["closed"]),
  site_visit: new Set(["done", "cancelled"]),
  property_deal: new Set(["closed", "rejected"]),
};

export type WorkspaceRequest = LeadRequestSummary & {
  key: string;
  finished: boolean;
  detail: string | null;
};

export function requestKey(ref: Pick<RequestRef, "kind" | "id">): string {
  return `${ref.kind}:${ref.id}`;
}

export function parseRequestKey(key: string): RequestRef | null {
  const [kind, id] = key.split(":");
  if (!id || !(kind in REQUEST_KIND_LABEL)) return null;
  return { kind: kind as RequestKind, id };
}

function toTitleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function statusLabel(status: string): string {
  return toTitleCase(status);
}

/** Every request on the lead, newest first, with whether it is finished. */
export function buildWorkspaceRequests(lead: TelecallerLeadDetail): WorkspaceRequest[] {
  const items: WorkspaceRequest[] = [];
  const push = (
    kind: RequestKind,
    id: string,
    title: string,
    status: string,
    appliedAt: string,
    detail: string | null,
  ) =>
    items.push({
      kind,
      id,
      title,
      status,
      applied_at: appliedAt,
      key: requestKey({ kind, id }),
      finished: FINISHED_STATUSES[kind].has(status),
      detail,
    });

  for (const app of lead.loan_applications ?? []) {
    push("loan_application", app.id, app.loan_type_name, app.status, app.opened_at, app.bank_name ?? null);
  }
  for (const enquiry of lead.financial_enquiries ?? []) {
    push(
      "financial_enquiry",
      enquiry.id,
      enquiry.product_name,
      enquiry.status,
      enquiry.submitted_at,
      toTitleCase(enquiry.product_category),
    );
  }
  for (const enquiry of lead.property_enquiries ?? []) {
    push(
      "property_enquiry",
      enquiry.id,
      enquiry.title,
      enquiry.status,
      enquiry.created_at,
      `${enquiry.locality}, ${enquiry.city}`,
    );
  }
  for (const visit of lead.site_visits ?? []) {
    push("site_visit", visit.id, visit.title, visit.status, visit.created_at, `${visit.locality}, ${visit.city}`);
  }
  for (const deal of lead.property_deals ?? []) {
    push("property_deal", deal.id, deal.property_title, deal.status, deal.opened_at, deal.property_location);
  }

  return items.sort((a, b) => Date.parse(b.applied_at) - Date.parse(a.applied_at));
}

/** The request to open first: the newest one still in progress, else the newest. */
export function defaultRequestKey(requests: WorkspaceRequest[]): string | null {
  return (requests.find((request) => !request.finished) ?? requests[0])?.key ?? null;
}

export type CallFilter = "all" | "general" | string;

export function filterCalls(activities: LeadActivity[], filter: CallFilter): LeadActivity[] {
  if (filter === "all") return activities;
  if (filter === "general") return activities.filter((activity) => !activity.request);
  return activities.filter(
    (activity) => activity.request && requestKey(activity.request) === filter,
  );
}

export function callCount(activities: LeadActivity[], filter: CallFilter): number {
  return filterCalls(activities, filter).length;
}

const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** "13 Nov 2026, 10:42 am" in the viewer's timezone. */
export function formatAppliedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : DATE_TIME.format(date);
}
