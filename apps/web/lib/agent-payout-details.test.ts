import { describe, expect, it } from "vitest";

import {
  EMPTY_PAYOUT_DETAILS_DRAFT,
  buildPayoutDetailsPayload,
  validateChequeFile,
  validatePayoutDetailsDraft,
} from "./agent-payout-details";

const BANK = {
  accountHolderName: " Test Agent ",
  accountNumber: "50100123456789",
  ifsc: "hdfc0001234",
  bankName: "",
};

describe("validatePayoutDetailsDraft", () => {
  it("requires at least one destination", () => {
    expect(validatePayoutDetailsDraft(EMPTY_PAYOUT_DETAILS_DRAFT).form).toBeTruthy();
  });

  it("accepts a UPI ID on its own", () => {
    expect(
      validatePayoutDetailsDraft({ ...EMPTY_PAYOUT_DETAILS_DRAFT, upiId: "9876543210@okhdfc" }),
    ).toEqual({});
  });

  it("rejects a malformed UPI ID", () => {
    expect(
      validatePayoutDetailsDraft({ ...EMPTY_PAYOUT_DETAILS_DRAFT, upiId: "not-a-upi" }).upiId,
    ).toBeTruthy();
  });

  it("requires every bank field once any is entered", () => {
    const errors = validatePayoutDetailsDraft({ ...EMPTY_PAYOUT_DETAILS_DRAFT, bankName: "HDFC" });
    expect(errors.accountHolderName).toBeTruthy();
    expect(errors.accountNumber).toBeTruthy();
    expect(errors.ifsc).toBeTruthy();
  });

  it("accepts a lowercase IFSC and checks its shape", () => {
    expect(validatePayoutDetailsDraft({ ...EMPTY_PAYOUT_DETAILS_DRAFT, ...BANK })).toEqual({});
    expect(
      validatePayoutDetailsDraft({ ...EMPTY_PAYOUT_DETAILS_DRAFT, ...BANK, ifsc: "HDFC1234567" })
        .ifsc,
    ).toBeTruthy();
  });
});

describe("buildPayoutDetailsPayload", () => {
  it("sends only the filled destinations, trimmed and normalized", () => {
    expect(
      buildPayoutDetailsPayload({ ...EMPTY_PAYOUT_DETAILS_DRAFT, upiId: " me@okaxis " }),
    ).toEqual({ upi_id: "me@okaxis" });
    expect(buildPayoutDetailsPayload({ ...EMPTY_PAYOUT_DETAILS_DRAFT, ...BANK })).toEqual({
      bank: {
        account_holder_name: "Test Agent",
        account_number: "50100123456789",
        ifsc: "HDFC0001234",
        bank_name: null,
      },
    });
  });
});

describe("validateChequeFile", () => {
  it("accepts JPEG, PNG and PDF up to 5 MB", () => {
    expect(validateChequeFile({ type: "image/jpeg", size: 1024 })).toBeNull();
    expect(validateChequeFile({ type: "application/pdf", size: 5 * 1024 * 1024 })).toBeNull();
  });

  it("refuses other types, empty and oversize files", () => {
    expect(validateChequeFile({ type: "image/webp", size: 1024 })).toBe(
      "Choose a JPEG, PNG or PDF file.",
    );
    expect(validateChequeFile({ type: "image/png", size: 0 })).toBe("This file is empty.");
    expect(validateChequeFile({ type: "image/png", size: 5 * 1024 * 1024 + 1 })).toBe(
      "Choose a file of 5 MB or less.",
    );
  });
});
