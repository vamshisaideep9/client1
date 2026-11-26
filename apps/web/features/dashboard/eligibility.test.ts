import { describe, expect, it } from "vitest";

import { DEFAULT_AGENT_LEAD_FILTERS, agentLeadScope, filterAgentLeads } from "@/features/agent/agent-lead-filters";
import type { AgentLead } from "@/lib/agent-api";

import {
  ATTEMPT_ELIGIBILITY_OPTIONS,
  ELIGIBILITY_LABEL,
  ELIGIBILITY_TONE,
  ROW_ELIGIBILITY_OPTIONS,
  eligibilityBreakdown,
  matchesAttemptOutcome,
  matchesEligibility,
  notEligibleHint,
  rowEligibility,
  type EligibilitySummary,
} from "./eligibility";

function lead(overrides: Partial<AgentLead> = {}): AgentLead {
  return {
    id: "lead-1",
    lead_ref: "LD-00000001",
    name: "Asha Verma",
    mobile: "+919812345678",
    business_line: "loans",
    status: "assigned",
    registered: false,
    editable: true,
    resubmittable: false,
    resubmit_count: 0,
    last_resubmitted_at: null,
    expires_at: null,
    expired_at: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    eligibility: "eligible",
    eligibility_reason: null,
    eligibility_reason_label: null,
    facets: { loans: [], deals: [] },
    ...overrides,
  };
}

const LOAN = {
  loan_type_id: "home",
  loan_type_label: "Home loan",
  bank_id: "hdfc",
  bank_name: "HDFC Bank",
  status: "sanctioned",
} as const;

describe("eligibility vocabulary (CS-024)", () => {
  it("names the three outcomes once and gives each list its own filter options", () => {
    expect(ELIGIBILITY_LABEL).toEqual({ eligible: "Eligible", not_eligible: "Not eligible", duplicate: "Duplicate" });
    expect(ELIGIBILITY_TONE).toEqual({ eligible: "success", not_eligible: "danger", duplicate: "warning" });
    expect(ROW_ELIGIBILITY_OPTIONS.map((option) => option.value)).toEqual(["eligible", "not_eligible"]);
    expect(ATTEMPT_ELIGIBILITY_OPTIONS.map((option) => option.value)).toEqual(["duplicate", "not_eligible"]);
  });

  it("reads a row's eligibility and never invents one for an older row", () => {
    expect(rowEligibility({ eligibility: "not_eligible" })).toBe("not_eligible");
    expect(rowEligibility({ eligibility: "eligible" })).toBe("eligible");
    expect(rowEligibility({})).toBeNull();
    expect(rowEligibility({ eligibility: "duplicate" })).toBeNull();
  });

  it("filters rows and attempts, with All keeping everything", () => {
    expect(matchesEligibility({ eligibility: "eligible" }, "all")).toBe(true);
    expect(matchesEligibility({}, "all")).toBe(true);
    expect(matchesEligibility({ eligibility: "eligible" }, "not_eligible")).toBe(false);
    expect(matchesEligibility({}, "eligible")).toBe(false);
    expect(matchesAttemptOutcome({ outcome: "duplicate" }, "duplicate")).toBe(true);
    expect(matchesAttemptOutcome({ outcome: "not_eligible" }, "duplicate")).toBe(false);
    expect(matchesAttemptOutcome({ outcome: "not_eligible" }, "all")).toBe(true);
  });

  it("splits Not eligible into accepted rows and turned-away attempts", () => {
    const summary: EligibilitySummary = { eligible: 4, not_eligible: 3, duplicate: 2, not_accepted: 3 };
    expect(eligibilityBreakdown(summary)).toEqual({ notEligibleAccepted: 2, notEligibleAttempts: 1 });
    expect(notEligibleHint(summary, { one: "lead", many: "leads" })).toBe("2 leads · 1 not accepted");
    expect(
      notEligibleHint({ eligible: 1, not_eligible: 1, duplicate: 0, not_accepted: 0 }, { one: "lead", many: "leads" }),
    ).toBe("1 lead");
    expect(
      notEligibleHint({ eligible: 1, not_eligible: 0, duplicate: 5, not_accepted: 5 }, { one: "lead", many: "leads" }),
    ).toBe("None");
  });
});

describe("agent lead filters (CS-024)", () => {
  const rows = [
    lead({ id: "a", name: "Asha Verma", status: "assigned", facets: { loans: [LOAN], deals: [] } }),
    lead({
      id: "b",
      name: "Bala Iyer",
      mobile: "+919800000001",
      status: "expired",
      eligibility: "not_eligible",
      eligibility_reason: "attribution_expired",
      eligibility_reason_label: "Your 30-day window ended",
    }),
    lead({ id: "c", name: "Chitra Rao", mobile: "+919800000002", status: "new" }),
  ];
  const scope = agentLeadScope(rows);
  const ids = (filters: Partial<typeof DEFAULT_AGENT_LEAD_FILTERS>) =>
    filterAgentLeads(rows, { ...DEFAULT_AGENT_LEAD_FILTERS, ...filters }, scope).map((row) => row.id);

  it("takes the line from the rows (Agents are line-scoped)", () => {
    expect(scope).toMatchObject({ loans: true, property: false, transactions: false });
    expect(agentLeadScope([])).toMatchObject({ loans: false, property: false });
    expect(agentLeadScope([lead({ business_line: "real_estate" })])).toMatchObject({ loans: false, property: true });
  });

  it("filters by eligibility, status and name or mobile", () => {
    expect(ids({})).toEqual(["a", "b", "c"]);
    expect(ids({ eligibility: "not_eligible" })).toEqual(["b"]);
    expect(ids({ eligibility: "eligible" })).toEqual(["a", "c"]);
    expect(ids({ status: "new" })).toEqual(["c"]);
    expect(ids({ search: "bala" })).toEqual(["b"]);
    expect(ids({ search: "00000002" })).toEqual(["c"]);
    expect(ids({ search: "98123 45678" })).toEqual(["a"]);
  });

  it("matches an exact lead reference in tolerant forms", () => {
    const referenced = [
      lead({ id: "x", lead_ref: "LD-00000042", mobile: "+919811111111" }),
      lead({ id: "y", lead_ref: "LD-00000420", mobile: "+919822222222" }),
    ];
    const found = (search: string) =>
      filterAgentLeads(referenced, { ...DEFAULT_AGENT_LEAD_FILTERS, search }, agentLeadScope(referenced)).map(
        (row) => row.id,
      );
    expect(found("LD-00000042")).toEqual(["x"]);
    expect(found("ld-42")).toEqual(["x"]);
    expect(found("42")).toEqual(["x"]);
    expect(found("LD-420")).toEqual(["y"]);
    expect(found("LD-4")).toEqual([]);
  });

  it("matches product, bank and loan status on one application", () => {
    expect(ids({ loanTypeId: "home" })).toEqual(["a"]);
    expect(ids({ loanTypeId: "home", bankId: "hdfc", loanStatus: "sanctioned" })).toEqual(["a"]);
    expect(ids({ loanTypeId: "home", loanStatus: "disbursed" })).toEqual([]);
  });

  it("ignores filters of the other line", () => {
    expect(ids({ propertyCategory: "villas" })).toEqual(["a", "b", "c"]);
  });
});
