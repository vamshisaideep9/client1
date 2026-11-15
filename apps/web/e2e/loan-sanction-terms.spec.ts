import { expect, test, type Page } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Security audit finding #5: a loan cannot reach
// sanctioned or disbursed without the sanctioned amount and lending bank.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "62000000-0000-4000-8000-000000000001";
const APP_ID = "63000000-0000-4000-8000-000000000001";
const BANK_ID = "64000000-0000-4000-8000-000000000001";

const application = {
  id: APP_ID,
  loan_type_id: FIXTURE_ID,
  loan_type_name: "Home Loan",
  bank_id: null,
  bank_name: null,
  amount_requested: "2500000.00",
  amount_sanctioned: null,
  interest_rate: null,
  processing_fee: null,
  fee_outcome: null,
  status: "new",
  status_reason: null,
  opened_at: "2026-11-10T05:15:00Z",
  closed_at: null,
  txns: [],
};

async function mockLead(page: Page) {
  await mockMobileApi(page, "telecaller");
  const patches: Record<string, unknown>[] = [];
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}`, (route) =>
    route.fulfill({
      json: {
        id: LEAD_ID,
        name: "Asha Rao",
        mobile: "+919876543210",
        business_line: "loans",
        status: "working",
        requirement: null,
        last_disposition: null,
        next_follow_up_at: null,
        created_at: "2026-11-10T05:00:00Z",
        updated_at: "2026-11-10T05:15:00Z",
        latest_request: {
          kind: "loan_application",
          id: APP_ID,
          title: "Home Loan",
          status: "new",
          applied_at: "2026-11-10T05:15:00Z",
        },
        activities: [],
        loan_applications: [application],
        financial_enquiries: [],
        property_enquiries: [],
        site_visits: [],
        property_deals: [],
        tasks: [],
      },
    }),
  );
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}/client-history`, (route) =>
    route.fulfill({ json: { business_line: "loans", leads: [] } }),
  );
  await page.route("**/api/v1/loans/banks**", (route) =>
    route.fulfill({ json: { banks: [{ id: BANK_ID, name: "Synthetic Bank" }] } }),
  );
  await page.route(`**/api/v1/telecaller/loan-applications/${APP_ID}`, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    patches.push(body);
    await route.fulfill({
      json: { ...application, ...body, bank_name: "Synthetic Bank" },
    });
  });
  return patches;
}

test("sanctioning a new loan asks for the amount and bank first", async ({ page, baseURL }, testInfo) => {
  const patches = await mockLead(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });

  const status = page.locator(`#loan-progress-status-${APP_ID}`);
  await expect(status).toBeVisible();
  // Terms are hidden while the loan is new and no forward move is chosen.
  await expect(page.locator(`#loan-progress-sanctioned-${APP_ID}`)).toHaveCount(0);

  await status.click();
  await page.getByRole("option", { name: "Approved", exact: true }).click();
  const amount = page.locator(`#loan-progress-sanctioned-${APP_ID}`);
  const bank = page.locator(`#loan-progress-bank-${APP_ID}`);
  await expect(amount).toBeVisible();
  await expect(amount).toHaveAttribute("aria-required", "true");

  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Enter the approved amount.")).toBeVisible();
  await expect(page.getByText("Choose the lending bank.")).toBeVisible();
  await expect(amount).toBeFocused();
  await expect(bank).toHaveAttribute("aria-invalid", "true");
  expect(patches).toHaveLength(0);
  await page.screenshot({ path: testInfo.outputPath("sanction-terms-required.png") });

  await amount.fill("1800000");
  await bank.click();
  await page.getByRole("option", { name: "Synthetic Bank" }).click();
  await expect(page.getByText("Choose the lending bank.")).toHaveCount(0);
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect.poll(() => patches.length).toBe(1);
  expect(patches[0]).toMatchObject({
    status: "sanctioned",
    amount_sanctioned: "1800000",
    bank_id: BANK_ID,
  });
});
