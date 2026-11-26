import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Admin's Products & staffing index, the per-product
// dashboard, the Team Manager's scoped product index, and the Telecaller
// redirect. The API derives every scope; these mocks stand in for it.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(150_000);

const HOME_LOAN = "81000000-0000-4000-8000-000000000001";
const CARD = "81000000-0000-4000-8000-000000000002";
const INSURANCE = "81000000-0000-4000-8000-000000000003";

function person(first: string, role: "telecaller" | "employee", id: string) {
  return {
    staff_profile_uuid: `82000000-0000-4000-8000-00000000000${id}`,
    auth_user_uuid: `83000000-0000-4000-8000-00000000000${id}`,
    first_name: first, last_name: "Synthetic", staff_code: `${role === "telecaller" ? "TC" : "EMP"}-00${id}`,
    role, business_line: "loans", status: "active",
  };
}

const STAFFING = {
  products: [
    {
      product_id: HOME_LOAN, label: "Home Loan", category: "loan", active: true,
      telecallers: [person("Asha", "telecaller", "1")], officers: [person("Omar", "employee", "2")],
      open_leads: 12, unassigned_leads: 0, open_tasks: 3, coverage: "full",
    },
    {
      product_id: CARD, label: "Platinum Card", category: "credit_card", active: true,
      telecallers: [person("Cara", "telecaller", "3")], officers: [],
      open_leads: 5, unassigned_leads: 2, open_tasks: 1, coverage: "no_officer",
    },
    {
      product_id: INSURANCE, label: "Term Insurance", category: "insurance", active: true,
      telecallers: [], officers: [], open_leads: 4, unassigned_leads: 4, open_tasks: 0, coverage: "none",
    },
  ],
  summary: {
    products: 3, active_products: 3, fully_covered: 1, open_leads: 21, unassigned_leads: 6, open_tasks: 4,
    unspecialised: [{ business_line: "loans", telecallers: 2, officers: 1 }],
  },
  available: [person("Free", "telecaller", "4"), person("Field", "employee", "5")],
};

const DASHBOARD = {
  product: { product_id: HOME_LOAN, label: "Home Loan", category: "loan", active: true },
  scope: "platform", date_from: "2026-10-28", date_to: "2026-11-26", range_days: 30,
  leads: { captured: 20, open: 12, converted: 5, conversion_rate: 15, served_by_fallback: 3, unassigned: 1 },
  tasks: { open: 3, completed: 7, on_time_rate: 85.7 },
  requests_kind: "applications",
  requests_by_status: [{ status: "new", count: 6 }, { status: "sanctioned", count: 2 }],
  trend: [
    { week_start: "2026-10-28", captured: 3, converted: 0 },
    { week_start: "2026-11-02", captured: 6, converted: 2 },
    { week_start: "2026-11-09", captured: 4, converted: 1 },
    { week_start: "2026-11-16", captured: 5, converted: 2 },
    { week_start: "2026-11-23", captured: 2, converted: 0 },
  ],
  staff: [
    { ...person("Asha", "telecaller", "1"), specialist: true, assigned: 10, contacted: 8, converted: 4, open_tasks: 0, completed_tasks: 0 },
    { ...person("Omar", "employee", "2"), specialist: true, assigned: 0, contacted: 0, converted: 0, open_tasks: 3, completed_tasks: 7 },
    { ...person("Bala", "telecaller", "6"), specialist: false, assigned: 2, contacted: 1, converted: 1, open_tasks: 0, completed_tasks: 0 },
  ],
};

async function signIn(page: Page, baseURL: string, role: "admin" | "sub_admin" | "telecaller", me?: Record<string, unknown>) {
  await mockMobileApi(page, role, "loans");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  if (me) {
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({ json: { first_name: "Mobile", last_name: "Reviewer", email: "reviewer@example.test", email_verified: true, profiles: [], ...me } }),
    );
  }
}

for (const width of [390, 1440]) {
  test(`Admin product staffing shows coverage and prefilled create links at ${width}px`, async ({ page, baseURL }, info) => {
    await signIn(page, baseURL!, "admin");
    await page.route("**/api/v1/admin/product-staffing", (route) => route.fulfill({ json: STAFFING }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/products", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { level: 1, name: "Products & staffing" })).toBeVisible({ timeout: 60_000 });
    for (const flag of ["Fully staffed", "No Officer", "No specialists"]) {
      await expect(page.getByText(flag, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("1 of 3", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`product-staffing-${width}.png`), fullPage: true });

    const addOfficer = page.getByRole("link", { name: "Add Officer" }).nth(1);
    await expect(addOfficer).toHaveAttribute("href", `/dashboard/users?role=employee&product=${CARD}`);
  });
}

test("Admin assigns an existing Officer and filters by coverage", async ({ page, baseURL }) => {
  await signIn(page, baseURL!, "admin");
  await page.route("**/api/v1/admin/product-staffing", (route) => route.fulfill({ json: STAFFING }));
  let body: unknown;
  await page.route("**/api/v1/admin/users/*/loan-specialty", async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard/products", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Products & staffing" })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("combobox", { name: "Filter by coverage" }).click();
  await page.getByRole("option", { name: "No Officer", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "Assign existing" }).click();
  const dialog = page.getByRole("dialog", { name: "Assign a specialist" });
  await expect(dialog.getByLabel("Role")).toContainText("Officer");
  await dialog.getByLabel("Officer", { exact: true }).click();
  await page.getByRole("option", { name: "Field Synthetic · EMP-005" }).click();
  await dialog.getByRole("button", { name: "Assign specialist" }).click();
  await expect.poll(() => body).toEqual({ loan_specialty_id: CARD });
  await expect(page.getByRole("dialog", { name: "Assign a specialist" })).toHaveCount(0);
});

test("the per-product dashboard renders KPIs, the trend and the staff table", async ({ page, baseURL }, info) => {
  await signIn(page, baseURL!, "admin");
  let days = "";
  await page.route(`**/api/v1/products/${HOME_LOAN}/dashboard**`, (route) => {
    days = new URL(route.request().url()).searchParams.get("days") ?? "";
    return route.fulfill({ json: DASHBOARD });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/dashboard/products/${HOME_LOAN}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Home Loan" })).toBeVisible({ timeout: 60_000 });
  expect(days).toBe("30");
  for (const label of ["Leads captured", "Conversion rate", "Served by fallback", "Unassigned leads", "Tasks on time"]) {
    // Attention cards append a screen-reader suffix to their label.
    await expect(page.getByText(new RegExp(`^${label}`)).first()).toBeVisible();
  }
  await expect(page.getByText("15%", { exact: true })).toBeVisible();
  await expect(page.getByText("85.7%", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Applications by stage" })).toBeVisible();
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Leads captured and converted" })).toBeVisible();
  await page.getByText("Show as table").click();
  await expect(page.getByRole("table", { name: "Leads captured and converted" })).toBeVisible();
  const people = page.locator("section").filter({ has: page.getByRole("heading", { name: "People" }) });
  await expect(people).toContainText("Asha Synthetic");
  await expect(people).toContainText("Fallback");
  await page.screenshot({ path: info.outputPath("product-dashboard-1440.png"), fullPage: true });

  await page.getByRole("combobox", { name: "Period" }).click();
  await page.getByRole("option", { name: "Last 90 days" }).click();
  await expect.poll(() => days).toBe("90");

  await page.setViewportSize({ width: 390, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("product-dashboard-390.png"), fullPage: true });
});

test("an unknown product shows a not-found state", async ({ page, baseURL }) => {
  await signIn(page, baseURL!, "admin");
  await page.route(`**/api/v1/products/${INSURANCE}/dashboard**`, (route) =>
    route.fulfill({ status: 404, json: { detail: "Product not found." } }),
  );
  await page.goto(`/dashboard/products/${INSURANCE}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Product not found", { exact: true })).toBeVisible({ timeout: 60_000 });
});

test("a Team Manager sees the scoped product index and team dashboard", async ({ page, baseURL }) => {
  await signIn(page, baseURL!, "sub_admin", {
    sub_admin_access: { status: "active", version: 1, grants: [{ assignment: "team_manager", business_line: "loans", actions: ["view"] }] },
  });
  await page.route("**/api/v1/manager/products", (route) =>
    route.fulfill({ json: { products: [{ product_id: HOME_LOAN, label: "Home Loan", category: "loan", active: true, specialists: 2, open_leads: 4, open_tasks: 1 }] } }),
  );
  await page.route(`**/api/v1/products/${HOME_LOAN}/dashboard**`, (route) =>
    route.fulfill({ json: { ...DASHBOARD, scope: "team", leads: { ...DASHBOARD.leads, unassigned: 0 } } }),
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/products", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Products" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Assign existing")).toHaveCount(0);
  await page.getByText("Home Loan", { exact: true }).first().click();
  await expect(page).toHaveURL(new RegExp(`/dashboard/products/${HOME_LOAN}$`));
  await expect(page.getByText("Your teams", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Unassigned leads", { exact: true })).toHaveCount(0);
});

test("a Telecaller is sent away from the Products area", async ({ page, baseURL }) => {
  await signIn(page, baseURL!, "telecaller");
  await page.goto("/dashboard/products", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 });
  await page.goto(`/dashboard/products/${HOME_LOAN}`, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 });
});
