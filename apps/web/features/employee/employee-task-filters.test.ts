import { describe, expect, it } from "vitest";

import { DEFAULT_LEAD_SIGNAL_FILTERS } from "@/features/telecaller/lead-signal-filters";
import { withDefaultProduct } from "@/features/dashboard/product-specialty";
import type { EmployeeTask } from "@/lib/employee-api";

import { employeeSignalValues, filterTasksByLeadSignals } from "./employee-task-filters";

const INSURANCE = "10000000-0000-4000-8000-000000000003";
const HOME = "10000000-0000-4000-8000-000000000001";

function task(id: string, patch: Partial<EmployeeTask> = {}): EmployeeTask {
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
    created_at: "2026-11-26T00:00:00Z",
    updated_at: "2026-11-26T00:00:00Z",
    ...patch,
  };
}

describe("Officer task product filter", () => {
  const tasks = [
    task("insured", { product_id: INSURANCE, product_label: "Term Insurance" }),
    task("applied", {
      lead_facets: {
        loans: [{ loan_type_id: HOME, loan_type_label: "Home Loan", status: "new" }],
        deals: [],
      },
    }),
    task("unknown"),
  ];

  it("reads the stored product of the task's lead", () => {
    expect(employeeSignalValues(tasks[0])).toMatchObject({
      productId: INSURANCE,
      productLabel: "Term Insurance",
    });
  });

  it("matches the stored product first, then the lead's applications", () => {
    const byProduct = (loanTypeId: string) =>
      filterTasksByLeadSignals(tasks, { ...DEFAULT_LEAD_SIGNAL_FILTERS, loanTypeId }).map((t) => t.id);
    expect(byProduct(INSURANCE)).toEqual(["insured"]);
    expect(byProduct(HOME)).toEqual(["applied"]);
    expect(byProduct("all")).toEqual(["insured", "applied", "unknown"]);
  });

  it("defaults a specialist to their product without overriding a choice", () => {
    const preset = withDefaultProduct(DEFAULT_LEAD_SIGNAL_FILTERS, INSURANCE);
    expect(filterTasksByLeadSignals(tasks, preset).map((t) => t.id)).toEqual(["insured"]);
    const cleared = { ...preset, loanTypeId: "all" };
    expect(filterTasksByLeadSignals(tasks, cleared)).toHaveLength(3);
  });
});
