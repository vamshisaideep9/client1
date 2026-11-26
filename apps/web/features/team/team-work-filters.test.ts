import { describe, expect, it } from "vitest";

import type { TeamLeadRow, TeamTaskRow } from "@/lib/staff-teams-api";

import {
  DEFAULT_TEAM_WORK_FILTERS,
  filterTeamLeads,
  filterTeamTasks,
  teamWorkFiltersActive,
} from "./team-work-filters";

const NOW = new Date("2026-11-15T10:00:00Z");
const ASHA = "30000000-0000-4000-8000-000000000001";
const BALA = "30000000-0000-4000-8000-000000000002";

function lead(overrides: Partial<TeamLeadRow>): TeamLeadRow {
  return {
    id: crypto.randomUUID(),
    lead_ref: "LD-00000001",
    name: "Kiran Kumar",
    mobile: "+919800000001",
    status: "working",
    business_line: "loans",
    created_at: NOW.toISOString(),
    updated_at: NOW.toISOString(),
    requests: [],
    last_call: null,
    assigned_to: { staff_profile_uuid: ASHA, first_name: "Asha", last_name: "Rao" },
    signals: { loan_statuses: [], last_disposition: null, last_interest_level: null, referrer: null },
    hidden_fields: [],
    ...overrides,
  };
}

function task(overrides: Partial<TeamTaskRow>): TeamTaskRow {
  return {
    id: crypto.randomUUID(),
    lead_uuid: crypto.randomUUID(),
    lead_name: "Field Client",
    lead_mobile: "+919800000002",
    task_type: "document_collection",
    status: "assigned",
    business_line: "loans",
    notes: null,
    due_at: null,
    created_at: NOW.toISOString(),
    updated_at: NOW.toISOString(),
    assigned_to: { staff_profile_uuid: BALA, first_name: "Bala", last_name: "Rao" },
    signals: { loan_statuses: [], last_disposition: null, last_interest_level: null, referrer: null },
    hidden_fields: [],
    ...overrides,
  };
}

describe("team work filters", () => {
  it("starts inactive and passes everything", () => {
    const rows = [lead({}), lead({ status: "closed" })];
    expect(teamWorkFiltersActive(DEFAULT_TEAM_WORK_FILTERS)).toBe(false);
    expect(filterTeamLeads(rows, DEFAULT_TEAM_WORK_FILTERS, NOW)).toHaveLength(2);
  });

  it("filters leads by assignee, status, search and the shared lead signals", () => {
    const hot = lead({
      name: "Priya Shah",
      mobile: "+919811122233",
      signals: {
        loan_statuses: ["under_review"],
        last_disposition: "connected",
        last_interest_level: "hot",
        referrer: { kind: "agent", reference_id: "AG-1042" },
      },
    });
    const bala = lead({ assigned_to: { staff_profile_uuid: BALA, first_name: "Bala", last_name: "Rao" } });
    const notCalled = lead({ name: "Nobody Called" });
    const rows = [hot, bala, notCalled];
    const base = DEFAULT_TEAM_WORK_FILTERS;

    expect(filterTeamLeads(rows, { ...base, assignee: BALA }, NOW)).toEqual([bala]);
    expect(filterTeamLeads(rows, { ...base, search: "priya" }, NOW)).toEqual([hot]);
    expect(filterTeamLeads(rows, { ...base, search: "11122" }, NOW)).toEqual([hot]);
    expect(filterTeamLeads(rows, { ...base, loanStatus: "under_review" }, NOW)).toEqual([hot]);
    expect(filterTeamLeads(rows, { ...base, interest: "hot" }, NOW)).toEqual([hot]);
    expect(filterTeamLeads(rows, { ...base, source: "agent", referredBy: "ag-10" }, NOW)).toEqual([hot]);
    expect(filterTeamLeads(rows, { ...base, callStatus: "not_called" }, NOW)).toEqual([bala, notCalled]);
    expect(filterTeamLeads(rows, { ...base, status: "closed" }, NOW)).toEqual([]);
  });

  it("keeps only open leads past their follow-up when overdue is on", () => {
    const due = lead({
      last_call: { disposition: "callback_requested", interest_level: null, follow_up_at: "2026-11-14T10:00:00Z", created_at: NOW.toISOString() },
    });
    const later = lead({
      last_call: { disposition: "callback_requested", interest_level: null, follow_up_at: "2026-11-16T10:00:00Z", created_at: NOW.toISOString() },
    });
    const closed = lead({ status: "closed", last_call: due.last_call });
    expect(filterTeamLeads([due, later, closed], { ...DEFAULT_TEAM_WORK_FILTERS, overdueOnly: true }, NOW)).toEqual([due]);
  });

  it("filters tasks by type, status, overdue due time and client search", () => {
    const late = task({ due_at: "2026-11-14T09:00:00Z", task_type: "property_visit" });
    const fine = task({ due_at: "2026-11-20T09:00:00Z" });
    const blocked = task({ status: "blocked", lead_name: "Ravi Teja" });
    const rows = [late, fine, blocked];
    const base = DEFAULT_TEAM_WORK_FILTERS;
    expect(filterTeamTasks(rows, { ...base, taskType: "property_visit" }, NOW)).toEqual([late]);
    expect(filterTeamTasks(rows, { ...base, overdueOnly: true }, NOW)).toEqual([late]);
    expect(filterTeamTasks(rows, { ...base, status: "blocked" }, NOW)).toEqual([blocked]);
    expect(filterTeamTasks(rows, { ...base, search: "ravi" }, NOW)).toEqual([blocked]);
  });
});
