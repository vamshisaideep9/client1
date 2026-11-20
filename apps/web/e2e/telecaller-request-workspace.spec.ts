import { expect, test, type Page } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: one returning client with a finished loan and a new
// one on the same lead, calls filed per application, and client history.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "60000000-0000-4000-8000-000000000001";
const OLD_APP = "61000000-0000-4000-8000-000000000001";
const NEW_APP = "61000000-0000-4000-8000-000000000002";

function application(id: string, name: string, status: string, openedAt: string) {
  return {
    id,
    loan_type_id: FIXTURE_ID,
    loan_type_name: name,
    bank_id: null,
    bank_name: "HDFC Bank",
    amount_requested: "2500000.00",
    status,
    opened_at: openedAt,
    txns: [],
  };
}

function call(id: string, notes: string, request: { kind: string; id: string } | null) {
  return {
    id,
    lead_uuid: LEAD_ID,
    disposition: "connected",
    interest_level: "warm",
    notes,
    follow_up_at: null,
    created_at: "2026-11-12T10:00:00Z",
    request,
  };
}

async function mockWorkspace(page: Page) {
  await mockMobileApi(page, "telecaller");
  const posted: unknown[] = [];
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}`, (route) =>
    route.fulfill({
      json: {
        id: LEAD_ID,
        name: "Ravi Kumar",
        mobile: "+919876543210",
        business_line: "loans",
        status: "working",
        requirement: null,
        last_disposition: "connected",
        next_follow_up_at: null,
        created_at: "2026-01-10T09:00:00Z",
        updated_at: "2026-11-13T09:00:00Z",
        latest_request: {
          kind: "loan_application",
          id: NEW_APP,
          title: "Home Loan",
          status: "submitted_to_bank",
          applied_at: "2026-11-10T05:15:00Z",
        },
        activities: [
          call("a1", "Asked about the new home loan rate", { kind: "loan_application", id: NEW_APP }),
          call("a2", "Old car loan disbursed, thanked client", {
            kind: "loan_application",
            id: OLD_APP,
          }),
          call("a3", "General catch-up call", null),
        ],
        loan_applications: [
          application(NEW_APP, "Home Loan", "submitted_to_bank", "2026-11-10T05:15:00Z"),
          application(OLD_APP, "Car Loan", "disbursed", "2026-02-01T06:00:00Z"),
        ],
        financial_enquiries: [],
        property_enquiries: [],
        site_visits: [],
        property_deals: [],
        tasks: [],
      },
    }),
  );
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}/activities`, async (route) => {
    posted.push(route.request().postDataJSON());
    await route.fulfill({ status: 201, json: call("a4", "logged", null) });
  });
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}/client-history`, (route) =>
    route.fulfill({
      json: {
        business_line: "loans",
        leads: [
          {
            lead_id: LEAD_ID,
            status: "working",
            created_at: "2026-01-10T09:00:00Z",
            requests: [
              {
                kind: "loan_application",
                id: NEW_APP,
                title: "Home Loan",
                status: "submitted_to_bank",
                applied_at: "2026-11-10T05:15:00Z",
              },
            ],
            activities: [call("a1", "Asked about the new home loan rate", null)],
          },
          {
            lead_id: "60000000-0000-4000-8000-000000000009",
            status: "closed",
            created_at: "2025-06-01T09:00:00Z",
            requests: [],
            activities: [call("h1", "Earlier journey: client not interested then", null)],
          },
        ],
      },
    }),
  );
  return posted;
}

async function openLead(page: Page, baseURL: string, width = 1440) {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });
}

test("a returning client's applications are worked separately", async ({ page, baseURL }) => {
  const posted = await mockWorkspace(page);
  await openLead(page, baseURL!);

  const list = page.getByRole("region", { name: "Applications & requests" }).or(
    page.locator("section", { has: page.getByRole("heading", { name: "Applications & requests" }) }),
  );
  const current = list.getByRole("button", { name: /Home Loan/ });
  await expect(current).toHaveAttribute("aria-pressed", "true");
  await expect(current).toContainText("Applied");
  await expect(current).toContainText("2026");

  // The finished loan is folded away and its calls are not mixed in.
  await expect(list.getByText("Previous applications (1)")).toBeVisible();
  const calls = page.locator("section", { has: page.getByRole("heading", { name: "Calls about this request" }) });
  await expect(calls.getByText("Asked about the new home loan rate")).toBeVisible();
  await expect(calls.getByText("Old car loan disbursed, thanked client")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Car Loan" })).toHaveCount(0);

  await list.getByText("Previous applications (1)").click();
  await list.getByRole("button", { name: /Car Loan/ }).click();
  await expect(calls.getByText("Old car loan disbursed, thanked client")).toBeVisible();
  await expect(calls.getByText("Asked about the new home loan rate")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Car Loan" })).toBeVisible();

  // A new call defaults to the application being worked on.
  await expect(page.locator("#lead-call-about")).toContainText("Car Loan");
  await page.locator("#lead-call-disposition").click();
  await page.getByRole("option", { name: "Busy" }).click();
  await page.getByRole("button", { name: "Log call" }).click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toMatchObject({ disposition: "busy", request: { kind: "loan_application", id: OLD_APP } });
});

test("full-screen call log filters by application and general calls", async ({ page, baseURL }, testInfo) => {
  await mockWorkspace(page);
  await openLead(page, baseURL!);

  await page.getByRole("button", { name: "Full call log" }).click();
  const dialog = page.getByRole("dialog", { name: "Call log" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: /All calls/ }).click();
  await expect(dialog.getByText("General catch-up call")).toBeVisible();
  await expect(dialog.getByText("Old car loan disbursed, thanked client")).toBeVisible();
  await dialog.getByRole("radio", { name: /General/ }).click();
  await expect(dialog.getByText("General catch-up call")).toBeVisible();
  await expect(dialog.getByText("Asked about the new home loan rate")).toHaveCount(0);
  const box = (await dialog.boundingBox())!;
  expect(box.width).toBeGreaterThan(1300);
  await page.screenshot({ path: testInfo.outputPath("call-log-full.png") });
});

test("client history shows every journey with this telecaller", async ({ page, baseURL }) => {
  await mockWorkspace(page);
  await openLead(page, baseURL!);

  await page.getByRole("button", { name: "Client history" }).click();
  const dialog = page.getByRole("dialog", { name: /client history/ });
  await expect(dialog.getByRole("heading", { name: "Current journey" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Earlier journey 1" })).toBeVisible();
  await expect(dialog.getByText("Earlier journey: client not interested then")).toBeVisible();
});

test("the workspace fits a 360px phone", async ({ page, baseURL }, testInfo) => {
  await mockWorkspace(page);
  await openLead(page, baseURL!, 360);
  await expect(page.getByRole("button", { name: /Home Loan/ })).toBeVisible();
  // The call form says which application the call will be filed against.
  await expect(page.locator("#lead-call-about")).toContainText("Home Loan");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("workspace-360.png"), fullPage: true });
});
