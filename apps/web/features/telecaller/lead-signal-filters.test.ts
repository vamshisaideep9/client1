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
  leadSignalOptions,
  lineScope,
  matchesLeadSignals,
  rowsHiddenTransactionParts,
  scopedLeadSignalFilters,
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
    expect(leadSignalActiveCount(filters, lineScope("loans"))).toBe(2);
    expect(leadSignalActiveCount(filters, lineScope("real_estate"))).toBe(1);
    expect(leadSignalActiveCount(DEFAULT_LEAD_SIGNAL_FILTERS, lineScope("loans"))).toBe(0);
  });

  it("chips name the field and clear only their own filter", () => {
    const patches: Partial<LeadSignalFilters>[] = [];
    const chips = leadSignalChips(
      only({ callStatus: "not_called", source: "direct", referredBy: "AG-1" }),
      (patch) => patches.push(patch),
      lineScope("loans"),
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

// --- CS-023: product, property and transaction filters -------------------------

const HOME = "lt-home";
const PERSONAL = "lt-personal";
const HDFC = "bank-hdfc";
const SBI = "bank-sbi";

function summary(
  items: { txn_date: string | null; bank_name: string | null; amount: number | null }[],
  hidden: ("bank_names" | "amount" | "dates")[] = [],
): NonNullable<LeadSignalValues["transactions"]> {
  return {
    count: items.length,
    bank_names: [...new Set(items.map((item) => item.bank_name).filter((name): name is string => !!name))],
    amount_min: null,
    amount_max: null,
    first_date: null,
    last_date: null,
    items,
    hidden_fields: hidden,
  };
}

// Home loan at HDFC (sanctioned) and a personal loan at SBI (new).
const twoLoans: LeadSignalValues = {
  facets: {
    loans: [
      { loan_type_id: HOME, loan_type_label: "Home Loan", bank_id: HDFC, bank_name: "HDFC Bank", status: "sanctioned" },
      { loan_type_id: PERSONAL, loan_type_label: "Personal Loan", bank_id: SBI, bank_name: "SBI", status: "new" },
    ],
    deals: [],
  },
  transactions: summary([
    { txn_date: "2026-03-10", bank_name: "HDFC Bank", amount: 250000 },
    { txn_date: "2026-01-05", bank_name: "Axis Bank", amount: 900000 },
  ]),
};
const villaDeal: LeadSignalValues = {
  facets: {
    loans: [],
    deals: [
      { status: "booked", property_category: "villas", property_subtype: "villa" },
      { status: "new", property_category: "apartments", property_subtype: "standalone_apartment" },
    ],
  },
};
const noTransactions: LeadSignalValues = { facets: { loans: [], deals: [] }, transactions: summary([]) };

describe("product and property filters", () => {
  it("needs one application to match product, bank and status together", () => {
    expect(matchesLeadSignals(twoLoans, only({ loanTypeId: HOME }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ loanTypeId: HOME, bankId: HDFC }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ loanTypeId: HOME, bankId: SBI }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ bankId: SBI, loanStatus: "new" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ bankId: SBI, loanStatus: "sanctioned" }))).toBe(false);
    expect(matchesLeadSignals(directLead, only({ loanTypeId: HOME }))).toBe(false);
  });

  it("falls back to the loan statuses on rows without facets", () => {
    expect(matchesLeadSignals(agentLead, only({ loanStatus: "contacted" }))).toBe(true);
    expect(matchesLeadSignals(agentLead, only({ loanTypeId: HOME }))).toBe(false);
  });

  it("needs one deal to match category, type and deal status together", () => {
    expect(matchesLeadSignals(villaDeal, only({ propertyCategory: "villas" }))).toBe(true);
    expect(matchesLeadSignals(villaDeal, only({ propertySubtype: "standalone_apartment" }))).toBe(true);
    expect(matchesLeadSignals(villaDeal, only({ propertyCategory: "villas", dealStatus: "booked" }))).toBe(true);
    expect(matchesLeadSignals(villaDeal, only({ propertyCategory: "villas", dealStatus: "new" }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ dealStatus: "booked" }))).toBe(false);
  });
});

describe("transaction filters", () => {
  it("filters by having a transaction or none", () => {
    expect(matchesLeadSignals(twoLoans, only({ txnPresence: "has" }))).toBe(true);
    expect(matchesLeadSignals(noTransactions, only({ txnPresence: "has" }))).toBe(false);
    expect(matchesLeadSignals(noTransactions, only({ txnPresence: "none" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnPresence: "none" }))).toBe(false);
    // A row the caller has no transaction data for counts as none.
    expect(matchesLeadSignals(directLead, only({ txnPresence: "none" }))).toBe(true);
  });

  it("filters by an inclusive date range", () => {
    expect(matchesLeadSignals(twoLoans, only({ txnFrom: "2026-03-10" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnFrom: "2026-03-11" }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ txnTo: "2026-01-05" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnFrom: "2026-02-01", txnTo: "2026-02-28" }))).toBe(false);
  });

  it("matches the bank by name, whatever the spacing or case", () => {
    expect(matchesLeadSignals(twoLoans, only({ txnBank: "hdfc bank" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnBank: "icici bank" }))).toBe(false);
  });

  it("filters by an inclusive amount range in rupees", () => {
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMin: "900000" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMin: "900001" }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMax: "2,50,000" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMin: "300000", txnAmountMax: "800000" }))).toBe(false);
    // An inverted range matches nothing; blank or invalid ends are ignored.
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMin: "500000", txnAmountMax: "100000" }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ txnAmountMin: "abc" }))).toBe(true);
  });

  it("needs one transaction to match bank, date and amount together", () => {
    // HDFC was in March for 2.5 L; Axis in January for 9 L.
    expect(matchesLeadSignals(twoLoans, only({ txnBank: "hdfc bank", txnFrom: "2026-03-01" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnBank: "hdfc bank", txnAmountMin: "500000" }))).toBe(false);
    expect(matchesLeadSignals(twoLoans, only({ txnBank: "axis bank", txnTo: "2026-02-01", txnAmountMin: "500000" }))).toBe(true);
    expect(matchesLeadSignals(twoLoans, only({ txnPresence: "none", txnBank: "hdfc bank" }))).toBe(false);
  });
});

describe("filter scope", () => {
  it("drops every family the list does not offer", () => {
    const filters = only({
      loanTypeId: HOME,
      propertyCategory: "villas",
      txnPresence: "has",
      txnBank: "hdfc bank",
      txnFrom: "2026-01-01",
      txnAmountMin: "10",
    });
    const realEstate = scopedLeadSignalFilters(filters, lineScope("real_estate", true));
    expect([realEstate.loanTypeId, realEstate.propertyCategory, realEstate.txnPresence]).toEqual(["all", "villas", "all"]);
    const employee = scopedLeadSignalFilters(filters, lineScope("loans"));
    expect([employee.loanTypeId, employee.txnPresence, employee.txnBank]).toEqual([HOME, "all", "all"]);
    const hidden = scopedLeadSignalFilters(filters, lineScope("loans", true, new Set(["bank_names", "amount"])));
    expect([hidden.txnPresence, hidden.txnBank, hidden.txnFrom, hidden.txnAmountMin]).toEqual(["has", "all", "2026-01-01", ""]);
  });

  it("counts and chips only what is in scope", () => {
    const filters = only({ loanTypeId: HOME, propertySubtype: "villa", txnFrom: "2026-01-01", txnTo: "2026-01-31" });
    expect(leadSignalActiveCount(filters, lineScope("loans", true))).toBe(2);
    expect(leadSignalActiveCount(filters, lineScope("real_estate"))).toBe(1);
    const options = leadSignalOptions({ loanTypes: [], banks: [], bankNames: [] }, [twoLoans]);
    const chips = leadSignalChips(filters, () => undefined, lineScope("loans", true), options);
    expect(chips.map((chip) => chip.label)).toEqual([
      "Product: Home Loan",
      "Transaction date: 2026-01-01 to 2026-01-31",
    ]);
  });

  it("reads the Admin-hidden transaction parts off the rows", () => {
    const hidden = { transactions: summary([{ txn_date: null, bank_name: null, amount: 5 }], ["bank_names", "dates"]) };
    expect([...rowsHiddenTransactionParts([directLead, hidden])].sort()).toEqual(["bank_names", "dates"]);
    expect(rowsHiddenTransactionParts([directLead]).size).toBe(0);
  });
});

describe("filter options", () => {
  it("offers the catalogue plus every product and bank on the rows, once each", () => {
    const options = leadSignalOptions(
      {
        loanTypes: [{ value: HOME, label: "Home Loan" }],
        banks: [{ value: HDFC, label: "HDFC Bank" }],
        bankNames: ["HDFC Bank", "ICICI Bank"],
      },
      [twoLoans, villaDeal, directLead],
    );
    expect(options.loanTypes).toEqual([
      { value: HOME, label: "Home Loan" },
      { value: PERSONAL, label: "Personal Loan" },
    ]);
    expect(options.banks.map((bank) => bank.label)).toEqual(["HDFC Bank", "SBI"]);
    // Typed transaction names join the catalogue, keyed case-insensitively.
    expect(options.transactionBanks).toEqual([
      { value: "axis bank", label: "Axis Bank" },
      { value: "hdfc bank", label: "HDFC Bank" },
      { value: "icici bank", label: "ICICI Bank" },
    ]);
  });
});
