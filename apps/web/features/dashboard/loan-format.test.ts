import { describe, expect, it } from "vitest";

import { PIPELINE, STATUS_STYLES } from "./loan-format";

describe("loan journey", () => {
  it("runs through review, approval and both agreement stages before disbursal", () => {
    expect(PIPELINE).toEqual([
      "new",
      "assigned",
      "contacted",
      "docs_collected",
      "submitted_to_bank",
      "under_review",
      "sanctioned",
      "agreement_collected",
      "agreement_submitted_to_bank",
      "disbursed",
      "closed",
    ]);
  });

  it("shows the stored 'sanctioned' status as Approved and labels every new stage", () => {
    expect(STATUS_STYLES.submitted_to_bank.label).toBe("Submitted to bank");
    expect(STATUS_STYLES.under_review.label).toBe("Under review");
    expect(STATUS_STYLES.sanctioned.label).toBe("Approved");
    expect(STATUS_STYLES.agreement_collected.label).toBe("Agreement collected");
    expect(STATUS_STYLES.agreement_submitted_to_bank.label).toBe("Agreement submitted to bank");
    expect(Object.values(STATUS_STYLES).map((style) => style.label)).not.toContain("Sanctioned");
  });
});
