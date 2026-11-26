import { describe, expect, it } from "vitest";

import type { AdminLoanType } from "@/lib/loan-config-api";

import { specialtyGroups } from "./product-specialty-select";
import { specialtyAllowed, specialtyPrefill } from "./staff-specialty-rules";

const PRODUCT = "10000000-0000-4000-8000-000000000001";

describe("product specialty rules", () => {
  it("lets Loans and dual-line Telecallers and Officers specialise", () => {
    for (const role of ["telecaller", "employee"]) {
      expect(specialtyAllowed(role, "loans")).toBe(true);
      expect(specialtyAllowed(role, "both")).toBe(true);
      expect(specialtyAllowed(role, "real_estate")).toBe(false);
      expect(specialtyAllowed(role, "")).toBe(false);
    }
    expect(specialtyAllowed("sub_admin", "loans")).toBe(false);
    expect(specialtyAllowed("admin", "")).toBe(false);
  });

  it("prefills the create form from the staffing page links", () => {
    expect(specialtyPrefill(new URLSearchParams(`role=employee&product=${PRODUCT}`))).toEqual({
      role: "employee",
      business_line: "loans",
      loan_specialty_id: PRODUCT,
    });
    expect(specialtyPrefill(new URLSearchParams("role=telecaller&product=not-a-uuid"))).toEqual({
      role: "telecaller",
      business_line: "loans",
      loan_specialty_id: "",
    });
    expect(specialtyPrefill(new URLSearchParams(`role=admin&product=${PRODUCT}`))).toBeNull();
    expect(specialtyPrefill(new URLSearchParams(""))).toBeNull();
  });

  it("groups active products of every category in catalogue order", () => {
    const product = (id: string, category: AdminLoanType["category"], active = true) =>
      ({ id, label: id, category, active }) as AdminLoanType;
    const groups = specialtyGroups([
      product("Term Insurance", "insurance"),
      product("Home Loan", "loan"),
      product("Retired Loan", "loan", false),
      product("Platinum Card", "credit_card"),
    ]);
    expect(groups.map((group) => [group.label, group.products.map((item) => item.label)])).toEqual([
      ["Loans", ["Home Loan"]],
      ["Credit cards", ["Platinum Card"]],
      ["Insurance", ["Term Insurance"]],
    ]);
  });
});
