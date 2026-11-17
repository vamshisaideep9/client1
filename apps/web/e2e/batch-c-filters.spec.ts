import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. CS-023: product, property and transaction filters
// on the Telecaller leads list, product filters and the amount range in My
// analytics, and the product, bank and amount filters on the Admin loans list.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const HOME = "71000000-0000-4000-8000-000000000001";
const PERSONAL = "71000000-0000-4000-8000-000000000002";
const GOLD = "71000000-0000-4000-8000-000000000003";
const HDFC = "72000000-0000-4000-8000-000000000001";
const SBI = "72000000-0000-4000-8000-000000000002";

function summary(items: { txn_date: string; bank_name: string | null; amount: number | null }[], hidden: string[] = []) {
  return {
    count: items.length,
    bank_names: hidden.includes("bank_names")
      ? null
      : [...new Set(items.map((item) => item.bank_name).filter(Boolean))],
    amount_min: null,
    amount_max: null,
    first_date: null,
    last_date: null,
    items,
    hidden_fields: hidden,
  };
}

function lead(id: string, name: string, patch: Record<string, unknown>) {
  return {
    id,
    name,
    mobile: "+919876543210",
    business_line: "loans",
    status: "working",
    requirement: null,
    last_disposition: null,
    last_interest_level: null,
    next_follow_up_at: null,
    created_at: "2026-11-12T04:00:00Z",
    updated_at: "2026-11-14T08:45:00Z",
    latest_request: null,
    loan_statuses: [],
    referrer: null,
    facets: { loans: [], deals: [] },
    transactions: summary([]),
    ...patch,
  };
}

function loanLeads(hidden: string[] = []) {
  return [
    lead("73000000-0000-4000-8000-000000000001", "Home Loan Lead", {
      loan_statuses: ["sanctioned"],
      facets: {
        loans: [{ loan_type_id: HOME, loan_type_label: "Home Loan", bank_id: HDFC, bank_name: "HDFC Bank", status: "sanctioned" }],
        deals: [],
      },
      transactions: summary([{ txn_date: "2026-03-10", bank_name: hidden.length ? null : "HDFC Bank", amount: hidden.length ? null : 250000 }], hidden),
    }),
    lead("73000000-0000-4000-8000-000000000002", "Personal Loan Lead", {
      loan_statuses: ["new"],
      facets: {
        loans: [{ loan_type_id: PERSONAL, loan_type_label: "Personal Loan", bank_id: SBI, bank_name: "SBI", status: "new" }],
        deals: [],
      },
      transactions: summary([], hidden),
    }),
    lead("73000000-0000-4000-8000-000000000003", "No Application Lead", { transactions: summary([], hidden) }),
  ];
}

async function routeCatalogue(page: Page) {
  await page.route("**/api/v1/loans/loan-types", (route) =>
    route.fulfill({
      json: {
        loan_types: [
          { id: HOME, name: "home", label: "Home Loan", category: "loan" },
          { id: GOLD, name: "gold", label: "Gold Loan", category: "loan" },
          { id: "71000000-0000-4000-8000-000000000009", name: "card", label: "Credit Card", category: "credit_card" },
        ].map((product) => ({ ...product, display_order: 1, form_version: 1, form_schema: { sections: [] }, last_updated_at: null })),
      },
    }),
  );
  await page.route("**/api/v1/loans/banks**", (route) =>
    route.fulfill({ json: { banks: [{ id: HDFC, name: "HDFC Bank", logo_url: null, last_updated_at: null }] } }),
  );
}

async function openLeads(page: Page, baseURL: string, leads: unknown[], line = "loans") {
  await mockMobileApi(page, "telecaller", line);
  await routeCatalogue(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: leads }));
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });
  await expect(page.locator("tbody tr")).toHaveCount(leads.length);
}

const names = (page: Page) => page.locator("tbody tr td:first-child p.font-medium").allTextContents();

async function pick(page: Page, scope: ReturnType<Page["getByRole"]>, field: string, option: string) {
  await scope.getByRole("combobox", { name: `Filter by ${field}` }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("telecaller leads filter by product, bank and transactions, one application or transaction matching all", async ({
  page,
  baseURL,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openLeads(page, baseURL!, loanLeads());

  await page.getByRole("button", { name: "More filters" }).click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  for (const group of ["Lead", "Product", "Money"]) {
    await expect(dialog.getByRole("group", { name: group })).toBeVisible();
  }
  await expect(dialog.getByRole("group", { name: "Property" })).toHaveCount(0);

  // Options: the catalogue's lending products plus those on the rows.
  await dialog.getByRole("combobox", { name: "Filter by product" }).click();
  await expect(page.getByRole("option")).toHaveText(["All", "Gold Loan", "Home Loan", "Personal Loan"]);
  await page.getByRole("option", { name: "Home Loan" }).click();
  expect(await names(page)).toEqual(["Home Loan Lead"]);

  // Same application: Home Loan at SBI matches nothing.
  await pick(page, dialog, "bank", "SBI");
  await expect(page.getByText("No leads match your filters")).toBeVisible();
  await pick(page, dialog, "bank", "HDFC Bank");
  expect(await names(page)).toEqual(["Home Loan Lead"]);
  await expect(page.getByRole("button", { name: "More filters (2)" })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Remove filter Product: Home Loan" }).click();
  await page.getByRole("button", { name: "Remove filter Bank: HDFC Bank" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(3);

  await page.getByRole("button", { name: "More filters" }).click();
  await pick(page, dialog, "transactions", "No transaction");
  expect(await names(page)).toEqual(["Personal Loan Lead", "No Application Lead"]);
  await pick(page, dialog, "transactions", "Has a transaction");
  expect(await names(page)).toEqual(["Home Loan Lead"]);
  await pick(page, dialog, "transactions", "All");

  await dialog.getByLabel("Transaction date from").fill("2026-04-01");
  await expect(page.getByText("No leads match your filters")).toBeVisible();
  await dialog.getByLabel("Transaction date from").fill("2026-03-01");
  await dialog.getByLabel("Minimum transaction amount (₹)").fill("200000");
  expect(await names(page)).toEqual(["Home Loan Lead"]);
  await dialog.getByLabel("Minimum transaction amount (₹)").fill("300000");
  await expect(page.getByText("No leads match your filters")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(3);
});

test("transaction parts the Admin hides leave their filters out", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openLeads(page, baseURL!, loanLeads(["bank_names", "amount"]));

  await page.getByRole("button", { name: "More filters" }).click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  await expect(dialog.getByRole("combobox", { name: "Filter by transactions" })).toBeVisible();
  await expect(dialog.getByLabel("Transaction date from")).toBeVisible();
  await expect(dialog.getByRole("combobox", { name: "Filter by transaction bank" })).toHaveCount(0);
  await expect(dialog.getByLabel("Minimum transaction amount (₹)")).toHaveCount(0);
});

test("real estate leads filter by property category, type and deal status on a phone", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const estate = [
    lead("74000000-0000-4000-8000-000000000001", "Villa Lead", {
      business_line: "real_estate",
      facets: { loans: [], deals: [{ status: "booked", property_category: "villas", property_subtype: "villa" }] },
      transactions: null,
    }),
    lead("74000000-0000-4000-8000-000000000002", "Flat Lead", {
      business_line: "real_estate",
      facets: {
        loans: [],
        deals: [{ status: "new", property_category: "apartments", property_subtype: "standalone_apartment" }],
      },
      transactions: null,
    }),
  ];
  await openLeads(page, baseURL!, estate, "real_estate");
  // The filters and chips must not widen the page beyond what the list itself needs.
  const before = await page.evaluate(() => document.documentElement.scrollWidth);

  await page.getByRole("button", { name: "More filters" }).click();
  const sheet = page.getByRole("dialog", { name: "More filters" });
  await expect(sheet.getByRole("group", { name: "Property" })).toBeVisible();
  await expect(sheet.getByRole("group", { name: "Product" })).toHaveCount(0);
  await expect(sheet.getByRole("group", { name: "Money" })).toHaveCount(0);
  await pick(page, sheet, "property type", "Villas");
  await pick(page, sheet, "deal status", "Booked");
  await page.keyboard.press("Escape");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr").first()).toContainText("Villa Lead");
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(before);
});

test("My analytics sends product filters and leaves out an amount the Admin hides", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockMobileApi(page, "telecaller", "loans");
  await routeCatalogue(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  const queries: URLSearchParams[] = [];
  let hidden: string[] = [];
  await page.route("**/api/v1/me/analytics**", async (route) => {
    const url = new URL(route.request().url());
    queries.push(url.searchParams);
    await route.fulfill({
      json: {
        role: "telecaller",
        range_days: 31,
        date_from: url.searchParams.get("date_from"),
        date_to: url.searchParams.get("date_to"),
        bucket: "day",
        kpis: [{ key: "calls", label: "Calls logged", value: 4, unit: "count", hint: null }],
        trend: { title: "Calls per day", description: "", series: [], points: [] },
        breakdowns: [],
        funnel: null,
        hidden_filters: hidden,
      },
    });
  });
  await page.goto("/dashboard/insights", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Calls logged")).toBeVisible();

  await page.getByRole("button", { name: "More filters" }).click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  await expect(dialog.getByRole("group", { name: "Product" })).toBeVisible();
  await pick(page, dialog, "product", "Home Loan");
  await expect.poll(() => queries.at(-1)?.get("loan_type_id")).toBe(HOME);
  await dialog.getByLabel("Minimum loan amount (₹)").fill("1,00,000");
  await expect.poll(() => queries.at(-1)?.get("amount_min")).toBe("100000");
  await dialog.getByLabel("Maximum loan amount (₹)").fill("5000");
  await expect(dialog.getByText("The minimum is above the maximum, so the amount is not applied.")).toBeVisible();
  await expect.poll(() => queries.at(-1)?.has("amount_min")).toBe(false);
  await page.keyboard.press("Escape");

  // The Admin hides the amount: the next response says so and the control goes.
  hidden = ["amount_max", "amount_min"];
  await page.getByRole("button", { name: "Remove filter Product: Home Loan" }).click();
  await page.getByRole("button", { name: "More filters" }).click();
  await expect(dialog.getByLabel("Minimum loan amount (₹)")).toHaveCount(0);
  expect(queries.at(-1)?.has("amount_min")).toBe(false);
});

test("Admin loan applications filter by product, bank and requested amount", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mockMobileApi(page, "admin", "loans");
  await routeCatalogue(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  const application = (id: string, code: string, patch: Record<string, unknown>) => ({
    id,
    lead_uuid: id,
    customer_code: code,
    business_line: "loans",
    loan_type_id: HOME,
    loan_type_label: "Home Loan",
    bank_id: HDFC,
    bank_name: "HDFC Bank",
    amount_requested: "900000.00",
    amount_sanctioned: null,
    interest_rate: null,
    processing_fee: null,
    fee_outcome: null,
    status: "new",
    status_reason: null,
    opened_at: "2026-11-10T04:00:00Z",
    closed_at: null,
    form_version: null,
    form_schema_snapshot: null,
    form_answers: null,
    ...patch,
  });
  await page.route("**/api/v1/admin/loans**", (route) =>
    route.fulfill({
      json: {
        applications: [
          application("75000000-0000-4000-8000-000000000001", "CL-HOME", {}),
          application("75000000-0000-4000-8000-000000000002", "CL-PERSONAL", {
            loan_type_id: PERSONAL,
            loan_type_label: "Personal Loan",
            bank_id: SBI,
            bank_name: "SBI",
            amount_requested: "150000.00",
          }),
        ],
      },
    }),
  );
  await page.goto("/dashboard/loan-applications", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("CL-HOME")).toBeVisible();

  await page.getByRole("button", { name: "More filters" }).click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  await pick(page, dialog, "product", "Personal Loan");
  await expect(page.getByText("CL-HOME")).toHaveCount(0);
  await expect(page.getByText("CL-PERSONAL")).toBeVisible();
  await pick(page, dialog, "product", "All");
  await dialog.getByLabel("Minimum requested amount (₹)").fill("500000");
  await expect(page.getByText("CL-PERSONAL")).toHaveCount(0);
  await expect(page.getByText("CL-HOME")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.getByText("CL-PERSONAL")).toBeVisible();
});
