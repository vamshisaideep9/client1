import { expect, test, type Page } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. A product specialist's home shows their product
// chip, a "My product" panel and the products that reached them by fallback;
// their lead and task lists start on their own product ("My product"), and
// clearing that chip keeps the full list.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(150_000);

const HOME_LOAN = "71000000-0000-4000-8000-000000000001";
const CARD = "71000000-0000-4000-8000-000000000002";
const INSURANCE = "71000000-0000-4000-8000-000000000003";

function profile(role: "telecaller" | "employee", specialty: { id: string; label: string } | null) {
  return {
    profile_uuid: FIXTURE_ID,
    role,
    code: role === "telecaller" ? "TC-001" : "EMP-001",
    business_line: "both",
    loan_specialty_id: specialty?.id ?? null,
    loan_specialty_label: specialty?.label ?? null,
    teams: [],
  };
}

async function setup(page: Page, baseURL: string, role: "telecaller" | "employee", specialty: { id: string; label: string } | null) {
  await mockMobileApi(page, role, "loans");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        first_name: "Asha", last_name: "Specialist", mobile: "+919876543210", email: "asha@example.test",
        email_verified: true, profiles: [], role_profiles: [profile(role, specialty)],
      },
    }),
  );
}

function lead(id: string, name: string, product: { id: string; label: string } | null) {
  return {
    id, lead_ref: `LD-0000030${id.slice(-1)}`, name, mobile: "+919876543210", business_line: "loans",
    status: "working", requirement: null, last_disposition: null, last_interest_level: null,
    next_follow_up_at: null, created_at: "2026-11-20T04:00:00Z", updated_at: "2026-11-25T08:45:00Z",
    latest_request: null, loan_statuses: [], referrer: null,
    product_id: product?.id ?? null, product_label: product?.label ?? null,
  };
}

const LEADS = [
  lead("72000000-0000-4000-8000-000000000001", "Home Applicant", { id: HOME_LOAN, label: "Home Loan" }),
  lead("72000000-0000-4000-8000-000000000002", "Home Enquiry", { id: HOME_LOAN, label: "Home Loan" }),
  lead("72000000-0000-4000-8000-000000000003", "Card Prospect", { id: CARD, label: "Platinum Card" }),
];

const TELECALLER_HOME = {
  follow_ups_due: [],
  counts_by_status: { working: 3 },
  specialty: { product_id: HOME_LOAN, label: "Home Loan", category: "loan", active: true },
  product_counts: [
    { product_id: HOME_LOAN, label: "Home Loan", category: "loan", open: 2, overdue: 1, converted_30d: 4 },
    { product_id: CARD, label: "Platinum Card", category: "credit_card", open: 1, overdue: 0, converted_30d: 0 },
  ],
};

const rows = (page: Page) => page.locator("tbody tr");

for (const width of [390, 1440]) {
  test(`Telecaller specialist home and defaulted lead list at ${width}px`, async ({ page, baseURL }, info) => {
    await setup(page, baseURL!, "telecaller", { id: HOME_LOAN, label: "Home Loan" });
    await page.route("**/api/v1/telecaller/home", (route) => route.fulfill({ json: TELECALLER_HOME }));
    await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: LEADS }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

    await expect(page.getByText("Home Loan specialist", { exact: true })).toBeVisible({ timeout: 60_000 });
    const mine = page.locator("section").filter({ has: page.getByRole("heading", { name: "My product" }) });
    await expect(mine).toContainText("Open leads");
    await expect(mine).toContainText("Follow-ups overdue");
    await expect(mine).toContainText("Converted (30 days)");
    const others = page.locator("section").filter({ has: page.getByRole("heading", { name: "Other products" }) });
    await expect(others).toContainText("Platinum Card");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`telecaller-specialist-home-${width}.png`), fullPage: true });

    await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });
    await expect(rows(page)).toHaveCount(2, { timeout: 60_000 });
    await expect(rows(page).filter({ hasText: "Card Prospect" })).toHaveCount(0);
    const chip = page.getByRole("button", { name: "Remove filter My product: Home Loan" });
    await expect(chip).toBeVisible();
    await page.screenshot({ path: info.outputPath(`telecaller-my-product-list-${width}.png`), fullPage: true });
    await chip.click();
    await expect(rows(page)).toHaveCount(3);
    // Not sticky: the default does not come back once cleared.
    await expect(page.getByRole("button", { name: /^Remove filter My product/ })).toHaveCount(0);
  });
}

test("a home link opens the list on another product", async ({ page, baseURL }) => {
  await setup(page, baseURL!, "telecaller", { id: HOME_LOAN, label: "Home Loan" });
  await page.route("**/api/v1/telecaller/home", (route) => route.fulfill({ json: TELECALLER_HOME }));
  await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: LEADS }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const link = page.getByRole("link", { name: "Platinum Card", exact: true });
  await expect(link).toHaveAttribute("href", `/dashboard/leads?product=${CARD}`, { timeout: 60_000 });
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/dashboard/leads\\?product=${CARD}`), { timeout: 60_000 });
  await expect(rows(page)).toHaveCount(1, { timeout: 60_000 });
  await expect(rows(page).first()).toContainText("Card Prospect");
  await expect(page.getByRole("button", { name: "Remove filter Product: Platinum Card" })).toBeVisible();
});

test("an unspecialised Telecaller sees only the product breakdown", async ({ page, baseURL }) => {
  await setup(page, baseURL!, "telecaller", null);
  await page.route("**/api/v1/telecaller/home", (route) =>
    route.fulfill({ json: { ...TELECALLER_HOME, specialty: null } }),
  );
  await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: LEADS }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Work by product" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My product" })).toHaveCount(0);
  await expect(page.getByText(/specialist$/)).toHaveCount(0);
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });
  await expect(rows(page)).toHaveCount(3);
});

test("Officer specialist home and defaulted task list", async ({ page, baseURL }, info) => {
  await setup(page, baseURL!, "employee", { id: INSURANCE, label: "Term Insurance" });
  const task = (id: string, name: string, product: string | null, label: string | null) => ({
    id, lead_uuid: id.replace("73", "74"), lead_name: name, lead_mobile: null, lead_contact_mode: "deny",
    business_line: "loans", task_type: "document_collection", status: "assigned", outcome: null, notes: null,
    due_at: null, created_at: "2026-11-25T04:00:00Z", updated_at: "2026-11-25T04:00:00Z",
    product_id: product, product_label: label,
  });
  const tasks = [
    task("73000000-0000-4000-8000-000000000001", "Insured Client", INSURANCE, "Term Insurance"),
    task("73000000-0000-4000-8000-000000000002", "Loan Client", HOME_LOAN, "Home Loan"),
  ];
  await page.route("**/api/v1/employee/tasks", (route) => route.fulfill({ json: tasks }));
  await page.route("**/api/v1/employee/home", (route) =>
    route.fulfill({
      json: {
        tasks_today: [], overdue_count: 0, counts_by_type: {}, counts_by_status: { assigned: 2 },
        specialty: { product_id: INSURANCE, label: "Term Insurance", category: "insurance", active: true },
        product_counts: [
          { product_id: INSURANCE, label: "Term Insurance", category: "insurance", open: 1, overdue: 0, completed_30d: 2 },
          { product_id: HOME_LOAN, label: "Home Loan", category: "loan", open: 1, overdue: 1, completed_30d: 0 },
        ],
      },
    }),
  );
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Term Insurance specialist", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "My product" })).toBeVisible();
  await expect(page.getByText("Completed (30 days)")).toBeVisible();
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: "Other products" }) })).toContainText("Home Loan");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("officer-specialist-home-390.png"), fullPage: true });

  await page.goto("/dashboard/tasks", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Insured Client").first()).toBeVisible();
  await expect(page.getByText("Loan Client")).toHaveCount(0);
  await page.getByRole("button", { name: "Remove filter My product: Term Insurance" }).click();
  await expect(page.getByText("Loan Client").first()).toBeVisible();
});
