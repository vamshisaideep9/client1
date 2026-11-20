import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: Agent greeting, required lead name, expiry policy
// with resubmit, and saved payout details.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "20000000-0000-4000-8000-000000000001";

function expiredLead(overrides: Record<string, unknown> = {}) {
  return {
    id: LEAD_ID,
    name: "Asha Verma",
    mobile: "+919812345678",
    business_line: "loans",
    status: "expired",
    requirement: { notes: "Home loan" },
    registered: false,
    editable: false,
    resubmittable: true,
    expires_at: "2026-10-01T00:00:00Z",
    expired_at: "2026-10-01T00:15:00Z",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-10-01T00:15:00Z",
    ...overrides,
  };
}

async function asAgent(page: Page, baseURL: string | undefined) {
  await mockMobileApi(page, "agent");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
}

test("agent home greets the agent by name", async ({ page, baseURL }) => {
  await asAgent(page, baseURL);
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Hi Mobile" })).toBeVisible();
  await expect(page.getByText("Agent workspace")).toHaveCount(0);
});

test("introducing a lead requires a name", async ({ page, baseURL }) => {
  await asAgent(page, baseURL);
  let posted = false;
  await page.route("**/api/v1/agent/leads", async (route) => {
    if (route.request().method() === "POST") posted = true;
    await route.fallback();
  });
  await page.goto("/dashboard/leads/new", { waitUntil: "domcontentloaded" });

  await page.getByLabel("Mobile number").fill("9812345678");
  await page.getByRole("button", { name: "Introduce lead" }).click();
  await expect(page.getByText("Enter the person's name.")).toBeVisible();
  await expect(page.getByLabel(/^Name/)).toBeFocused();
  expect(posted).toBe(false);
});

test("expired lead shows the policy and can be resubmitted", async ({ page, baseURL }, testInfo) => {
  await asAgent(page, baseURL);
  let resubmitted = false;
  await page.route("**/api/v1/agent/leads", async (route) => {
    await route.fulfill({ json: [expiredLead(resubmitted ? { status: "assigned", resubmittable: false, expired_at: null } : {})] });
  });
  await page.route(`**/api/v1/agent/leads/${LEAD_ID}/resubmit`, async (route) => {
    resubmitted = true;
    await route.fulfill({
      json: expiredLead({ status: "assigned", resubmittable: false, expired_at: null, expires_at: "2026-12-14T00:00:00Z" }),
    });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });

  await expect(page.getByText(/doesn't respond within 30 days, the lead expires/)).toBeVisible();
  await expect(page.getByText(/Expired .* — you can resubmit it/)).toBeVisible();
  await expect(page.getByText(/Expires in \d+ days?/)).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("agent-leads-expired.png"), fullPage: true });

  await page.getByRole("button", { name: "Resubmit" }).click();
  const dialog = page.getByRole("dialog", { name: "Resubmit Asha Verma?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Resubmit lead" }).click();

  await expect.poll(() => resubmitted).toBe(true);
  await expect(page.getByText("Lead resubmitted")).toBeVisible();
  // The dialog click did not navigate through the clickable table row.
  await expect(page).toHaveURL(/\/dashboard\/leads$/);
  await expect(page.getByRole("button", { name: "Resubmit" })).toHaveCount(0);
});

test("agent saves payout details and sees only masked values", async ({ page, baseURL }, testInfo) => {
  await asAgent(page, baseURL);
  let saved: Record<string, unknown> | null = null;
  await page.route("**/api/v1/agent/payout-details", async (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      saved = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: { saved: true, upi_hint: "***@okhdfc", bank_hint: null, updated_at: "2026-11-14T00:00:00Z", available: true },
      });
      return;
    }
    await route.fulfill({ json: { saved: false, upi_hint: null, bank_hint: null, updated_at: null, available: true } });
  });
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

  const card = page.getByRole("region", { name: "Payout details" });
  await expect(card).toBeVisible();
  await card.getByLabel("UPI ID").fill("not-a-upi");
  await card.getByRole("button", { name: "Save payout details" }).click();
  await expect(card.getByText("Enter a UPI ID like name@bank.")).toBeVisible();
  expect(saved).toBeNull();

  await card.getByLabel("UPI ID").fill("9876543210@okhdfc");
  await card.getByRole("button", { name: "Save payout details" }).click();
  await expect.poll(() => saved).toEqual({ upi_id: "9876543210@okhdfc" });
  await expect(card.getByText("***@okhdfc")).toBeVisible();
  await expect(card.getByText("9876543210@okhdfc")).toHaveCount(0);

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await card.screenshot({ path: testInfo.outputPath("payout-details-360.png") });
});

test("payout details are not offered to clients", async ({ page, baseURL }) => {
  await mockMobileApi(page, "client");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Payout details" })).toHaveCount(0);
});
