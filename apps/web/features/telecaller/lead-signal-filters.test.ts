import { describe, expect, it } from "vitest";

import type { EmployeeTask } from "@/lib/employee-api";
import { filterTasksByLeadSignals } from "@/features/employee/employee-task-filters";

import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  REFERRER_SOURCE_LABEL,
  formatReferrer,
  leadSignalActiveCount,
  leadSignalChips,
  leadSignalFiltersActive,
  matchesLeadSignals,
  type LeadSignalFilters,
  type LeadSignalValues,
} from "./lead-signal-filters";

const agentLead: LeadSignalValues = {
  loanStatuses: ["contacted", "sanctioned"],
  lastDisposition: "connected",
  lastInterestLevel: "hot",
  referrer: { kind: "agent", reference_id: "AG-1234ABCD" },
};
const clientLead: LeadSignalValues = {
  loanStatuses: [],
  lastDisposition: "busy",
  lastInterestLevel: null,
  referrer: { kind: "client", reference_id: "7K2M9QXA" },
};
const directLead: LeadSignalValues = { loanStatuses: [], lastDisposition: null, lastInterestLevel: null, referrer: null };

function only(patch: Partial<LeadSignalFilters>): LeadSignalFilters {
  return { ...DEFAULT_LEAD_SIGNAL_FILTERS, ...patch };
}

describe("matchesLeadSignals", () => {
  it("passes everything with the default filters", () => {
    for (const lead of [agentLead, clientLead, directLead]) {
      expect(matchesLeadSignals(lead, DEFAULT_LEAD_SIGNAL_FILTERS)).toBe(true);
    }
    expect(leadSignalFiltersActive(DEFAULT_LEAD_SIGNAL_FILTERS)).toBe(false);
  });

  it("matches a loan status held by any of the lead's applications", () => {
    expect(matchesLeadSignals(agentLead, only({ loanStatus: "sanctioned" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ loanStatus: "disbursed" }))).toBe(false);
    expect(matchesLeadSignals(directLead, only({ loanStatus: "new" }))).toBe(false);
  });

  it("filters by the latest call status, including never-called leads", () => {
    expect(matchesLeadSignals(clientLead, only({ callStatus: "busy" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ callStatus: "busy" }))).toBe(false);
    expect(matchesLeadSignals(directLead, only({ callStatus: "not_called" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ callStatus: "not_called" }))).toBe(false);
  });

  it("filters by interest level", () => {
    expect(matchesLeadSignals(agentLead, only({ interest: "hot" }))).toBe(true);
    expect(matchesLeadSignals(clientLead, only({ interest: "hot" }))).toBe(false);
  });

  it("filters by referral source, treating no referrer as direct", () => {
    expect(matchesLeadSignals(agentLead, only({ source: "agent" }))).toBe(true);
    expect(matchesLeadSignals(clientLead, only({ source: "agent" }))).toBe(false);
    expect(matchesLeadSignals(clientLead, only({ source: "client" }))).toBe(true);
    expect(matchesLeadSignals(directLead, only({ source: "direct" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ source: "direct" }))).toBe(false);
  });

  it("matches the referred-by ID case-insensitively by substring, ignoring spaces", () => {
    expect(matchesLeadSignals(clientLead, only({ referredBy: " 7k2m " }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ referredBy: "ag-1234" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ referredBy: "7K2M" }))).toBe(false);
    expect(matchesLeadSignals(directLead, only({ referredBy: "AG" }))).toBe(false);
    expect(leadSignalFiltersActive(only({ referredBy: "AG" }))).toBe(true);
  });

  it("combines filters with AND", () => {
    expect(matchesLeadSignals(agentLead, only({ source: "agent", interest: "hot", callStatus: "connected" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ source: "agent", interest: "cold" }))).toBe(false);
  });
});

describe("formatReferrer", () => {
  it("labels the referrer kind with its ID", () => {
    expect(formatReferrer(agentLead.referrer)).toBe("Agent · AG-1234ABCD");
    expect(formatReferrer(clientLead.referrer)).toBe("Client · 7K2M9QXA");
    expect(formatReferrer(null)).toBeNull();
    expect(formatReferrer(undefined)).toBeNull();
  });
});

describe("filterTasksByLeadSignals", () => {
  function task(id: string, patch: Partial<EmployeeTask>): EmployeeTask {
    return {
      id,
      lead_uuid: `lead-${id}`,
      lead_contact_mode: "allow",
      business_line: "loans",
      task_type: "document_collection",
      status: "assigned",
      outcome: null,
      notes: null,
      due_at: null,
      created_at: "2026-11-15T00:00:00Z",
      updated_at: "2026-11-15T00:00:00Z",
      ...patch,
    };
  }

  it("applies the same rules to the employee's task lead fields", () => {
    const tasks = [
      task("1", { lead_referrer: { kind: "client", reference_id: "7K2M9QXA" }, lead_last_disposition: "busy" }),
      task("2", { lead_loan_statuses: ["sanctioned"], lead_last_disposition: "connected", lead_last_interest_level: "warm" }),
      task("3", {}),
    ];

    expect(filterTasksByLeadSignals(tasks, only({ source: "client" })).map((t) => t.id)).toEqual(["1"]);
    expect(filterTasksByLeadSignals(tasks, only({ loanStatus: "sanctioned", interest: "warm" })).map((t) => t.id)).toEqual(["2"]);
    expect(filterTasksByLeadSignals(tasks, only({ callStatus: "not_called" })).map((t) => t.id)).toEqual(["3"]);
  });
});

describe("lead signal naming, counts and chips", () => {
  it("offers the three lead sources by their agreed names", () => {
    expect(Object.values(REFERRER_SOURCE_LABEL)).toEqual(["Direct lead", "Referred by agent", "Referred by client"]);
  });

  it("counts active filters, ignoring loan status where it does not apply", () => {
    const filters = only({ loanStatus: "sanctioned", interest: "hot", referredBy: "  " });
    expect(leadSignalActiveCount(filters)).toBe(2);
    expect(leadSignalActiveCount(filters, false)).toBe(1);
    expect(leadSignalActiveCount(DEFAULT_LEAD_SIGNAL_FILTERS)).toBe(0);
  });

  it("chips name the field and clear only their own filter", () => {
    const patches: Partial<LeadSignalFilters>[] = [];
    const chips = leadSignalChips(
      only({ callStatus: "not_called", source: "direct", referredBy: "AG-1" }),
      (patch) => patches.push(patch),
    );
    expect(chips.map((chip) => chip.label)).toEqual([
      "Call status: Not called yet",
      "Lead source: Direct lead",
      "Referred by ID: AG-1",
    ]);
    chips[1].onRemove();
    expect(patches).toEqual([{ source: "all" }]);
  });
});
