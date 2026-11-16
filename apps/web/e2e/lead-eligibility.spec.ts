import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. CS-024: lead eligibility on the Agent Leads page and
// referral eligibility on the Client Referrals page — summary, Eligibility
// filter and badge, and the "Not accepted" tab of recorded attempts.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const HOME = "81000000-0000-4000-8000-000000000001";
const HDFC = "82000000-0000-4000-8000-000000000001";

function agentLead(id: string, name: string, patch: Record<string, unknown> = {}) {
  return {
    id,
    name,
    mobile: "+919812300000",
    business_line: "loans",
    status: "assigned",
    requirement: null,
    registered: false,
    editable: true,
    resubmittable: false,
    expires_at: "2026-12-10T00:00:00Z",
    expired_at: null,
    created_at: "2026-11-10T00:00:00Z",
    updated_at: "2026-11-10T00:00:00Z",
    eligibility: "eligible",
    eligibility_reason: null,
    eligibility_reason_label: null,
    facets: { loans: [], deals: [] },
    ...patch,
  };
}

const AGENT_LEADS = [
  agentLead("83000000-0000-4000-8000-000000000001", "Asha Verma", {
    mobile: "+919812300001",
    facets: {
      loans: [{ loan_type_id: HOME, loan_type_label: "Home Loan", bank_id: HDFC, bank_name: "HDFC Bank", status: "sanctioned" }],
      deals: [],
    },
  }),
  agentLead("83000000-0000-4000-8000-000000000002", "Bala Iyer", {
    mobile: "+919812300002",
    status: "expired",
    editable: false,
    expires_at: "2026-10-01T00:00:00Z",
    expired_at: "2026-10-01T00:15:00Z",
    eligibility: "not_eligible",
    eligibility_reason: "attribution_expired",
    eligibility_reason_label: "Your 30-day window ended",
  }),
  agentLead("83000000-0000-4000-8000-000000000003", "Chitra Rao", { mobile: "+919812300003", status: "new" }),
];

const AGENT_ATTEMPTS = {
  total: 2,
  attempts: [
    {
      id: "84000000-0000-4000-8000-000000000001",
      outcome: "duplicate",
      reason: "already_linked",
      reason_label: "Already registered or linked to an existing enquiry",
      mobile_masked: "***4321",
      business_line: "loans",
      created_at: "2026-11-16T09:30:00Z",
    },
    {
      id: "84000000-0000-4000-8000-000000000002",
      outcome: "not_eligible",
      reason: "own_lead_window_ended",
      reason_label: "Your earlier lead for this number expired",
      mobile_masked: "***8765",
      business_line: "loans",
      created_at: "2026-11-15T09:30:00Z",
    },
  ],
};

async function openAgentLeads(page: Page, baseURL: string) {
  await mockMobileApi(page, "agent", "loans");
  await page.route((url) => url.pathname === "/api/v1/agent/leads", (route) => route.fulfill({ json: AGENT_LEADS }));
  await page.route(
    (url) => url.pathname === "/api/v1/agent/lead-eligibility",
    (route) => route.fulfill({ json: { eligible: 2, not_eligible: 2, duplicate: 1, not_accepted: 2 } }),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/agent/lead-attempts",
    (route) => route.fulfill({ json: AGENT_ATTEMPTS }),
  );
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Leads", exact: true })).toBeVisible();
}

async function pick(page: Page, scope: Page | ReturnType<Page["getByRole"]>, field: string, option: string) {
  await scope.getByRole("combobox", { name: `Filter by ${field}` }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

const leadRows = (page: Page) => page.getByRole("table", { name: "Introduced leads" }).locator("tbody tr");

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("agent leads show eligibility, filter by it and list numbers not accepted", async ({ page, baseURL }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openAgentLeads(page, baseURL!);

  const summary = page.getByRole("region", { name: "Eligibility summary" });
  await expect(summary).toContainText("Eligible");
  await expect(summary).toContainText("Accepted and counted for you");
  await expect(summary).toContainText("1 lead · 1 not accepted");
  await expect(summary).toContainText("Already registered or linked");

  await expect(leadRows(page)).toHaveCount(3);
  const expired = leadRows(page).filter({ hasText: "Bala Iyer" });
  await expect(expired).toContainText("Not eligible");
  await expect(expired).toContainText("Your 30-day window ended");
  await expect(leadRows(page).filter({ hasText: "Asha Verma" })).toContainText("Eligible");
  await page.screenshot({ path: testInfo.outputPath("agent-leads-eligibility.png"), fullPage: true });

  await pick(page, page, "eligibility", "Not eligible");
  await expect(leadRows(page)).toHaveCount(1);
  await expect(leadRows(page).first()).toContainText("Bala Iyer");
  await page.getByRole("button", { name: "Remove filter Eligibility: Not eligible" }).click();
  await expect(leadRows(page)).toHaveCount(3);

  // Batch C product filters, without the Telecaller-only Lead group.
  await page.getByRole("button", { name: "More filters" }).click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  await expect(dialog.getByRole("group", { name: "Product" })).toBeVisible();
  await expect(dialog.getByRole("group", { name: "Lead" })).toHaveCount(0);
  await pick(page, dialog, "product", "Home Loan");
  await page.keyboard.press("Escape");
  await expect(leadRows(page)).toHaveCount(1);
  await expect(leadRows(page).first()).toContainText("Asha Verma");
  await pick(page, page, "status", "New");
  await expect(page.getByText("No leads match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(leadRows(page)).toHaveCount(3);

  await page.getByRole("tab", { name: "Not accepted (2)" }).click();
  const attempts = page.getByRole("table", { name: "Leads not accepted" }).locator("tbody tr");
  await expect(attempts).toHaveCount(2);
  await expect(attempts.first()).toContainText("***4321");
  await expect(attempts.first()).toContainText("Duplicate");
  await expect(attempts.first()).toContainText("Already registered or linked to an existing enquiry");
  await pick(page, page, "eligibility", "Not eligible");
  await expect(attempts).toHaveCount(1);
  await expect(attempts.first()).toContainText("***8765");
  await expect(attempts.first()).toContainText("Your earlier lead for this number expired");
  await page.screenshot({ path: testInfo.outputPath("agent-leads-not-accepted.png"), fullPage: true });
});

test("agent eligibility fits a 390 px phone in dark mode", async ({ page, baseURL }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 390, height: 844 });
  await openAgentLeads(page, baseURL!);

  await expect(page.getByRole("region", { name: "Eligibility summary" })).toBeVisible();
  await expect(leadRows(page).filter({ hasText: "Bala Iyer" })).toContainText("Your 30-day window ended");
  await expectNoPageOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("agent-leads-eligibility-390.png"), fullPage: true });

  await page.getByRole("tab", { name: "Not accepted (2)" }).click();
  const attempts = page.getByRole("table", { name: "Leads not accepted" }).locator("tbody tr");
  // On phones the reason and date sit under the number and badge.
  await expect(attempts.first()).toContainText("Already registered or linked to an existing enquiry");
  await expectNoPageOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("agent-leads-not-accepted-390.png"), fullPage: true });
});

function referral(id: string, patch: Record<string, unknown>) {
  return {
    id,
    referred_mobile_masked: "***1111",
    business_line: null,
    conversion_status: "pending",
    bonus_amount_paise: null,
    converted_at: null,
    created_at: "2026-11-10T00:00:00Z",
    converted_item: null,
    eligibility: "eligible",
    eligibility_reason: null,
    eligibility_reason_label: null,
    ...patch,
  };
}

async function openReferrals(page: Page, baseURL: string) {
  await mockMobileApi(page, "client");
  await page.route(
    (url) => url.pathname === "/api/v1/referrals/me",
    (route) =>
      route.fulfill({
        json: {
          code: "AB12CD34",
          eligible: true,
          ineligible_reason: null,
          stats: { total: 3, pending: 1, converted: 1, accrued: 1, paid: 0, void: 0, accrued_amount_paise: 50000, paid_amount_paise: 0 },
        },
      }),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/referrals",
    (route) =>
      route.fulfill({
        json: {
          referrals: [
            referral("85000000-0000-4000-8000-000000000001", { referred_mobile_masked: "***1111" }),
            referral("85000000-0000-4000-8000-000000000002", {
              referred_mobile_masked: "***2222",
              business_line: "loans",
              conversion_status: "converted",
              converted_at: "2026-11-12T00:00:00Z",
              eligibility: "not_eligible",
              eligibility_reason: "cap_reached",
              eligibility_reason_label: "Bonus limit reached",
            }),
            referral("85000000-0000-4000-8000-000000000003", {
              referred_mobile_masked: "***3333",
              business_line: "loans",
              conversion_status: "accrued",
              bonus_amount_paise: 50000,
              converted_at: "2026-11-13T00:00:00Z",
            }),
          ],
        },
      }),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/referrals/eligibility",
    (route) => route.fulfill({ json: { eligible: 2, not_eligible: 1, duplicate: 1, not_accepted: 1 } }),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/referrals/attempts",
    (route) =>
      route.fulfill({
        json: {
          total: 1,
          attempts: [
            {
              id: "86000000-0000-4000-8000-000000000001",
              outcome: "duplicate",
              reason: "already_referred",
              reason_label: "This person was already referred",
              mobile_masked: "***5555",
              business_line: null,
              created_at: "2026-11-16T10:00:00Z",
            },
          ],
        },
      }),
  );
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.goto("/dashboard/referrals", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Referrals", exact: true })).toBeVisible();
}

for (const width of [1440, 390]) {
  test(`client referrals show eligibility and sign-ups not accepted (${width} px)`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
    await openReferrals(page, baseURL!);

    const summary = page.getByRole("region", { name: "Eligibility summary" });
    await expect(summary).toContainText("Can earn or earned a bonus");
    await expect(summary).toContainText("1 referral");
    await expect(summary).toContainText("Already referred by someone else");

    const rows = page.locator("table tbody tr");
    await expect(rows).toHaveCount(3);
    await expect(rows.filter({ hasText: "***2222" })).toContainText("Not eligible");
    await expect(rows.filter({ hasText: "***2222" })).toContainText("Bonus limit reached");
    await pick(page, page, "eligibility", "Not eligible");
    await expect(rows).toHaveCount(1);
    await pick(page, page, "eligibility", "Eligible");
    await expect(rows).toHaveCount(2);
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`client-referrals-eligibility-${width}.png`), fullPage: true });

    await page.getByRole("tab", { name: "Not accepted (1)" }).click();
    const attempts = page.getByRole("table", { name: "Referrals not accepted" }).locator("tbody tr");
    await expect(attempts).toHaveCount(1);
    await expect(attempts.first()).toContainText("***5555");
    await expect(attempts.first()).toContainText("Duplicate");
    await expect(attempts.first()).toContainText("This person was already referred");
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`client-referrals-not-accepted-${width}.png`), fullPage: true });
  });
}
