// Agent payout details form (bank account / UPI ID). Pure validation and
// payload building, mirroring the API's patterns so most mistakes are caught
// before a request; the API remains the authority.
import type { AgentPayoutDetailsUpdate } from "@/lib/agent-api";

export type PayoutDetailsDraft = {
  upiId: string;
  accountHolderName: string;
  accountNumber: string;
  ifsc: string;
  bankName: string;
};

export const EMPTY_PAYOUT_DETAILS_DRAFT: PayoutDetailsDraft = {
  upiId: "",
  accountHolderName: "",
  accountNumber: "",
  ifsc: "",
  bankName: "",
};

const UPI_PATTERN = /^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$/;
const IFSC_PATTERN = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const ACCOUNT_PATTERN = /^\d{6,18}$/;

function hasBankInput(draft: PayoutDetailsDraft): boolean {
  return [draft.accountHolderName, draft.accountNumber, draft.ifsc, draft.bankName].some(
    (value) => value.trim() !== "",
  );
}

/** Field errors keyed by draft field; `form` holds a form-level message. */
export function validatePayoutDetailsDraft(
  draft: PayoutDetailsDraft,
): Partial<Record<keyof PayoutDetailsDraft | "form", string>> {
  const errors: Partial<Record<keyof PayoutDetailsDraft | "form", string>> = {};
  const upi = draft.upiId.trim();
  const bank = hasBankInput(draft);
  if (!upi && !bank) {
    errors.form = "Enter a UPI ID or bank account details.";
    return errors;
  }
  if (upi && !UPI_PATTERN.test(upi)) {
    errors.upiId = "Enter a UPI ID like name@bank.";
  }
  if (bank) {
    if (!draft.accountHolderName.trim()) {
      errors.accountHolderName = "Enter the account holder's name.";
    }
    if (!ACCOUNT_PATTERN.test(draft.accountNumber.trim())) {
      errors.accountNumber = "Enter a 6 to 18 digit account number.";
    }
    if (!IFSC_PATTERN.test(draft.ifsc.trim().toUpperCase())) {
      errors.ifsc = "Enter an 11-character IFSC, like HDFC0001234.";
    }
  }
  return errors;
}

/**
 * Only the destinations the Agent filled in are sent, so saving a new UPI ID
 * keeps an existing bank account (and vice versa).
 */
export function buildPayoutDetailsPayload(draft: PayoutDetailsDraft): AgentPayoutDetailsUpdate {
  const payload: AgentPayoutDetailsUpdate = {};
  const upi = draft.upiId.trim();
  if (upi) payload.upi_id = upi;
  if (hasBankInput(draft)) {
    payload.bank = {
      account_holder_name: draft.accountHolderName.trim(),
      account_number: draft.accountNumber.trim(),
      ifsc: draft.ifsc.trim().toUpperCase(),
      bank_name: draft.bankName.trim() || null,
    };
  }
  return payload;
}
