import { describe, expect, it } from "vitest";

import {
  buildPayoutPayload,
  EMPTY_PAYOUT_FORM,
  rupeesToPaise,
  savedDestinationToForm,
  validatePayoutForm,
  type PayoutDestinationFormState,
  type PayoutFormState,
} from "@/lib/payout-form";

describe("rupeesToPaise()", () => {
  it("converts valid rupee strings to integer paise", () => {
    expect(rupeesToPaise("0.01")).toBe(1);
    expect(rupeesToPaise("1234.56")).toBe(123456);
    expect(rupeesToPaise("1000")).toBe(100_000);
  });

  it("rejects grouped, over-precision, non-positive, and out-of-range input", () => {
    expect(rupeesToPaise("1,000")).toBeNull();
    expect(rupeesToPaise("1.234")).toBeNull();
    expect(rupeesToPaise("-5")).toBeNull();
    expect(rupeesToPaise("0")).toBeNull();
    expect(rupeesToPaise("")).toBeNull();
    expect(rupeesToPaise("100000000.01")).toBeNull();
  });

  it("rejects leading zeros", () => {
    expect(rupeesToPaise("0007.50")).toBeNull();
    expect(rupeesToPaise("01")).toBeNull();
  });

  it("accepts exactly MAX_AMOUNT_PAISE and rejects one paisa over", () => {
    expect(rupeesToPaise("100000000.00")).toBe(10_000_000_000);
    expect(rupeesToPaise("100000000.01")).toBeNull();
  });

  it("would corrupt 19.99 by a paisa without Math.round (regression guard)", () => {
    // Documents why Math.round is load-bearing: the naive float multiply
    // undershoots the true integer paise value (1998.9999999999998).
    expect(Number.parseFloat("19.99") * 100).toBeLessThan(1999);
    expect(rupeesToPaise("19.99")).toBe(1999);
  });
});

function form(overrides: Partial<PayoutFormState>): PayoutFormState {
  return { ...EMPTY_PAYOUT_FORM, ...overrides };
}

describe("buildPayoutPayload()", () => {
  it("rejects a payout without an operational business line", () => {
    expect(() =>
      buildPayoutPayload(
        form({
          recipient: { authUserUuid: "u1", name: "Test User", code: "CL-X" },
          type: "cashback",
          businessLine: "",
          amountRupees: "100",
          destinationType: "vpa",
          vpa: "payee@okhdfc",
        }),
        "idem-key-12345",
      ),
    ).toThrow();
  });

  it("builds a bank_account destination", () => {
    const payload = buildPayoutPayload(
      form({
        recipient: { authUserUuid: "u2", name: "Test User", code: null },
        type: "commission",
        businessLine: "loans",
        amountRupees: "50",
        destinationType: "bank_account",
        ifsc: "HDFC0000123",
        accountNumber: "1234567890",
        accountName: "Test User",
      }),
      "idem-key-67890",
    );
    expect(payload.business_line).toBe("loans");
    expect(payload.destination).toEqual({
      ifsc: "HDFC0000123",
      account_number: "1234567890",
      name: "Test User",
    });
  });

  it("builds a cheque payout without bank or VPA details", () => {
    const payload = buildPayoutPayload(
      form({
        recipient: { authUserUuid: "u3", name: "Test User", code: null },
        type: "cashback",
        businessLine: "real_estate",
        amountRupees: "25",
        destinationType: "cheque",
        vpa: "stale@bank",
        ifsc: "STALE000001",
        accountNumber: "1234567890",
      }),
      "idem-key-cheque",
    );
    expect(payload.destination_type).toBe("cheque");
    expect(payload.destination).toEqual({});
  });

  it("throws rather than silently building a 0-paise payload when the amount is invalid", () => {
    expect(() =>
      buildPayoutPayload(
        form({
          recipient: { authUserUuid: "u1", name: "Test User", code: null },
          type: "cashback",
          businessLine: "loans",
          amountRupees: "not-a-number",
          destinationType: "vpa",
          vpa: "payee@okhdfc",
        }),
        "idem-key-11111",
      ),
    ).toThrow();
  });
});

describe("validatePayoutForm()", () => {
  it("requires a recipient, type, business line, amount, and destination", () => {
    const errs = validatePayoutForm(EMPTY_PAYOUT_FORM);
    expect(errs.recipient).toBeTruthy();
    expect(errs.type).toBeTruthy();
    expect(errs.businessLine).toBeTruthy();
    expect(errs.amountRupees).toBeTruthy();
    expect(errs.destinationType).toBeTruthy();
  });

  it("validates a vpa destination requires an @", () => {
    const errs = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: null },
        type: "cashback",
        businessLine: "loans",
        amountRupees: "10",
        destinationType: "vpa",
        vpa: "not-a-vpa",
      }),
    );
    expect(errs.vpa).toBeTruthy();
  });

  it("validates a bank_account destination requires ifsc and a 6+ digit account number", () => {
    const errs = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: null },
        type: "cashback",
        businessLine: "loans",
        amountRupees: "10",
        destinationType: "bank_account",
        ifsc: "",
        accountNumber: "123",
      }),
    );
    expect(errs.ifsc).toBeTruthy();
    expect(errs.accountNumber).toBeTruthy();
  });

  it("mirrors the API maximum lengths for payout destinations", () => {
    const longVpa = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: null },
        type: "cashback",
        businessLine: "loans",
        amountRupees: "10",
        destinationType: "vpa",
        vpa: `${"a".repeat(100)}@bank`,
      }),
    );
    expect(longVpa.vpa).toBe("UPI VPA must be 100 characters or fewer.");

    const longBankDetails = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: null },
        type: "cashback",
        businessLine: "loans",
        amountRupees: "10",
        destinationType: "bank_account",
        ifsc: "I".repeat(21),
        accountNumber: "1".repeat(41),
      }),
    );
    expect(longBankDetails.ifsc).toBe("IFSC must be 20 characters or fewer.");
    expect(longBankDetails.accountNumber).toBe(
      "Account number must be 40 characters or fewer.",
    );
  });

  it("passes for a fully valid form", () => {
    const errs = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: "CL-X" },
        type: "cashback",
        businessLine: "loans",
        amountRupees: "10",
        destinationType: "vpa",
        vpa: "payee@okhdfc",
      }),
    );
    expect(errs).toEqual({});
  });

  it("accepts cheque without destination credentials", () => {
    const errs = validatePayoutForm(
      form({
        recipient: { authUserUuid: "u1", name: "Test User", code: null },
        type: "cashback",
        businessLine: "real_estate",
        amountRupees: "10",
        destinationType: "cheque",
      }),
    );
    expect(errs).toEqual({});
  });
});

describe("savedDestinationToForm()", () => {
  const blank: PayoutDestinationFormState = {
    destinationType: "",
    vpa: "",
    ifsc: "",
    accountNumber: "",
    accountName: "",
  };
  const bank = {
    account_holder_name: "Test Agent",
    account_number: "50100123456789",
    ifsc: "HDFC0001234",
    bank_name: null,
  };
  const updatedAt = "2026-11-14T00:00:00Z";

  it("prefers UPI when the maker has not chosen a rail", () => {
    expect(
      savedDestinationToForm(blank, { upi_id: "me@okaxis", bank, updated_at: updatedAt }),
    ).toEqual({ ...blank, destinationType: "vpa", vpa: "me@okaxis" });
  });

  it("keeps the chosen bank rail when a bank account is saved", () => {
    expect(
      savedDestinationToForm(
        { ...blank, destinationType: "bank_account" },
        { upi_id: "me@okaxis", bank, updated_at: updatedAt },
      ),
    ).toEqual({
      destinationType: "bank_account",
      vpa: "",
      ifsc: "HDFC0001234",
      accountNumber: "50100123456789",
      accountName: "Test Agent",
    });
  });

  it("falls back to the saved rail and returns null when nothing is saved", () => {
    expect(
      savedDestinationToForm(
        { ...blank, destinationType: "vpa" },
        { upi_id: null, bank, updated_at: updatedAt },
      )?.destinationType,
    ).toBe("bank_account");
    expect(
      savedDestinationToForm(blank, { upi_id: null, bank: null, updated_at: updatedAt }),
    ).toBeNull();
  });
});
