import { describe, expect, it } from "vitest";

import {
  compareOptionalTimes,
  leadStatusRank,
  sinkFinishedLoans,
  sortLeadsByDefaultOrder,
} from "./list-order";

describe("default lead order", () => {
  it("ranks New > Assigned > Working > Converted > Closed > Released", () => {
    const order = ["released", "closed", "converted", "working", "assigned", "new"];
    const sorted = [...order].sort((a, b) => leadStatusRank(a) - leadStatusRank(b));
    expect(sorted).toEqual(["new", "assigned", "working", "converted", "closed", "released"]);
  });

  it("puts unknown or missing statuses last", () => {
    expect(leadStatusRank("expired")).toBeGreaterThan(leadStatusRank("released"));
    expect(leadStatusRank("mystery")).toBeGreaterThan(leadStatusRank("expired"));
    expect(leadStatusRank(null)).toBe(leadStatusRank("mystery"));
  });

  it("keeps closed leads off the top and orders ties by the soonest follow-up", () => {
    const rows = [
      { id: "closed", status: "closed", followUp: "2026-01-01T09:00:00Z" },
      { id: "working-late", status: "working", followUp: "2026-03-01T09:00:00Z" },
      { id: "working-none", status: "working", followUp: null },
      { id: "working-soon", status: "working", followUp: "2026-02-01T09:00:00Z" },
      { id: "new", status: "new", followUp: null },
    ];
    expect(
      sortLeadsByDefaultOrder(rows, (row) => row.status, (row) => row.followUp).map((row) => row.id),
    ).toEqual(["new", "working-soon", "working-late", "working-none", "closed"]);
  });

  it("keeps the incoming order inside a status when there is no follow-up and leaves the input alone", () => {
    const rows = [
      { id: "b", status: "assigned" },
      { id: "a", status: "assigned" },
    ];
    expect(sortLeadsByDefaultOrder(rows, (row) => row.status).map((row) => row.id)).toEqual(["b", "a"]);
    expect(rows.map((row) => row.id)).toEqual(["b", "a"]);
  });

  it("sorts missing times after real ones", () => {
    expect(compareOptionalTimes(null, "2026-01-01T00:00:00Z")).toBeGreaterThan(0);
    expect(compareOptionalTimes("2026-01-01T00:00:00Z", undefined)).toBeLessThan(0);
    expect(compareOptionalTimes(null, null)).toBe(0);
  });
});

describe("loan applications", () => {
  it("moves closed and rejected applications below active ones without reordering the rest", () => {
    const rows = [
      { id: "1", status: "rejected" },
      { id: "2", status: "under_review" },
      { id: "3", status: "closed" },
      { id: "4", status: "disbursed" },
      { id: "5", status: "new" },
    ];
    expect(sinkFinishedLoans(rows, (row) => row.status).map((row) => row.id)).toEqual(["2", "4", "5", "1", "3"]);
  });
});
