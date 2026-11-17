import { describe, expect, it } from "vitest";

import type { AgentEarningsRow } from "@/lib/agent-api";

import {
  EMPTY_EARNINGS_FILTERS,
  commissionPaidLabel,
  earningsFilterOptions,
  filterEarningsRows,
  humanizeStatus,
  moreEarningsFilterCount,
  rupeesToPaise,
} from "./agent-earnings-filters";

function row(overrides: Partial<AgentEarningsRow>): AgentEarningsRow {
  return {
    id: "c0000000-0000-0000-0000-000000000001",
    business_line: "loans",
    deal_type: "loan_application",
    deal_uuid: "d0000000-0000-0000-0000-000000000001",
    agreed_amount_paise: 1_000_000,
    status: "pending",
    payout_txn_uuid: null,
    created_at: "2026-10-05T10:00:00Z",
    lead_uuid: "10000000-0000-0000-0000-000000000001",
    lead_status: "converted",
    client_name: "Asha Rao",
    product_uuid: "p-home",
    product_label: "Home Loan",
    bank_uuid: "b-hdfc",
    bank_name: "HDFC Bank",
    property_uuid: null,
    property_title: null,
    property_category: null,
    deal_status: "disbursed",
    deal_amount: "2500000.00",
    paid_at: null,
    ...overrides,
  };
}

const rows = [
  row({ id: "c1", status: "paid", client_name: "Asha Rao", created_at: "2026-09-30T18:29:00Z" }),
  row({
    id: "c2",
    client_name: "Vikram Shah",
    product_uuid: "p-car",
    product_label: "Car Loan",
    bank_uuid: "b-sbi",
    bank_name: "SBI",
    agreed_amount_paise: 250_000,
    created_at: "2026-09-30T18:30:00Z",
  }),
  row({
    id: "c3",
    deal_type: "property_deal",
    client_name: null,
    product_uuid: null,
    product_label: null,
    bank_uuid: null,
    bank_name: null,
    property_title: "Lakeview 3BHK",
    property_category: "apartments",
    lead_status: "expired",
    created_at: "2026-11-02T04:00:00Z",
  }),
];

const ids = (filters: Partial<typeof EMPTY_EARNINGS_FILTERS>) =>
  filterEarningsRows(rows, { ...EMPTY_EARNINGS_FILTERS, ...filters }).map((r) => r.id);

describe("filterEarningsRows", () => {
  it("keeps everything with no filters", () => {
    expect(ids({})).toEqual(["c1", "c2", "c3"]);
  });

  it("filters by status, deal type, lead status, product, bank and category", () => {
    expect(ids({ status: "paid" })).toEqual(["c1"]);
    expect(ids({ dealType: "property_deal" })).toEqual(["c3"]);
    expect(ids({ leadStatus: "expired" })).toEqual(["c3"]);
    expect(ids({ product: "p-car" })).toEqual(["c2"]);
    expect(ids({ bank: "b-hdfc" })).toEqual(["c1"]);
    expect(ids({ propertyCategory: "apartments" })).toEqual(["c3"]);
  });

  it("filters the commission amount in rupees", () => {
    expect(ids({ amountMin: "5,000" })).toEqual(["c1", "c3"]);
    expect(ids({ amountMax: "2500" })).toEqual(["c2"]);
    expect(ids({ amountMin: "abc" })).toEqual(["c1", "c2", "c3"]);
  });

  it("uses IST calendar days for the entry date", () => {
    // 2026-09-30T18:30Z is 1 Oct 00:00 IST.
    expect(ids({ from: "2026-10-01", to: "2026-10-31" })).toEqual(["c2"]);
    expect(ids({ to: "2026-09-30" })).toEqual(["c1"]);
  });

  it("searches names, products, banks, properties and id prefixes", () => {
    expect(ids({ search: "vikram" })).toEqual(["c2"]);
    expect(ids({ search: "LAKEVIEW" })).toEqual(["c3"]);
    expect(ids({ search: "sbi" })).toEqual(["c2"]);
    expect(ids({ search: "c3" })).toEqual(["c3"]);
  });
});

describe("helpers", () => {
  it("builds sorted, de-duplicated filter options", () => {
    const options = earningsFilterOptions(rows);
    expect(options.products).toEqual([
      { value: "p-car", label: "Car Loan" },
      { value: "p-home", label: "Home Loan" },
    ]);
    // The fixed category vocabulary, like every other property filter.
    expect(options.categories.map((o) => o.value)).toEqual(["apartments", "commercial", "houses", "plots", "villas"]);
    expect(options.leadStatuses.map((o) => o.label)).toEqual(["Converted", "Expired"]);
  });

  it("offers the catalogue's products and banks plus those in the history (CS-023)", () => {
    const options = earningsFilterOptions(rows, {
      loanTypes: [
        { value: "p-home", label: "Home Loan" },
        { value: "p-gold", label: "Gold Loan" },
      ],
      banks: [{ value: "b-axis", label: "Axis Bank" }],
    });
    expect(options.products.map((o) => o.value)).toEqual(["p-car", "p-gold", "p-home"]);
    expect(options.banks[0]).toEqual({ value: "b-axis", label: "Axis Bank" });
  });

  it("counts only the filters behind More filters", () => {
    expect(moreEarningsFilterCount(EMPTY_EARNINGS_FILTERS)).toBe(0);
    expect(
      moreEarningsFilterCount({ ...EMPTY_EARNINGS_FILTERS, status: "paid", bank: "b", amountMax: "10" }),
    ).toBe(2);
  });

  it("labels the previous month card", () => {
    const totals = {
      pending_amount_paise: 0,
      paid_amount_paise: 0,
      total_amount_paise: 0,
      last_month_paid_amount_paise: 0,
      last_month_start: "2026-10-01",
      last_month_end: "2026-10-31",
    };
    expect(commissionPaidLabel(totals)).toBe("Commission paid · Oct 2026");
    expect(commissionPaidLabel({ ...totals, last_month_start: null })).toBe("Commission paid");
  });

  it("converts rupees and humanizes statuses", () => {
    expect(rupeesToPaise("1,250.5")).toBe(125_050);
    expect(rupeesToPaise("")).toBeNull();
    expect(rupeesToPaise("-1")).toBeNull();
    expect(humanizeStatus("site_visit_done")).toBe("Site visit done");
    expect(humanizeStatus(null)).toBe("—");
  });
});
