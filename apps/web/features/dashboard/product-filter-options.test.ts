import { describe, expect, it } from "vitest";

import { matchesAdminLoanDetail, adminLoanDetailCount, adminLoanOptions, EMPTY_ADMIN_LOAN_DETAIL } from "@/features/admin/admin-loan-filters";
import { priceInRange } from "@/features/admin/property-deals-view";
import { buildReportParams, detailForLine } from "@/lib/reports";

import {
  PROPERTY_SUBTYPE_LABEL,
  amountRangeInverted,
  amountRangeLabel,
  hiddenTransactionParts,
  mergeOptions,
  normalizeName,
  parseRupees,
  transactionBankOptions,
} from "./product-filter-options";

describe("product filter options (CS-023)", () => {
  it("merges option lists once per value, the first label winning, sorted by label", () => {
    expect(
      mergeOptions(
        [{ value: "a", label: "Home Loan" }],
        [
          { value: "a", label: "Old name" },
          { value: "b", label: "Car Loan" },
          { value: "", label: "Blank" },
        ],
      ),
    ).toEqual([
      { value: "b", label: "Car Loan" },
      { value: "a", label: "Home Loan" },
    ]);
  });

  it("normalises bank names so spelling variants collapse", () => {
    expect(normalizeName("  HDFC   bank ")).toBe("hdfc bank");
    expect(normalizeName(null)).toBe("");
    const options = transactionBankOptions(
      ["HDFC Bank"],
      [{ count: 1, bank_names: ["hdfc  BANK", "Kotak"], items: [], hidden_fields: [] }, null],
    );
    expect(options).toEqual([
      { value: "hdfc bank", label: "HDFC Bank" },
      { value: "kotak", label: "Kotak" },
    ]);
  });

  it("reads the hidden transaction parts from the first summary", () => {
    expect([...hiddenTransactionParts([null, { count: 0, items: [], hidden_fields: ["amount"] }])]).toEqual(["amount"]);
    expect(hiddenTransactionParts([undefined]).size).toBe(0);
  });

  it("parses typed rupees and labels ranges", () => {
    expect(parseRupees(" 1,50,000 ")).toBe(150000);
    expect(parseRupees("")).toBeNull();
    expect(parseRupees("-5")).toBeNull();
    expect(parseRupees("abc")).toBeNull();
    expect(amountRangeInverted("10", "5")).toBe(true);
    expect(amountRangeInverted("10", "")).toBe(false);
    expect(amountRangeLabel("100000", "500000")).toBe("₹1,00,000 – ₹5,00,000");
    expect(amountRangeLabel("100000", "")).toBe("From ₹1,00,000");
    expect(amountRangeLabel("", "500")).toBe("Up to ₹500");
    expect(amountRangeLabel("", "")).toBeNull();
  });

  it("labels every property subtype from the catalogue", () => {
    expect(Object.keys(PROPERTY_SUBTYPE_LABEL)).toHaveLength(9);
    expect(PROPERTY_SUBTYPE_LABEL.gated_community_apartment).toBe("Gated community apartments");
  });
});

describe("Admin loan-applications filters", () => {
  const row = { loan_type_id: "lt-1", bank_id: "b-1", amount_requested: "500000.00" };

  it("filters by product, bank and requested amount together", () => {
    expect(matchesAdminLoanDetail(row, EMPTY_ADMIN_LOAN_DETAIL)).toBe(true);
    expect(matchesAdminLoanDetail(row, { ...EMPTY_ADMIN_LOAN_DETAIL, loanTypeId: "lt-1", bankId: "b-1" })).toBe(true);
    expect(matchesAdminLoanDetail(row, { ...EMPTY_ADMIN_LOAN_DETAIL, bankId: "b-2" })).toBe(false);
    expect(matchesAdminLoanDetail(row, { ...EMPTY_ADMIN_LOAN_DETAIL, amountMin: "500000" })).toBe(true);
    expect(matchesAdminLoanDetail(row, { ...EMPTY_ADMIN_LOAN_DETAIL, amountMax: "499999" })).toBe(false);
    expect(matchesAdminLoanDetail({ ...row, amount_requested: null }, { ...EMPTY_ADMIN_LOAN_DETAIL, amountMin: "1" })).toBe(
      false,
    );
    expect(adminLoanDetailCount({ ...EMPTY_ADMIN_LOAN_DETAIL, bankId: "b-1", amountMin: "1", amountMax: "2" })).toBe(2);
  });

  it("offers the catalogue plus the rows' products and banks", () => {
    const options = adminLoanOptions(
      [
        // Row type carries more fields; only these matter here.
        { loan_type_id: "lt-old", loan_type_label: "Old Product", bank_id: null, bank_name: null } as never,
        { loan_type_id: "lt-1", loan_type_label: "Home Loan", bank_id: "b-1", bank_name: "HDFC Bank" } as never,
      ],
      { loanTypes: [{ value: "lt-1", label: "Home Loan" }], banks: [] },
    );
    expect(options.loanTypes.map((o) => o.value)).toEqual(["lt-1", "lt-old"]);
    expect(options.banks).toEqual([{ value: "b-1", label: "HDFC Bank" }]);
  });

  it("keeps property deals to the quoted price range", () => {
    expect(priceInRange("8000000.00", { min: "5000000", max: "" })).toBe(true);
    expect(priceInRange("8000000.00", { min: "", max: "5000000" })).toBe(false);
    expect(priceInRange(null, { min: "1", max: "" })).toBe(false);
    expect(priceInRange(null, { min: "", max: "" })).toBe(true);
  });
});

describe("Admin report detail filters", () => {
  it("sends amounts as plain rupees and leaves an inverted range out", () => {
    const params = buildReportParams({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-15",
      detail: { amountMin: "1,00,000", amountMax: "5,00,000", propertySubtype: "villa" },
    });
    expect(params.get("amount_min")).toBe("100000");
    expect(params.get("amount_max")).toBe("500000");
    expect(params.get("property_subtype")).toBe("villa");
    const inverted = buildReportParams({
      dateFrom: "2026-11-01",
      dateTo: "2026-11-15",
      detail: { amountMin: "9", amountMax: "1" },
    });
    expect(inverted.has("amount_min") || inverted.has("amount_max")).toBe(false);
  });

  it("drops the other line's filters when the leads report switches line", () => {
    const detail = { loanTypeId: "lt-1", bankId: "b-1", propertySubtype: "villa", leadSource: "agent" as const };
    expect(detailForLine(detail, "real_estate")).toEqual({ propertySubtype: "villa", leadSource: "agent" });
    expect(detailForLine(detail, "loans")).toEqual({ loanTypeId: "lt-1", bankId: "b-1", leadSource: "agent" });
    expect(detailForLine(detail, undefined)).toEqual(detail);
  });
});
