import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, describe, expect, it, vi } from "vitest";

import {
  productListHref,
  productParam,
  specialistTitle,
  splitProductCounts,
  withDefaultProduct,
  withMyProductChip,
} from "./product-specialty";
import { ProductWorkPanels, SpecialtyChip } from "./product-work-panels";

// Next supplies the automatic JSX runtime; Vitest's existing config uses classic JSX.
vi.stubGlobal("React", React);
afterAll(() => vi.unstubAllGlobals());

const HOME = "10000000-0000-4000-8000-000000000001";
const CARD = "10000000-0000-4000-8000-000000000002";
const counts = [
  { product_id: CARD, label: "Platinum Card", category: "credit_card", open: 1, overdue: 0, converted_30d: 0 },
  { product_id: HOME, label: "Home Loan", category: "loan", open: 4, overdue: 2, converted_30d: 3 },
  { product_id: null, label: null, category: null, open: 2, overdue: 0, converted_30d: 1 },
];

describe("specialist product counts", () => {
  it("separates the specialty from fallback work", () => {
    const { mine, others } = splitProductCounts(counts, HOME);
    expect(mine?.open).toBe(4);
    expect(others.map((row) => row.product_id)).toEqual([CARD, null]);
  });

  it("gives unspecialised staff only the breakdown", () => {
    expect(splitProductCounts(counts, null)).toEqual({ mine: null, others: counts });
    expect(splitProductCounts(undefined, HOME)).toEqual({ mine: null, others: [] });
  });

  it("names the specialist and links lists to one product", () => {
    expect(specialistTitle("Home Loan")).toBe("Home Loan specialist");
    expect(productListHref("/dashboard/leads", HOME)).toBe(`/dashboard/leads?product=${HOME}`);
    expect(productListHref("/dashboard/leads", null)).toBe("/dashboard/leads");
  });
});

describe("My product list default", () => {
  it("presets the product once and never overrides a chosen one", () => {
    expect(withDefaultProduct({ loanTypeId: "all", status: "open" }, HOME)).toEqual({
      loanTypeId: HOME,
      status: "open",
    });
    expect(withDefaultProduct({ loanTypeId: CARD }, HOME)).toEqual({ loanTypeId: CARD });
    expect(withDefaultProduct({ loanTypeId: "all" }, null)).toEqual({ loanTypeId: "all" });
  });

  it("reads only a well-formed ?product= link", () => {
    expect(productParam(new URLSearchParams(`product=${HOME}`))).toBe(HOME);
    expect(productParam(new URLSearchParams("product=home-loan"))).toBeNull();
    expect(productParam(new URLSearchParams(""))).toBeNull();
  });

  it("labels the chip My product only while it shows the specialty", () => {
    const remove = () => undefined;
    const chips = [{ id: "loanTypeId", label: "Product: Home Loan", onRemove: remove }];
    expect(withMyProductChip(chips, HOME, HOME)[0].label).toBe("My product: Home Loan");
    expect(withMyProductChip(chips, CARD, HOME)[0].label).toBe("Product: Home Loan");
    expect(withMyProductChip(chips, HOME, null)[0].label).toBe("Product: Home Loan");
  });
});

describe("home product panels", () => {
  const specialty = { product_id: HOME, label: "Home Loan", category: "loan" };

  it("shows the specialty chip and the My product counts", () => {
    expect(renderToStaticMarkup(<SpecialtyChip specialty={specialty} />)).toContain("Home Loan specialist");
    const html = renderToStaticMarkup(<ProductWorkPanels kind="leads" specialty={specialty} counts={counts} />);
    for (const text of ["My product", "Open leads", "Follow-ups overdue", "Converted (30 days)", "Other products", "Platinum Card", "No product recorded"]) {
      expect(html).toContain(text);
    }
    expect(html).toContain(`/dashboard/leads?product=${HOME}`);
  });

  it("shows unspecialised staff only the breakdown", () => {
    const html = renderToStaticMarkup(<ProductWorkPanels kind="tasks" specialty={null} counts={counts} />);
    expect(html).not.toContain("My product");
    expect(html).toContain("Work by product");
    expect(html).toContain(`/dashboard/tasks?product=${CARD}`);
  });

  it("keeps the specialty panel when it has no work yet", () => {
    const html = renderToStaticMarkup(<ProductWorkPanels kind="tasks" specialty={specialty} counts={[]} />);
    expect(html).toContain("My product");
    expect(html).toContain("Open tasks");
    expect(html).not.toContain("Other products");
  });
});
