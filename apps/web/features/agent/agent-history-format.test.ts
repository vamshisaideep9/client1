import { describe, expect, it } from "vitest";

import type { AgentLeadHistory } from "@/lib/agent-api";

import {
  formatDealAmount,
  formatWhen,
  hiddenFieldsNote,
  historyRequests,
  timelineLabel,
} from "./agent-history-format";

const history: AgentLeadHistory = {
  lead_id: "lead-1",
  status: "converted",
  created_at: "2026-09-01T00:00:00Z",
  applications: [
    {
      id: "app-1",
      product_label: "Home Loan",
      bank_name: "HDFC Bank",
      status: "disbursed",
      amount_requested: "3000000.00",
      amount_sanctioned: "2500000.00",
      opened_at: "2026-09-02T00:00:00Z",
      closed_at: null,
      disbursed_at: "2026-09-20T00:00:00Z",
    },
  ],
  service_enquiries: [],
  deals: [
    {
      id: "deal-1",
      property_title: "Lakeview 3BHK",
      property_category: "apartments",
      status: "booked",
      price_quoted: null,
      booking_amount: null,
      opened_at: "2026-09-10T00:00:00Z",
      closed_at: null,
    },
  ],
  enquiries: [],
  site_visits: [
    {
      id: "visit-1",
      title: "Lakeview 3BHK",
      locality: "Hidden Locality",
      city: "City",
      preferred_date: "2026-10-02",
      preferred_time_slot: "morning",
      status: "done",
      created_at: "2026-09-05T00:00:00Z",
    },
  ],
  calls: [],
  timeline: [],
  hidden_fields: [],
};

describe("historyRequests", () => {
  it("lists every request newest first with a plain detail line", () => {
    const items = historyRequests(history);
    expect(items.map((item) => item.key)).toEqual([
      "property_deal:deal-1",
      "site_visit:visit-1",
      "loan_application:app-1",
    ]);
    expect(items[2].detail).toBe(
      `HDFC Bank · Sanctioned ₹25,00,000 · Disbursed ${formatWhen("2026-09-20T00:00:00Z")}`,
    );
    expect(items[0].detail).toBe("Apartments");
    expect(items[1].detail).toBe(`Visit ${formatWhen("2026-10-02T06:30:00Z")} · Morning`);
  });
});

describe("timelineLabel", () => {
  const at = "2026-09-01T00:00:00Z";
  it("describes each event", () => {
    expect(
      timelineLabel({ event: "introduced", at, request_id: null, from_status: null, to_status: null }),
    ).toBe("You introduced this lead");
    expect(
      timelineLabel({
        event: "loan_application_updated",
        at,
        request_id: "app-1",
        from_status: "sanctioned",
        to_status: "disbursed",
      }),
    ).toBe("Loan application: Sanctioned → Disbursed");
    expect(
      timelineLabel({
        event: "team_lead_status_updated",
        at,
        request_id: null,
        from_status: "working",
        to_status: "converted",
      }),
    ).toBe("Marked converted by a team manager");
  });
});

describe("formatting", () => {
  it("formats amounts, dates and the hidden-fields note", () => {
    expect(formatDealAmount("2500000.00")).toBe("₹25,00,000");
    expect(formatDealAmount(null)).toBe("—");
    expect(formatWhen(null)).toBe("—");
    // 18:30 UTC is already the next day in IST.
    expect(formatWhen("2026-09-30T18:30:00Z")).toBe(formatWhen("2026-10-01T06:00:00Z"));
    expect(hiddenFieldsNote([])).toBe("");
    expect(hiddenFieldsNote(["call_notes"])).toBe("Your Admin hides call notes.");
    expect(hiddenFieldsNote(["call_notes", "staff_names", "deal_amount"])).toBe(
      "Your Admin hides call notes, telecaller names and loan and deal amounts.",
    );
  });
});
