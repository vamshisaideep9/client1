import { expect, test, type Page } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: staff sidebar collapse, the assignment toast, and
// the responsive add-transaction dialog. No live account or backend.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "20000000-0000-4000-8000-000000000001";
const APP_ID = "30000000-0000-4000-8000-000000000001";

function assignment(index: number, readAt: string | null = null) {
  return {
    id: `40000000-0000-4000-8000-00000000000${index}`,
    type: "lead_assigned",
    title: "New lead assigned",
    body: "A new loans lead has been assigned to you.",
    href: "/dashboard/leads",
    read_at: readAt,
    created_at: "2026-11-13T10:00:00Z",
  };
}

async function mockTelecaller(page: Page) {
  await mockMobileApi(page, "telecaller");
  await page.route("**/api/v1/notifications", (route) =>
    route.fulfill({
      json: {
        notifications: [1, 2, 3, 4].map((i) => assignment(i)).concat(assignment(5, "2026-11-13T11:00:00Z")),
      },
    }),
  );
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}`, (route) =>
    route.fulfill({
      json: {
        id: LEAD_ID,
        name: "Asha Verma",
        mobile: "+919876543210",
        business_line: "loans",
        status: "working",
        requirement: null,
        last_disposition: null,
        next_follow_up_at: null,
        created_at: "2026-11-01T09:00:00Z",
        updated_at: "2026-11-13T09:00:00Z",
        activities: [],
        tasks: [],
        property_deals: [],
        loan_applications: [
          {
            id: APP_ID,
            loan_type_id: FIXTURE_ID,
            loan_type_name: "Home Loan",
            bank_id: null,
            bank_name: "HDFC Bank",
            amount_requested: "4500000.00",
            status: "submitted_to_bank",
            txns: [
              {
                id: "50000000-0000-4000-8000-000000000001",
                loan_application_uuid: APP_ID,
                bank_name: "HDFC Bank",
                amount: "4200000.00",
                interest_rate: "8.650",
                txn_date: "2026-11-10",
                created_at: "2026-11-10T09:00:00Z",
              },
            ],
          },
        ],
      },
    }),
  );
}

test("telecaller sees how many new leads were assigned, once per tab", async ({ page, baseURL }) => {
  await mockTelecaller(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1365, height: 844 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

  const toast = page.getByText("4 new leads have been assigned to you");
  await expect(toast).toBeVisible();
  await page.getByRole("button", { name: "View" }).click();
  await expect(page).toHaveURL(/\/dashboard\/leads$/);

  // The same unread assignments are not announced again after a reload.
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator('nav[aria-label="Workspace"]:visible')).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(toast).toHaveCount(0);
});

test("telecaller can collapse the desktop sidebar and keeps the choice", async ({ page, baseURL }) => {
  await mockTelecaller(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1365, height: 844 });
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });

  const sidebar = page.locator("aside").getByRole("navigation", { name: "Workspace" });
  const collapse = sidebar.getByRole("button", { name: "Collapse sidebar" });
  await expect(collapse).toBeVisible();
  const expandedWidth = (await sidebar.boundingBox())!.width;
  await collapse.click();
  const expand = sidebar.getByRole("button", { name: "Expand sidebar" });
  await expect(expand).toBeFocused();
  await expect.poll(async () => (await sidebar.boundingBox())!.width).toBeLessThan(expandedWidth);
  // Collapsed rail keeps every destination named for assistive technology.
  await expect(sidebar.getByRole("link", { name: "Leads", exact: true })).toBeVisible();

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(sidebar.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
});

for (const width of [360, 768, 1024, 1440]) {
  test(`add-transaction dialog fits a ${width}px screen`, async ({ page, baseURL }, testInfo) => {
    await mockTelecaller(page);
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width, height: width < 768 ? 740 : 900 });
    await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: "Add transaction" }).click();
    const dialog = page.getByRole("dialog", { name: "Add transaction" });
    await expect(dialog).toBeVisible();

    // Bank defaults from the application, the date from today.
    await expect(dialog.getByLabel("Bank")).toHaveValue("HDFC Bank");
    await expect(dialog.getByLabel("Transaction date")).not.toHaveValue("");
    await dialog.getByLabel("Amount").fill("500000");
    await expect(dialog.getByText(/5,00,000/)).toBeVisible();

    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
    for (const name of ["Cancel", "Save transaction"]) {
      const button = (await dialog.getByRole("button", { name }).boundingBox())!;
      expect(button.x + button.width).toBeLessThanOrEqual(box.x + box.width + 1);
      if (width < 640) expect(button.height).toBeGreaterThanOrEqual(44);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`add-txn-${width}.png`) });

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
  });
}
