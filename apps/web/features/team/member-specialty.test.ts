import { describe, expect, it } from "vitest";

import { NO_SPECIALTY, filterMembersBySpecialty, memberSpecialtyOptions } from "./member-specialty";

const HOME = "50000000-0000-4000-8000-000000000001";
const CARD = "50000000-0000-4000-8000-000000000002";

const rows = [
  { name: "Asha", member: { loan_specialty_id: HOME, loan_specialty_label: "Home Loan" } },
  { name: "Bala", member: { loan_specialty_id: CARD, loan_specialty_label: "Platinum Card" } },
  { name: "Chitra", member: { loan_specialty_id: HOME, loan_specialty_label: "Home Loan" } },
  { name: "Dev", member: { loan_specialty_id: null, loan_specialty_label: null } },
];

describe("team members by specialty", () => {
  it("offers each held specialty once, then No specialty", () => {
    expect(memberSpecialtyOptions(rows)).toEqual([
      { value: HOME, label: "Home Loan" },
      { value: CARD, label: "Platinum Card" },
      { value: NO_SPECIALTY, label: "No specialty" },
    ]);
    expect(memberSpecialtyOptions(rows.slice(0, 1))).toEqual([{ value: HOME, label: "Home Loan" }]);
  });

  it("filters members by specialty or by having none", () => {
    expect(filterMembersBySpecialty(rows, HOME).map((row) => row.name)).toEqual(["Asha", "Chitra"]);
    expect(filterMembersBySpecialty(rows, NO_SPECIALTY).map((row) => row.name)).toEqual(["Dev"]);
    expect(filterMembersBySpecialty(rows, "all")).toHaveLength(4);
  });
});
