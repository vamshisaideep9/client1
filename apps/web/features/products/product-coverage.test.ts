import { describe, expect, it } from "vitest";

import type { ProductStaffPerson, ProductStaffingRow } from "@/lib/product-dashboards-api";

import {
  COVERAGE_LABEL,
  COVERAGE_TONE,
  DEFAULT_STAFFING_FILTERS,
  addSpecialistHref,
  assignableFor,
  compareStaffingRows,
  filterStaffingRows,
  formatRate,
  productDashboardHref,
} from "./product-coverage";

const HOME = "10000000-0000-4000-8000-000000000001";

function row(label: string, patch: Partial<ProductStaffingRow> = {}): ProductStaffingRow {
  return {
    product_id: `${label}-id`,
    label,
    category: "loan",
    active: true,
    telecallers: [],
    officers: [],
    open_leads: 0,
    unassigned_leads: 0,
    open_tasks: 0,
    coverage: "none",
    ...patch,
  };
}

function person(first: string, role: ProductStaffPerson["role"], status: ProductStaffPerson["status"] = "active"): ProductStaffPerson {
  return {
    staff_profile_uuid: `${first}-profile`,
    auth_user_uuid: `${first}-user`,
    first_name: first,
    last_name: "Synthetic",
    staff_code: `${first.toUpperCase()}-1`,
    role,
    business_line: "loans",
    status,
  };
}

describe("coverage flags", () => {
  it("labels every flag and never relies on color alone", () => {
    expect(COVERAGE_LABEL).toEqual({
      full: "Fully staffed",
      no_telecaller: "No Telecaller",
      no_officer: "No Officer",
      none: "No specialists",
    });
    expect(COVERAGE_TONE.full).toBe("success");
    expect(COVERAGE_TONE.none).toBe("danger");
  });

  it("puts gaps first, then the busiest products", () => {
    const rows = [
      row("Covered", { coverage: "full", open_leads: 50 }),
      row("Quiet gap", { coverage: "no_officer", open_leads: 1 }),
      row("Busy gap", { coverage: "none", open_leads: 9 }),
    ];
    expect([...rows].sort(compareStaffingRows).map((item) => item.label)).toEqual(["Busy gap", "Quiet gap", "Covered"]);
  });
});

describe("staffing filters", () => {
  const rows = [
    row("Home Loan", { coverage: "full" }),
    row("Platinum Card", { category: "credit_card", coverage: "no_officer" }),
    row("Old Insurance", { category: "insurance", active: false }),
  ];

  it("hides inactive products by default and filters by category, coverage and name", () => {
    expect(filterStaffingRows(rows, DEFAULT_STAFFING_FILTERS).map((item) => item.label)).toEqual(["Home Loan", "Platinum Card"]);
    expect(filterStaffingRows(rows, { ...DEFAULT_STAFFING_FILTERS, active: "all", category: "insurance" })).toHaveLength(1);
    expect(filterStaffingRows(rows, { ...DEFAULT_STAFFING_FILTERS, coverage: "no_officer" })[0].label).toBe("Platinum Card");
    expect(filterStaffingRows(rows, { ...DEFAULT_STAFFING_FILTERS, search: "home" })[0].label).toBe("Home Loan");
    expect(filterStaffingRows(rows, { ...DEFAULT_STAFFING_FILTERS, active: "inactive" })[0].label).toBe("Old Insurance");
  });
});

describe("staffing actions", () => {
  it("links to a prefilled create form and the product dashboard", () => {
    expect(addSpecialistHref("employee", HOME)).toBe(`/dashboard/users?role=employee&product=${HOME}`);
    expect(productDashboardHref(HOME)).toBe(`/dashboard/products/${HOME}`);
  });

  it("offers only active people of the chosen role, by name", () => {
    const available = [person("Zara", "telecaller"), person("Amit", "telecaller"), person("Omar", "employee"), person("Sid", "telecaller", "suspended")];
    expect(assignableFor(available, "telecaller").map((item) => item.first_name)).toEqual(["Amit", "Zara"]);
    expect(assignableFor(available, "employee").map((item) => item.first_name)).toEqual(["Omar"]);
  });

  it("formats rates and leaves missing ones blank", () => {
    expect(formatRate(20)).toBe("20%");
    expect(formatRate(33.333)).toBe("33.3%");
    expect(formatRate(null)).toBe("—");
  });
});
