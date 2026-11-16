import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. The development RazorpayX simulator: approving a
// UPI payout opens the test-mode dialog, and the chosen outcome is posted as a
// gateway event. The API owns every rule; these routes only stand in for it.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const PAYOUT_ID = "71000000-0000-4000-8000-000000000001";
const PAID_ID = "71000000-0000-4000-8000-000000000002";
const RECIPIENT_ID = "72000000-0000-4000-8000-000000000001";
const MAKER_ID = "72000000-0000-4000-8000-000000000002";

function payout(overrides: Record<string, unknown>) {
  return {
    id: PAYOUT_ID,
    recipient_user_uuid: RECIPIENT_ID,
    type: "commission",
    business_line: "loans",
    amount_paise: 2_500_000,
    currency: "INR",
    status: "pending_approval",
    destination_type: "vpa",
    provider: "razorpayx",
    destination_hint: "UPI · as****@okaxis",
    maker_user_uuid: MAKER_ID,
    checker_user_uuid: null,
    rejected_by_user_uuid: null,
    reject_reason: null,
    gateway_payout_id: null,
    gateway_status: null,
    failure_reason: null,
    manual_issued_at: null,
    manual_cleared_at: null,
    reversal_transaction_id: null,
    created_at: "2026-11-15T05:00:00Z",
    updated_at: "2026-11-15T05:00:00Z",
    recipient_name: "Asha Rao",
    recipient_code: "AG-LN0001",
    maker_name: "Sana Subadmin",
    checker_name: null,
    rejected_by_name: null,
    viewer_is_maker: false,
    viewer_can_approve: true,
    simulate_events: [],
    ...overrides,
  };
}

const initiated = payout({
  status: "initiated",
  checker_user_uuid: "10000000-0000-4000-8000-000000000001",
  checker_name: "Aarav Admin",
  gateway_payout_id: "pout_sim_0123456789abcd",
  gateway_status: "queued",
  viewer_can_approve: false,
  simulate_events: ["payout.processed", "payout.failed", "payout.rejected"],
});

async function mockPayouts(page: Page) {
  await mockMobileApi(page, "admin");
  const simulated: Record<string, unknown>[] = [];
  let approved = false;
  await page.route("**/api/v1/payouts?**", (route) =>
    route.fulfill({
      json: {
        payouts: [
          approved ? initiated : payout({}),
          payout({
            id: PAID_ID,
            status: "paid",
            amount_paise: 150_000,
            type: "referral_bonus",
            recipient_name: "Ravi Kumar",
            gateway_payout_id: "pout_sim_feedfacecafe01",
            gateway_status: "processed",
            viewer_can_approve: false,
            simulate_events: ["payout.reversed"],
          }),
        ],
      },
    }),
  );
  await page.route(`**/api/v1/payouts/${PAYOUT_ID}/approve`, (route) => {
    approved = true;
    return route.fulfill({ json: initiated });
  });
  await page.route("**/api/v1/payouts/*/simulate-gateway", async (route) => {
    simulated.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      json: { ...initiated, status: "paid", simulate_events: ["payout.reversed"] },
    });
  });
  return simulated;
}

for (const viewport of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`approving opens the Razorpay test mode and posts the chosen outcome (${viewport.name})`, async ({
    page,
    baseURL,
  }, testInfo) => {
    const simulated = await mockPayouts(page);
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/dashboard/payouts", { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: "Review" }).first().click();
    await page.getByRole("button", { name: "Approve" }).click();

    const dialog = page.getByRole("dialog", { name: "Razorpay test payout" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("No real money moves.", { exact: false })).toBeVisible();
    await expect(dialog.getByText("pout_sim_0123456789abcd")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Bank reverses the payment" })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`simulator-${viewport.name}.png`) });

    await dialog.getByRole("button", { name: "Payment succeeds" }).click();
    await expect(dialog).toBeHidden();
    expect(simulated).toEqual([{ event: "payout.processed" }]);
  });
}

test("a settled test payout offers only the reversal", async ({ page, baseURL }) => {
  const simulated = await mockPayouts(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/payouts", { waitUntil: "domcontentloaded" });

  await page.getByRole("button", { name: "Test outcome" }).click();
  const dialog = page.getByRole("dialog", { name: "Razorpay test payout" });
  await expect(dialog.getByRole("button", { name: "Payment succeeds" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Bank reverses the payment" }).click();
  await expect.poll(() => simulated).toEqual([{ event: "payout.reversed" }]);
});
