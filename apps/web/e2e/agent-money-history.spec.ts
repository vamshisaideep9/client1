import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// CS-022 (batch B): Agent commission summary, commission history with filters
// and detail sheet, payment trail, lead history and the optional cancelled
// cheque. Synthetic fixtures only.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "20000000-0000-4000-8000-000000000001";
const TXN_ID = "30000000-0000-4000-8000-000000000001";

function commission(overrides: Record<string, unknown>) {
  return {
    id: "40000000-0000-4000-8000-000000000001",
    business_line: "loans",
    deal_type: "loan_application",
    deal_uuid: "50000000-0000-4000-8000-000000000001",
    agreed_amount_paise: 4_000_000,
    status: "paid",
    payout_txn_uuid: TXN_ID,
    created_at: "2026-10-05T06:00:00Z",
    lead_uuid: LEAD_ID,
    lead_status: "converted",
    client_name: "Asha Rao",
    product_uuid: "60000000-0000-4000-8000-000000000001",
    product_label: "Home Loan",
    bank_uuid: "70000000-0000-4000-8000-000000000001",
    bank_name: "HDFC Bank",
    property_uuid: null,
    property_title: null,
    property_category: null,
    deal_status: "disbursed",
    deal_amount: "2500000.00",
    paid_at: "2026-10-12T06:00:00Z",
    ...overrides,
  };
}

const EARNINGS = {
  rows: [
    commission({}),
    commission({
      id: "40000000-0000-4000-8000-000000000002",
      deal_uuid: "50000000-0000-4000-8000-000000000002",
      agreed_amount_paise: 1_500_000,
      status: "pending",
      payout_txn_uuid: null,
      paid_at: null,
      client_name: "Vikram Shah",
      product_uuid: "60000000-0000-4000-8000-000000000002",
      product_label: "Car Loan",
      bank_uuid: "70000000-0000-4000-8000-000000000002",
      bank_name: "SBI",
      deal_status: "sanctioned",
    }),
  ],
  totals: {
    pending_amount_paise: 1_500_000,
    paid_amount_paise: 4_000_000,
    total_amount_paise: 5_500_000,
    last_month_paid_amount_paise: 4_000_000,
    last_month_start: "2026-10-01",
    last_month_end: "2026-10-31",
  },
  hidden_fields: [],
};

const TRANSACTION = {
  id: TXN_ID,
  type: "commission",
  status: "paid",
  amount_paise: 4_000_000,
  currency: "INR",
  description: "Commission payout",
  created_at: "2026-10-12T06:00:00Z",
  payout: {
    status: "paid",
    method: "vpa",
    provider: "razorpayx",
    destination_hint: "98******10@okhdfc",
    requested_at: "2026-10-10T06:00:00Z",
    approved_at: "2026-10-11T06:00:00Z",
    issued_at: null,
    paid_at: "2026-10-12T06:00:00Z",
    reversed_at: null,
    requested_by: { name: "Maker Person", role: "sub_admin" },
    approved_by: { name: "Checker Person", role: "admin" },
    approval_mode: "maker_checker",
  },
  items: [
    {
      commission_id: "40000000-0000-4000-8000-000000000001",
      amount_paise: 4_000_000,
      status: "paid",
      deal_type: "loan_application",
      deal_uuid: "50000000-0000-4000-8000-000000000001",
      lead_uuid: LEAD_ID,
      client_name: "Asha Rao",
      product_label: "Home Loan",
      bank_name: "HDFC Bank",
      property_title: null,
      deal_status: "disbursed",
      deal_amount: "2500000.00",
      entered_at: "2026-10-05T06:00:00Z",
    },
  ],
  hidden_fields: [],
};

async function asAgent(page: Page, baseURL: string | undefined) {
  await mockMobileApi(page, "agent");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.route("**/api/v1/agent/earnings", (route) => route.fulfill({ json: EARNINGS }));
  await page.route(`**/api/v1/agent/transactions/${TXN_ID}`, (route) => route.fulfill({ json: TRANSACTION }));
}

async function noHorizontalScroll(page: Page, width: number) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
}

test("home shows Total / Pending / Paid and last month's paid commission", async ({ page, baseURL }) => {
  await asAgent(page, baseURL);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Commission paid · Oct 2026")).toBeVisible();
  const summary = page.getByRole("region", { name: "Commission summary" }).or(
    page.locator("section", { has: page.getByRole("heading", { name: "Commission summary" }) }),
  );
  await expect(summary.getByText("Total")).toBeVisible();
  await expect(summary.getByText("Pending")).toBeVisible();
  await expect(summary.getByText("Paid", { exact: true })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`commission history filters and opens the payment trail (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await asAgent(page, baseURL);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/earnings", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Commission history" })).toBeVisible();
    await expect(page.getByText("2 of 2 commissions", { exact: false })).toBeVisible();
    await expect(page.getByText("Paid · Oct 2026")).toBeVisible();

    await page.getByLabel("Search commissions").fill("vikram");
    await expect(page.getByText("1 of 2 commissions", { exact: false })).toBeVisible();
    await expect(page.getByText("Asha Rao")).toHaveCount(0);
    await page.getByLabel("Search commissions").fill("");

    await page.getByRole("combobox", { name: "Filter by status" }).click();
    await page.getByRole("option", { name: "Paid" }).click();
    await expect(page.getByText("1 of 2 commissions", { exact: false })).toBeVisible();

    await page.getByRole("link", { name: /Asha Rao/ }).click();
    const sheet = page.getByRole("dialog", { name: "Commission details" });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByText("HDFC Bank")).toBeVisible();
    await expect(sheet.getByText("₹25,00,000")).toBeVisible();
    await sheet.getByRole("button", { name: "View payment trail" }).click();

    const trail = page.getByRole("dialog", { name: "Transaction details" });
    await expect(trail).toBeVisible();
    await expect(trail.getByText("98******10@okhdfc")).toBeVisible();
    await expect(trail.getByText("Maker Person (Sub Admin)")).toBeVisible();
    await expect(trail.getByText("Checker Person (Admin)")).toBeVisible();
    await noHorizontalScroll(page, width);
    await page.screenshot({ path: testInfo.outputPath(`agent-payment-trail-${width}.png`), fullPage: true });
  });
}

test("transactions page opens an Agent's payment trail", async ({ page, baseURL }) => {
  await asAgent(page, baseURL);
  await page.route("**/api/v1/transactions", (route) =>
    route.fulfill({
      json: {
        transactions: [
          {
            id: TXN_ID,
            type: "commission",
            status: "paid",
            amount_paise: 4_000_000,
            currency: "INR",
            description: "Commission payout",
            created_at: "2026-10-12T06:00:00Z",
          },
        ],
      },
    }),
  );
  await page.goto("/dashboard/transactions", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Commission payout.*view payment details/ }).click();
  const trail = page.getByRole("dialog", { name: "Transaction details" });
  await expect(trail.getByText("What this paid")).toBeVisible();
  await expect(trail.getByText(/Asha Rao/)).toBeVisible();
});

test("lead detail shows the lead's history and hidden fields", async ({ page, baseURL }, testInfo) => {
  await asAgent(page, baseURL);
  await page.route(`**/api/v1/agent/leads/${LEAD_ID}`, (route) =>
    route.fulfill({
      json: {
        id: LEAD_ID,
        name: "Asha Rao",
        mobile: "+919812345678",
        business_line: "loans",
        status: "converted",
        requirement: { notes: "Home loan" },
        registered: true,
        editable: false,
        resubmittable: false,
        expires_at: null,
        expired_at: null,
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-10-01T00:00:00Z",
      },
    }),
  );
  await page.route(`**/api/v1/agent/leads/${LEAD_ID}/history`, (route) =>
    route.fulfill({
      json: {
        lead_id: LEAD_ID,
        status: "converted",
        created_at: "2026-09-01T00:00:00Z",
        applications: [
          {
            id: "80000000-0000-4000-8000-000000000001",
            product_label: "Home Loan",
            bank_name: "HDFC Bank",
            status: "disbursed",
            amount_requested: null,
            amount_sanctioned: null,
            opened_at: "2026-09-02T00:00:00Z",
            closed_at: null,
            disbursed_at: "2026-09-20T00:00:00Z",
          },
        ],
        service_enquiries: [],
        deals: [],
        enquiries: [],
        site_visits: [],
        calls: [
          {
            id: "90000000-0000-4000-8000-000000000001",
            disposition: "connected",
            interest_level: "hot",
            notes: null,
            follow_up_at: null,
            created_at: "2026-09-03T06:00:00Z",
            staff_name: "Tara Caller",
          },
        ],
        timeline: [
          { event: "introduced", at: "2026-09-01T00:00:00Z", request_id: null, from_status: null, to_status: null },
          { event: "lead_assigned", at: "2026-09-01T01:00:00Z", request_id: null, from_status: null, to_status: null },
          {
            event: "loan_application_updated",
            at: "2026-09-20T00:00:00Z",
            request_id: "80000000-0000-4000-8000-000000000001",
            from_status: "sanctioned",
            to_status: "disbursed",
          },
        ],
        hidden_fields: ["call_notes", "deal_amount"],
      },
    }),
  );
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Applications and deals" })).toBeVisible();
  await expect(page.getByText("Home Loan", { exact: true })).toBeVisible();
  await expect(page.getByText("Loan application: Sanctioned → Disbursed")).toBeVisible();
  await expect(page.getByText("by Tara Caller")).toBeVisible();
  await expect(page.getByText("Your Admin hides call notes.")).toBeVisible();
  await expect(page.getByText("Loan and deal amounts are hidden by your Admin.")).toBeVisible();
  await noHorizontalScroll(page, 390);
  await page.screenshot({ path: testInfo.outputPath("agent-lead-history-390.png"), fullPage: true });
});

test("agent uploads an optional cancelled cheque", async ({ page, baseURL }) => {
  await asAgent(page, baseURL);
  let details: Record<string, unknown> = {
    saved: true,
    upi_hint: "***@okhdfc",
    bank_hint: "HDFC0001234 · ****6789",
    updated_at: "2026-11-14T00:00:00Z",
    available: true,
    cheque_uploaded_at: null,
    cheque_content_type: null,
  };
  let confirmed: Record<string, unknown> | null = null;
  await page.route("**/api/v1/agent/payout-details", (route) => route.fulfill({ json: details }));
  await page.route("**/api/v1/agent/payout-details/cheque/presign", (route) =>
    route.fulfill({
      json: {
        object_key: "private/agent-payout-cheques/staging/a/b/cheque.png",
        // The dev CSP allows the local MinIO origin for uploads.
        upload_url: "http://localhost:9000/dhanadhara-dev",
        fields: { key: "private/agent-payout-cheques/staging/a/b/cheque.png" },
        max_bytes: 5 * 1024 * 1024,
      },
    }),
  );
  await page.route("http://localhost:9000/**", (route) =>
    route.fulfill({ status: 201, body: "", headers: { "access-control-allow-origin": "*" } }),
  );
  await page.route("**/api/v1/agent/payout-details/cheque", async (route) => {
    confirmed = route.request().postDataJSON() as Record<string, unknown>;
    details = { ...details, cheque_uploaded_at: "2026-11-16T06:00:00Z", cheque_content_type: "image/png" };
    await route.fulfill({ json: details });
  });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

  const card = page.getByRole("region", { name: "Payout details" });
  await expect(card.getByText("Cancelled cheque (optional)")).toBeVisible();
  await expect(card.getByText("Not uploaded")).toBeVisible();

  // A wrong type is refused before any request.
  await card.locator("#cancelled-cheque-file").setInputFiles({
    name: "cheque.gif",
    mimeType: "image/gif",
    buffer: Buffer.from("GIF89a"),
  });
  await expect(card.getByText("Choose a JPEG, PNG or PDF file.")).toBeVisible();
  expect(confirmed).toBeNull();

  await card.locator("#cancelled-cheque-file").setInputFiles({
    name: "cheque.png",
    mimeType: "image/png",
    buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  });
  await expect.poll(() => confirmed).toEqual({
    object_key: "private/agent-payout-cheques/staging/a/b/cheque.png",
    content_type: "image/png",
  });
  await expect(card.getByText(/^Uploaded /)).toBeVisible();
  await expect(card.getByRole("button", { name: "Replace cancelled cheque" })).toBeVisible();
});
