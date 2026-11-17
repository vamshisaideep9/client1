import { describe, expect, it } from "vitest";

import type { TelecallerLead } from "@/lib/telecaller-api";

import {
  DEFAULT_TELECALLER_LEAD_FILTERS,
  DEFAULT_TELECALLER_LEAD_SORT,
  filterTelecallerLeads,
  isFollowUpDue,
  sortTelecallerLeads,
  telecallerLeadFiltersActive,
} from "./telecaller-lead-filters";

function lead(overrides: Partial<TelecallerLead>): TelecallerLead {
  return {
    id: overrides.id ?? "lead-1",
    business_line: "loans",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    mobile: "9876543210",
    name: "Asha Rao",
    status: "assigned",
    last_disposition: null,
    next_follow_up_at: null,
    requirement: null,
    ...overrides,
  };
}

describe("filterTelecallerLeads", () => {
  const leads: TelecallerLead[] = [
    lead({ id: "1", name: "Asha Rao", mobile: "9876543210", status: "working" }),
    lead({ id: "2", name: "Vikram Shah", mobile: "8123456789", status: "converted" }),
    lead({ id: "3", name: null, mobile: "7000011111", status: "new" }),
  ];

  it("matches search against name and mobile", () => {
    expect(filterTelecallerLeads(leads, { ...DEFAULT_TELECALLER_LEAD_FILTERS, search: "asha", status: "all" })).toEqual([leads[0]]);
    expect(filterTelecallerLeads(leads, { ...DEFAULT_TELECALLER_LEAD_FILTERS, search: "7000011111", status: "all" })).toEqual([leads[2]]);
  });

  it("filters by status", () => {
    expect(filterTelecallerLeads(leads, { ...DEFAULT_TELECALLER_LEAD_FILTERS, search: "", status: "converted" })).toEqual([leads[1]]);
  });

  it("filters by follow-up date range", () => {
    const withFollowUp = [
      lead({ id: "a", next_follow_up_at: "2026-02-01T09:00:00Z" }),
      lead({ id: "b", next_follow_up_at: "2026-03-15T09:00:00Z" }),
      lead({ id: "c", next_follow_up_at: null }),
    ];
    expect(
      filterTelecallerLeads(withFollowUp, {
        ...DEFAULT_TELECALLER_LEAD_FILTERS,
        search: "",
        status: "all",
        followUpFrom: "2026-02-01",
        followUpTo: "2026-02-28",
      }),
    ).toEqual([withFollowUp[0]]);
  });

  it("combines search and status filters", () => {
    expect(
      filterTelecallerLeads(leads, { ...DEFAULT_TELECALLER_LEAD_FILTERS, search: "shah", status: "converted" }),
    ).toEqual([leads[1]]);
    expect(
      filterTelecallerLeads(leads, { ...DEFAULT_TELECALLER_LEAD_FILTERS, search: "shah", status: "working" }),
    ).toEqual([]);
  });
});

describe("sortTelecallerLeads", () => {
  it("sorts by soonest follow-up first, with never-called leads last regardless of direction", () => {
    const leads: TelecallerLead[] = [
      lead({ id: "later", next_follow_up_at: "2026-03-15T09:00:00Z" }),
      lead({ id: "never", next_follow_up_at: null }),
      lead({ id: "soonest", next_follow_up_at: "2026-02-01T09:00:00Z" }),
    ];

    expect(sortTelecallerLeads(leads, { key: "next_follow_up_at", dir: "asc" }).map((l) => l.id)).toEqual([
      "soonest",
      "later",
      "never",
    ]);
    expect(sortTelecallerLeads(leads, { key: "next_follow_up_at", dir: "desc" }).map((l) => l.id)).toEqual([
      "later",
      "soonest",
      "never",
    ]);
  });

  it("sorts by name alphabetically", () => {
    const leads: TelecallerLead[] = [
      lead({ id: "1", name: "Zara" }),
      lead({ id: "2", name: "Asha" }),
    ];
    expect(sortTelecallerLeads(leads, { key: "name", dir: "asc" }).map((l) => l.id)).toEqual(["2", "1"]);
    expect(sortTelecallerLeads(leads, { key: "name", dir: "desc" }).map((l) => l.id)).toEqual(["1", "2"]);
  });

  it("does not mutate the input array", () => {
    const leads: TelecallerLead[] = [lead({ id: "1", name: "Zara" }), lead({ id: "2", name: "Asha" })];
    const original = [...leads];
    sortTelecallerLeads(leads, { key: "name", dir: "asc" });
    expect(leads).toEqual(original);
  });

  it("lands on open work first, then the soonest follow-up, so closed leads leave page 1", () => {
    const leads: TelecallerLead[] = [
      lead({ id: "closed-soon", status: "closed", next_follow_up_at: "2026-01-01T09:00:00Z" }),
      lead({ id: "released", status: "released" }),
      lead({ id: "working-late", status: "working", next_follow_up_at: "2026-03-01T09:00:00Z" }),
      lead({ id: "assigned", status: "assigned" }),
      lead({ id: "working-soon", status: "working", next_follow_up_at: "2026-02-01T09:00:00Z" }),
      lead({ id: "converted", status: "converted" }),
      lead({ id: "new", status: "new" }),
    ];
    expect(DEFAULT_TELECALLER_LEAD_SORT.key).toBe("default");
    expect(sortTelecallerLeads(leads, DEFAULT_TELECALLER_LEAD_SORT).map((l) => l.id)).toEqual([
      "new",
      "assigned",
      "working-soon",
      "working-late",
      "converted",
      "closed-soon",
      "released",
    ]);
  });

  it("keeps only open leads whose follow-up is due now or overdue for ?followUp=due", () => {
    const now = new Date("2026-11-16T10:00:00Z");
    const leads: TelecallerLead[] = [
      lead({ id: "overdue", status: "working", next_follow_up_at: "2026-11-15T09:00:00Z" }),
      lead({ id: "now", status: "assigned", next_follow_up_at: "2026-11-16T10:00:00Z" }),
      lead({ id: "later", status: "working", next_follow_up_at: "2026-11-17T09:00:00Z" }),
      lead({ id: "none", status: "working", next_follow_up_at: null }),
      lead({ id: "closed", status: "closed", next_follow_up_at: "2026-11-10T09:00:00Z" }),
    ];
    const filters = { ...DEFAULT_TELECALLER_LEAD_FILTERS, followUpDue: true };
    expect(filterTelecallerLeads(leads, filters, now).map((l) => l.id)).toEqual(["overdue", "now"]);
    expect(telecallerLeadFiltersActive(filters)).toBe(true);
    expect(isFollowUpDue(leads[2], now)).toBe(false);
  });

  it("sorts the Status column by the same rank, not alphabetically", () => {
    const leads: TelecallerLead[] = [
      lead({ id: "closed", status: "closed" }),
      lead({ id: "new", status: "new" }),
      lead({ id: "working", status: "working" }),
    ];
    expect(sortTelecallerLeads(leads, { key: "status", dir: "asc" }).map((l) => l.id)).toEqual([
      "new",
      "working",
      "closed",
    ]);
    expect(sortTelecallerLeads(leads, { key: "status", dir: "desc" }).map((l) => l.id)).toEqual([
      "closed",
      "working",
      "new",
    ]);
  });
});
