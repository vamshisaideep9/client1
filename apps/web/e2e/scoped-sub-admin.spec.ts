import { expect, test } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

test.use({ viewport: { width: 390, height: 844 }, contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

test("a scoped Sub Admin can open assigned Agent work and is redirected from an ungranted module", async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "sub_admin");
  await page.route("**/api/v1/auth/me", async (route) => route.fulfill({ json: {
    first_name: "Scope", last_name: "Reviewer", email: "reviewer@example.test",
    email_verified: true, profiles: [], sub_admin_access: {
      status: "active", version: 1, grants: [{
        assignment: "relationship_manager", business_line: "loans", actions: ["view", "follow_up"], agent_profile_ids: [FIXTURE_ID],
      }],
    },
  } }));
  await page.route("**/api/v1/relationships", async (route) => route.fulfill({ json: [
    { id: FIXTURE_ID, name: "Assigned Agent", agent_code: "A-1000", business_line: "loans", status: "active", kyc_status: "verified", approved_at: null, submitted_leads: 2 },
  ] }));
  await page.route("**/api/v1/relationships/*/activity", async (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: [] });
    const entry = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { ...entry, id: FIXTURE_ID, created_at: "2026-11-21T09:00:00Z" } });
  });

  await page.goto("/dashboard/banners");
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 25_000 });
  await expect(page.getByRole("link", { name: /Relationship Manager/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Account Manager/ })).toHaveCount(0);
  await page.getByRole("link", { name: /Relationship Manager/ }).click();
  await page.getByRole("button", { name: /Assigned Agent/ }).click();
  await page.getByLabel("Note").fill("Follow up on onboarding progress.");
  await page.getByRole("button", { name: "Save activity" }).click();
  await expect(page.getByText("Follow up on onboarding progress.", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
});

test("Main Admin can preview and save independent module grants", async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await context.addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "admin");
  const entry = {
    staff_profile_uuid: FIXTURE_ID, first_name: "Pending", last_name: "Reviewer",
    staff_code: "SUB-1000", role: "sub_admin", is_primary_admin: false,
    features: [], live_teams: [], sub_admin_access: { status: "pending", version: 1, grants: [] },
  };
  const directory = { entries: [entry], additional_admin_limit: 3, additional_admin_count: 0 };
  await page.route("**/api/v1/admin/staff-access", async (route) => route.fulfill({ json: directory }));
  await page.route("**/api/v1/admin/staff-access/*/history", async (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/admin/staff-access/*/dashboard", async (route) => {
    const update = route.request().postDataJSON();
    await route.fulfill({ json: { ...directory, entries: [{ ...entry, sub_admin_access: { status: "active", version: 2, grants: update.grants } }] } });
  });
  await page.goto("/dashboard/users");
  await page.getByRole("button", { name: "Edit access", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Pending Reviewer" });
  const finance = dialog.getByRole("group", { name: "Account Manager", exact: true });
  const media = dialog.getByRole("group", { name: "Media Sub Admin", exact: true });
  await finance.getByRole("checkbox", { name: "Loans", exact: true }).check();
  await media.getByRole("checkbox", { name: "Real Estate", exact: true }).check();
  await media.getByRole("checkbox", { name: "Edit", exact: true }).uncheck();
  await expect(dialog.getByText("Account Manager · Loans · View, Prepare payout requests", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Media Sub Admin · Real Estate · View", { exact: true })).toBeVisible();
  const saved = page.waitForRequest((request) => request.url().endsWith("/dashboard") && request.method() === "PUT");
  await dialog.getByRole("button", { name: "Activate with these grants" }).click();
  expect((await saved).postDataJSON()).toMatchObject({
    status: "active", expected_version: 1,
    grants: [
      { assignment: "account_manager", business_line: "loans", actions: ["view", "prepare"] },
      { assignment: "media_sub_admin", business_line: "real_estate", actions: ["view"] },
    ],
  });
  await expect(page.getByRole("dialog", { name: "Pending Reviewer" })).toHaveCount(0);
  await expect(page.getByText("Scoped access", { exact: true })).toBeVisible();
});

test("a scoped Team Manager opens Products only with a Loans grant", async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "sub_admin");
  let line = "loans";
  await page.route("**/api/v1/auth/me", async (route) => route.fulfill({ json: {
    first_name: "Scope", last_name: "Manager", email: "manager@example.test",
    email_verified: true, profiles: [], sub_admin_access: {
      status: "active", version: 1, grants: [{ assignment: "team_manager", business_line: line, actions: ["view"] }],
    },
  } }));
  await page.route("**/api/v1/manager/products", async (route) => route.fulfill({ json: { products: [
    { product_id: FIXTURE_ID, label: "Team Home Loan", category: "loan", active: true, specialists: 1, open_leads: 3, open_tasks: 0 },
  ] } }));

  await page.goto("/dashboard/products");
  await expect(page.getByRole("heading", { level: 1, name: "Products" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Team Home Loan", { exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);

  line = "real_estate";
  await page.goto("/dashboard/products");
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 });
  await page.goto(`/dashboard/products/${FIXTURE_ID}`);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 });
});
