import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

const AGENT = "40000000-0000-4000-8000-000000000001";
const TXN_ID = "50000000-0000-4000-8000-000000000001";
const GROUP = {
  agent_profile_uuid: AGENT,
  business_line: "loans",
  agent_name: "Asha Rao",
  agent_code: "AG-LN0001",
  pending_count: 2,
  pending_amount_paise: 125_000,
};

async function session(page: Page, baseURL: string | undefined, role: "admin" | "client") {
  await mockMobileApi(page, role);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
}

test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

test("Admin selects a single Agent group and retries a payout with both commissions", async ({ page, baseURL }, testInfo) => {
  await session(page, baseURL, "admin");
  await page.setViewportSize({ width: 390, height: 844 });
  const selection = [1, 2].map((number) => ({
    id: `41000000-0000-4000-8000-00000000000${number}`,
    deal_uuid: `42000000-0000-4000-8000-00000000000${number}`,
    deal_type: "loan_application",
    lead_ref: `LD-0000010${number}`,
    agent_profile_uuid: AGENT,
    agent_name: GROUP.agent_name,
    agent_code: GROUP.agent_code,
    business_line: "loans",
    agreed_amount_paise: number === 1 ? 50_000 : 75_000,
    created_at: "2026-11-20T07:00:00Z",
    updated_at: "2026-11-20T07:00:00Z",
    status: "pending",
    payout_uuid: null,
    notes: null,
    cancelled_reason: null,
  }));
  const requests: unknown[] = [];
  let paid = false;
  await page.route("**/api/v1/admin/commissions/eligible?**", (route) =>
    route.fulfill({ json: { deals: [], total: 0 } }),
  );
  await page.route("**/api/v1/admin/commissions/pending-payout-groups?**", (route) =>
    route.fulfill({ json: { groups: paid ? [] : [GROUP], total: paid ? 0 : 1 } }),
  );
  await page.route("**/api/v1/admin/commissions?**", (route) =>
    route.fulfill({ json: { commissions: paid ? [] : selection, total: paid ? 0 : selection.length } }),
  );
  await page.route("**/api/v1/admin/commissions/bulk-payout", (route) => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) return route.fulfill({ status: 503, json: { detail: "Try again." } });
    paid = true;
    return route.fulfill({ status: 201, json: { payout_id: TXN_ID } });
  });

  await page.goto("/dashboard/commissions", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Pay pending commissions" }).click();
  await expect(page.getByText("2 pending", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Select commissions for Asha Rao" }).click();
  await expect(page.getByText("LD-00000102", { exact: true })).toBeVisible();
  const checks = page.getByRole("checkbox", { name: /Loan commission/ });
  await checks.nth(0).check();
  await checks.nth(1).check();
  await expect(page.getByText("2 selected · ₹1,250", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Review payout" }).click();
  const dialog = page.getByRole("dialog", { name: /Review payout/ });
  await dialog.getByText("Covered commissions", { exact: true }).click();
  await expect(dialog.getByText("₹750", { exact: true })).toBeVisible();
  await dialog.getByRole("radio", { name: "Cheque" }).check();
  await dialog.getByRole("button", { name: "Raise payout" }).click();
  await expect(page.getByText("Could not raise the payout")).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "Cheque" })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath("bulk-payout-review-390.png") });
  await dialog.getByRole("button", { name: "Raise payout" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("No pending payouts", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  expect(requests[0]).toMatchObject({
    commission_ids: selection.map((row) => row.id),
    destination_type: "cheque",
  });
});

test("Client sees filtered server totals and a masked reversal timeline", async ({ page, baseURL }, testInfo) => {
  await session(page, baseURL, "client");
  await page.setViewportSize({ width: 768, height: 900 });
  const txn = {
    id: TXN_ID,
    type: "cashback",
    status: "paid",
    amount_paise: 50_000,
    currency: "INR",
    description: "Fee cashback",
    created_at: "2026-11-18T07:00:00Z",
  };
  const searches: URLSearchParams[] = [];
  await page.route("**/api/v1/transactions/search?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    searches.push(params);
    return route.fulfill({ json: {
      transactions: [txn],
      total: params.get("q") ? 1 : 27,
      paid_amount_paise: 0,
      processing_count: 0,
      referral_count: 0,
    } });
  });
  await page.route(`**/api/v1/transactions/${TXN_ID}`, (route) => route.fulfill({ json: {
    ...txn,
    display_id: `TXN-${TXN_ID}`,
    payment: {
      status: "reversed",
      method: "bank_account",
      destination_hint: "HDFC0000001 · ******1234",
      reference: "pout_Synthetic123",
      requested_at: "2026-11-16T07:00:00Z",
      approved_at: "2026-11-17T07:00:00Z",
      issued_at: null,
      paid_at: txn.created_at,
      reversed_at: "2026-11-19T07:00:00Z",
    },
  } }));

  await page.goto("/dashboard/transactions", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Showing 1-25 of 27", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect.poll(() => searches.at(-1)?.get("offset")).toBe("25");
  await page.getByRole("textbox", { name: "Search transactions" }).fill("Fee cashback");
  await expect.poll(() => searches.at(-1)?.get("q")).toBe("Fee cashback");
  await expect(page.getByText("Showing 1-1 of 1", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /Fee cashback.*view payment details/ }).click();
  const sheet = page.getByRole("dialog", { name: "Transaction details" });
  await expect(sheet.getByText("The original payment was reversed.", { exact: false })).toBeVisible();
  await expect(sheet.getByText("pout_Synthetic123")).toBeVisible();
  await expect(sheet.getByText(/\*{6}1234/)).toBeVisible();
  await expect(sheet.getByText(`TXN-${TXN_ID}`)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
  await page.screenshot({ path: testInfo.outputPath("client-reversal-768.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: /Fee cashback.*view payment details/ })).toBeFocused();
});
