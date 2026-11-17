import { describe, expect, it } from "vitest";

import {
  EMPTY_OPTIONAL_PROFILE,
  optionalProfilePayload,
} from "@/components/profile/optional-profile-fields";

describe("optionalProfilePayload", () => {
  it("maps an empty optional profile to explicit nulls", () => {
    const result = optionalProfilePayload(EMPTY_OPTIONAL_PROFILE);
    expect(result).toEqual({
      ok: true,
      data: {
        gender: null,
        genderSelfDescription: null,
        incomeSource: null,
        incomeAmountMinor: null,
        incomePeriod: null,
        occupation: null,
        location: null,
        pincode: null,
      },
    });
  });

  it("keeps a valid pincode and refuses a malformed one (CS-026)", () => {
    const valid = optionalProfilePayload({ ...EMPTY_OPTIONAL_PROFILE, pincode: " 500001 " });
    expect(valid.ok && valid.data.pincode).toBe("500001");
    for (const pincode of ["012345", "50001", "5000011", "50a001"]) {
      const result = optionalProfilePayload({ ...EMPTY_OPTIONAL_PROFILE, pincode });
      expect(result.ok).toBe(false);
      expect(!result.ok && result.field).toBe("pincode");
    }
  });

  it("converts rupees to integer minor units", () => {
    const result = optionalProfilePayload({
      ...EMPTY_OPTIONAL_PROFILE,
      incomeSource: "salaried",
      incomeAmountRupees: "50000.25",
      incomePeriod: "monthly",
    });
    expect(result.ok && result.data.incomeAmountMinor).toBe(5_000_025);
  });

  it("keeps a trimmed manual location", () => {
    const result = optionalProfilePayload({
      ...EMPTY_OPTIONAL_PROFILE,
      location: "  Kondapur, Hyderabad  ",
    });
    expect(result.ok && result.data.location).toBe("Kondapur, Hyderabad");
  });

  it("requires a description for self-described gender", () => {
    const result = optionalProfilePayload({
      ...EMPTY_OPTIONAL_PROFILE,
      gender: "self_described",
    });
    expect(result.ok).toBe(false);
  });

  it("rejects malformed and out-of-range income", () => {
    expect(
      optionalProfilePayload({
        ...EMPTY_OPTIONAL_PROFILE,
        incomeSource: "business_income",
        incomeAmountRupees: "12.345",
        incomePeriod: "annual",
      }).ok,
    ).toBe(false);
    expect(
      optionalProfilePayload({
        ...EMPTY_OPTIONAL_PROFILE,
        incomeSource: "business_income",
        incomeAmountRupees: "10000000000.01",
        incomePeriod: "annual",
      }).ok,
    ).toBe(false);
  });
});
