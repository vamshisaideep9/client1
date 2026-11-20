import { describe, expect, it } from "vitest";

import type { LeadActivity, TelecallerLeadDetail } from "@/lib/telecaller-api";

import {
  buildWorkspaceRequests,
  defaultRequestKey,
  filterCalls,
  parseRequestKey,
  requestKey,
} from "./telecaller-requests";

const base = {
  id: "lead-1",
  mobile: "+919876543210",
  business_line: "loans",
  status: "working",
  created_at: "2026-10-01T09:00:00Z",
  updated_at: "2026-11-13T09:00:00Z",
  activities: [],
  tasks: [],
} as unknown as TelecallerLeadDetail;

function loanApp(id: string, status: string, openedAt: string) {
  return {
    id,
    loan_type_id: "lt",
    loan_type_name: "Home Loan",
    bank_name: "HDFC Bank",
    status,
    opened_at: openedAt,
    txns: [],
  };
}

describe("telecaller request workspace", () => {
  const lead = {
    ...base,
    loan_applications: [
      loanApp("old", "disbursed", "2026-03-01T10:00:00Z"),
      loanApp("new", "submitted_to_bank", "2026-11-10T10:00:00Z"),
    ],
    financial_enquiries: [
      {
        id: "card",
        product_name: "Platinum Card",
        product_category: "credit_card",
        status: "submitted",
        submitted_at: "2026-11-12T08:30:00Z",
      },
    ],
  } as unknown as TelecallerLeadDetail;

  it("lists every request newest first and marks finished ones", () => {
    const requests = buildWorkspaceRequests(lead);
    expect(requests.map((r) => r.key)).toEqual([
      "financial_enquiry:card",
      "loan_application:new",
      "loan_application:old",
    ]);
    expect(requests.find((r) => r.id === "old")?.finished).toBe(true);
    expect(requests.find((r) => r.id === "new")?.finished).toBe(false);
    expect(requests[0].detail).toBe("Credit card");
  });

  it("opens the newest request still in progress first", () => {
    expect(defaultRequestKey(buildWorkspaceRequests(lead))).toBe("financial_enquiry:card");
    const onlyFinished = {
      ...base,
      loan_applications: [loanApp("done", "closed", "2026-03-01T10:00:00Z")],
    } as unknown as TelecallerLeadDetail;
    expect(defaultRequestKey(buildWorkspaceRequests(onlyFinished))).toBe("loan_application:done");
    expect(defaultRequestKey(buildWorkspaceRequests(base))).toBeNull();
  });

  it("separates calls by request and keeps general calls apart", () => {
    const calls = [
      { id: "1", request: { kind: "loan_application", id: "new" } },
      { id: "2", request: null },
      { id: "3", request: { kind: "loan_application", id: "old" } },
    ] as unknown as LeadActivity[];
    expect(filterCalls(calls, "all").map((c) => c.id)).toEqual(["1", "2", "3"]);
    expect(filterCalls(calls, "general").map((c) => c.id)).toEqual(["2"]);
    expect(filterCalls(calls, "loan_application:old").map((c) => c.id)).toEqual(["3"]);
  });

  it("round-trips request keys and rejects unknown kinds", () => {
    expect(parseRequestKey(requestKey({ kind: "site_visit", id: "v1" }))).toEqual({
      kind: "site_visit",
      id: "v1",
    });
    expect(parseRequestKey("general")).toBeNull();
    expect(parseRequestKey("bogus:1")).toBeNull();
  });
});
