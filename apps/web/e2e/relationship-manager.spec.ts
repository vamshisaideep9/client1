import { expect, test } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";

test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(150_000);

const AGENT_ID = "50000000-0000-4000-8000-000000000001";
const OTHER_AGENT_ID = "50000000-0000-4000-8000-000000000002";
const APPLICATION_ID = "60000000-0000-4000-8000-000000000001";
const RM_ID = "70000000-0000-4000-8000-000000000001";
const NEW_RM_ID = "70000000-0000-4000-8000-000000000002";

async function signIn(page: import("@playwright/test").Page, role: "admin" | "sub_admin" | "agent", baseURL: string) {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await mockMobileApi(page, role);
}

test("Main Admin changes an Agent's Relationship Manager from the Agent queue", async ({ page, baseURL }, info) => {
  await signIn(page, "admin", baseURL!);
  let manager: { staff_profile_id: string; name: string | null; staff_code: string } | null = {
    staff_profile_id: RM_ID, name: "Riya Manager", staff_code: "SUB-0001",
  };
  const application = () => ({
    id: APPLICATION_ID, first_name: "Asha", last_name: "Agent", mobile: "+919812345678", email: null,
    business_line: "loans", rera_code: null, status: "approved", created_at: "2026-11-01T09:00:00Z",
    agent_profile_id: AGENT_ID, relationship_manager: manager,
  });
  await page.route("**/api/v1/admin/agents?*", (route) => route.fulfill({ json: { applications: [application()] } }));
  await page.route(`**/api/v1/admin/agents/${APPLICATION_ID}`, (route) => route.fulfill({ json: { ...application(), documents: [], review_note: null } }));
  await page.route(`**/api/v1/admin/agents/${AGENT_ID}/relationship-manager/options`, (route) => route.fulfill({ json: [
    { staff_profile_id: RM_ID, name: "Riya Manager", staff_code: "SUB-0001", business_line: "loans", agent_count: 12, current: true },
    { staff_profile_id: NEW_RM_ID, name: "Nikhil Lead", staff_code: "SUB-0002", business_line: "loans", agent_count: 3, current: false },
  ] }));
  let saved: unknown;
  await page.route(`**/api/v1/admin/agents/${AGENT_ID}/relationship-manager`, async (route) => {
    saved = route.request().postDataJSON();
    manager = { staff_profile_id: NEW_RM_ID, name: "Nikhil Lead", staff_code: "SUB-0002" };
    await route.fulfill({ json: { agent_profile_id: AGENT_ID, relationship_manager: manager } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard/agents");
  await page.getByRole("combobox", { name: "Filter by status" }).click();
  await page.getByRole("option", { name: "Approved", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Relationship Manager" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Riya Manager · SUB-0001").first()).toBeVisible();
  await page.getByText("Asha Agent").first().click();
  const dialog = page.getByRole("dialog", { name: /Asha Agent/ });
  await dialog.getByRole("button", { name: "Change" }).click();
  const picker = page.getByRole("dialog", { name: "Relationship Manager for Asha Agent" });
  await expect(picker.getByText("12 Agents · current", { exact: false })).toBeVisible();
  await picker.getByRole("radio", { name: /Nikhil Lead/ }).check();
  await page.screenshot({ path: info.outputPath("rm-change-1440.png"), fullPage: true });
  await picker.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => saved).toEqual({ sub_admin_profile_id: NEW_RM_ID });
  await expect(page.getByText("Nikhil Lead · SUB-0002").first()).toBeVisible();
});

test("the access editor names assigned Agents and removes one", async ({ page, baseURL }) => {
  await signIn(page, "admin", baseURL!);
  const entry = {
    staff_profile_uuid: FIXTURE_ID, first_name: "Riya", last_name: "Manager",
    staff_code: "SUB-0001", role: "sub_admin", is_primary_admin: false, features: [], live_teams: [],
    sub_admin_access: { status: "active", version: 3, grants: [{
      assignment: "relationship_manager", business_line: "loans", actions: ["view", "follow_up"],
      agent_profile_ids: [AGENT_ID, OTHER_AGENT_ID],
    }] },
  };
  const directory = { entries: [entry], additional_admin_limit: 3, additional_admin_count: 0 };
  await page.route("**/api/v1/admin/staff-access", (route) => route.fulfill({ json: directory }));
  await page.route("**/api/v1/admin/staff-access/*/history", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/relationships/options/selected?*", (route) => route.fulfill({ json: [
    { id: AGENT_ID, name: "Asha Agent", agent_code: "AG-0001", business_line: "loans", status: "active", kyc_status: null, approved_at: null, submitted_leads: 0 },
    { id: OTHER_AGENT_ID, name: "Idle Agent", agent_code: "AG-0002", business_line: "loans", status: "inactive", kyc_status: null, approved_at: null, submitted_leads: 0 },
  ] }));
  let saved: { grants: { agent_profile_ids: string[] }[] } | undefined;
  await page.route("**/api/v1/admin/staff-access/*/dashboard", async (route) => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: directory });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/users");
  await page.getByRole("button", { name: "Edit access", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Riya Manager" });
  const assigned = dialog.getByRole("list", { name: "Assigned Agents, Loans" });
  await expect(assigned.getByText("Asha Agent · AG-0001")).toBeVisible();
  await expect(assigned.getByText("(inactive)")).toBeVisible();
  await assigned.getByRole("button", { name: "Remove Asha Agent from this Relationship Manager" }).click();
  await expect(assigned.getByText("Asha Agent · AG-0001")).toHaveCount(0);
  await dialog.getByRole("button", { name: /Save/ }).first().click();
  await expect.poll(() => saved?.grants[0].agent_profile_ids).toEqual([OTHER_AGENT_ID]);
});

test("a Relationship Manager reads an assigned Agent's leads without contact details", async ({ page, baseURL }, info) => {
  await signIn(page, "sub_admin", baseURL!);
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
    first_name: "Riya", last_name: "Manager", email: "rm@example.test", email_verified: true, profiles: [],
    sub_admin_access: { status: "active", version: 1, grants: [{
      assignment: "relationship_manager", business_line: "loans", actions: ["view"], agent_profile_ids: [AGENT_ID],
    }] },
  } }));
  await page.route("**/api/v1/relationships", (route) => route.fulfill({ json: [
    { id: AGENT_ID, name: "Asha Agent", agent_code: "AG-0001", business_line: "loans", status: "active", kyc_status: "verified", approved_at: null, submitted_leads: 2 },
  ] }));
  await page.route(`**/api/v1/relationships/${AGENT_ID}/activity`, (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/v1/relationships/${AGENT_ID}/leads`, (route) => route.fulfill({ json: [
    { id: FIXTURE_ID, lead_ref: "LD-00000042", business_line: "loans", status: "working", product_label: "Home Loan", created_at: "2026-11-20T09:00:00Z", updated_at: "2026-11-22T09:00:00Z" },
  ] }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/relationships");
  await page.getByRole("button", { name: /Asha Agent/ }).click();
  const leads = page.getByRole("table", { name: "Leads from Asha Agent" });
  await expect(leads.getByText("LD-00000042")).toBeVisible();
  await expect(leads.getByText("Working")).toBeVisible();
  await expect(leads.getByText("Home Loan")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save activity" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: info.outputPath("rm-leads-390.png"), fullPage: true });
});

test("an Agent sees their Relationship Manager on the home page", async ({ page, baseURL }, info) => {
  await signIn(page, "agent", baseURL!);
  await page.route("**/api/v1/agent/home", (route) => route.fulfill({ json: {
    profile: { agent_code: "AG-0001", business_line: "loans", kyc_status: "verified", status: "active", rera_code: null, approved_at: "2026-11-01T09:00:00Z" },
    counts_by_status: { new: 1 },
    relationship_manager: { name: "Riya Manager", staff_code: "SUB-0001" },
  } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  const card = page.getByRole("region", { name: "Your Relationship Manager" });
  await expect(card.getByText("Riya Manager")).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("Staff code SUB-0001", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: info.outputPath("agent-home-rm-390.png"), fullPage: true });
});
