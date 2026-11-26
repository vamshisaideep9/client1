import { expect, test, type Page } from "@playwright/test";
import type { UserRole } from "@/lib/auth";
import { mockMobileApi, schemaExample, FIXTURE_ID } from "./helpers/mobile-fixtures";

test.setTimeout(180_000);
test.use({ contextOptions: { reducedMotion: "reduce" } });
const SECOND_PRODUCT = "20000000-0000-4000-8000-000000000001";
const INSURANCE = "20000000-0000-4000-8000-000000000003";
const TASK_ID = "30000000-0000-4000-8000-000000000001";
const LEAD_ID = "40000000-0000-4000-8000-000000000001";
const codes = { admin: "ADMIN-001", sub_admin: "SUB-001", telecaller: "TC-001", employee: "EMP-001", agent: "AGENT-001", client: "CLIENT-001" };
function profile(role: Exclude<UserRole, "client">, specialty: string | null = FIXTURE_ID) {
  return { profile_uuid: FIXTURE_ID, role, code: codes[role], business_line: role === "admin" || role === "sub_admin" ? null : role === "agent" ? "loans" : "both",
    loan_specialty_id: role === "telecaller" ? specialty : null,
    loan_specialty_label: role === "telecaller" && specialty ? specialty === FIXTURE_ID ? "Personal Loan" : "Home Loan" : null,
    teams: role === "telecaller" ? [{ business_line: "loans", name: "North region lending team" }, { business_line: "real_estate", name: "West region property team" }] : [],
  };
}
async function setup(page: Page, role: UserRole, metadata = true) {
  await mockMobileApi(page, role);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: String(test.info().project.use.baseURL ?? "http://localhost:3001") }]);
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: {
    first_name: "Mobile", last_name: "Reviewer", mobile: "+919876543210", email: "mobile@example.test", email_verified: true,
    profiles: role === "client" ? [{ business_line: "loans", customer_code: codes.client }] : [],
    ...(metadata ? { role_profiles: role === "client" ? [] : [profile(role)] } : {}),
  } }));
  await page.route("**/api/v1/admin/loan-types", (route) => route.fulfill({ json: { loan_types: [
    { id: FIXTURE_ID, label: "Personal Loan", active: true, category: "loan" },
    { id: SECOND_PRODUCT, label: "Home Loan", active: true, category: "loan" },
    { id: "retired", label: "Retired Loan", active: false, category: "loan" },
    { id: "card", label: "Credit Card", active: true, category: "credit_card" },
    { id: INSURANCE, label: "Term Insurance", active: true, category: "insurance" },
  ] } }));
}
async function choose(page: Page, label: string | RegExp, option: string) {
  await page.getByLabel(label).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
async function createForm(page: Page) {
  await page.goto("/dashboard/users", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Create staff account", exact: true }).click();
  await page.getByLabel(/^First name/).fill("Synthetic");
  await page.getByLabel(/^Last name/).fill("Caller");
  await page.getByLabel(/^Mobile number/).fill("9812345678");
  await page.getByLabel(/^Email/).fill("synthetic@example.test");
  await choose(page, /^Role/, "Telecaller");
  await choose(page, /^Business line/, "Loans");
}

test("Admin provisions a specialty and keeps form values after a save error", async ({ page }, info) => {
  await setup(page, "admin");
  let body: unknown;
  await page.route("**/api/v1/admin/users/create", async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ status: 503, json: { detail: "Synthetic retry response" } });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await createForm(page);
  await choose(page, "Product specialty (optional)", "Home Loan");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect.poll(() => body).toMatchObject({ role: "telecaller", business_line: "loans", loan_specialty_id: SECOND_PRODUCT });
  await expect(page.getByLabel(/^First name/)).toHaveValue("Synthetic");
  await expect(page.getByLabel("Product specialty (optional)")).toContainText("Home Loan");
  await page.screenshot({ path: info.outputPath("specialty-create-390.png"), fullPage: true });
});

test("role and line changes clear a hidden specialty, and Officers can specialise", async ({ page }) => {
  await setup(page, "admin");
  let body: unknown;
  await page.route("**/api/v1/admin/users/create", async (route) => { body = route.request().postDataJSON(); await route.fulfill({ status: 503, json: { detail: "Synthetic retry" } }); });
  await createForm(page);
  await choose(page, "Product specialty (optional)", "Home Loan");
  await choose(page, /^Business line/, "Real Estate");
  await expect(page.getByLabel("Product specialty (optional)")).toHaveCount(0);
  await choose(page, /^Business line/, "Loans");
  await expect(page.getByLabel("Product specialty (optional)")).toContainText("No specialty");
  await choose(page, "Product specialty (optional)", "Personal Loan");
  // Changing the role clears the line and the specialty; Officers can specialise too.
  await choose(page, /^Role/, "Officer");
  await expect(page.getByLabel("Product specialty (optional)")).toHaveCount(0);
  await choose(page, /^Business line/, "Loans");
  await expect(page.getByLabel("Product specialty (optional)")).toContainText("No specialty");
  await choose(page, "Product specialty (optional)", "Term Insurance");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect.poll(() => body).toMatchObject({ role: "employee", business_line: "loans", loan_specialty_id: INSURANCE });
  await choose(page, /^Role/, "Sub Admin");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect.poll(() => body).toMatchObject({ role: "sub_admin", loan_specialty_id: null });
});

test("existing account specialty supports retry, clear and directory refresh", async ({ page }, info) => {
  await setup(page, "admin");
  let current = profile("telecaller");
  const account = () => ({ id: FIXTURE_ID, first_name: "Synthetic", last_name: "Caller", mobile: "+919812345678", email: "caller@example.test", status: "active", roles: ["telecaller"], client_profiles: [], role_profiles: [current], created_at: "2026-11-20T06:00:00Z", last_login_at: null });
  await page.route("**/api/v1/admin/users?**", (route) => route.fulfill({ json: { users: [account()], total: 1 } }));
  let calls = 0;
  const bodies: unknown[] = [];
  await page.route(`**/api/v1/admin/users/${FIXTURE_ID}/loan-specialty`, async (route) => {
    const body = route.request().postDataJSON(); bodies.push(body); calls++;
    if (calls === 1) { await route.fulfill({ status: 503, json: { detail: "Could not save specialty. Retry." } }); return; }
    current = profile("telecaller", body.loan_specialty_id);
    await route.fulfill({ json: [current] });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/users", { waitUntil: "domcontentloaded" });
  await page.getByText("Synthetic Caller", { exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Synthetic Caller" });
  await expect(dialog.getByText("TC-001", { exact: true })).toBeVisible();
  await choose(page, "Product specialty (optional)", "Home Loan");
  await dialog.getByRole("button", { name: "Save specialty", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Something went wrong on our end. Please try again in a moment.");
  await expect(dialog.getByLabel("Product specialty (optional)")).toContainText("Home Loan");
  await dialog.getByRole("button", { name: "Save specialty", exact: true }).click();
  await expect(dialog.getByText("Specialty: Home Loan", { exact: true })).toBeVisible();
  expect(bodies.slice(0, 2)).toEqual([{ loan_specialty_id: SECOND_PRODUCT }, { loan_specialty_id: SECOND_PRODUCT }]);
  await page.screenshot({ path: info.outputPath("specialty-account-1440.png"), fullPage: true });
  await choose(page, "Product specialty (optional)", "No specialty");
  await dialog.getByRole("button", { name: "Save specialty", exact: true }).click();
  await expect.poll(() => bodies.at(-1)).toEqual({ loan_specialty_id: null });
  await expect(dialog.getByText("Specialty: Home Loan", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Close account", exact: true }).click();
  await expect(page.getByText("Specialty: Home Loan", { exact: true })).toHaveCount(0);
});

for (const width of [320, 390, 768, 1440]) test(`Telecaller codes, specialty and dual-line teams at ${width}px`, async ({ page }, info) => {
  await setup(page, "telecaller");
  await page.setViewportSize({ width, height: 900 });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("TC-001", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Loans team: North region lending team", { exact: true })).toBeVisible();
  await expect(page.getByText("Real Estate team: West region property team", { exact: true })).toBeVisible();
  await expect(page.getByText("Specialty: Personal Loan", { exact: true })).toBeVisible();
  await expect(page.getByLabel(/^First name/)).toHaveCount(0);
  await page.locator("header").getByRole("button", { name: "Open account menu", exact: true }).click();
  await expect(page.getByRole("menu").getByText("TC-001", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({ path: info.outputPath(`role-teams-${width}.png`), fullPage: true });
  if (width === 1440) {
    await page.keyboard.press("Escape");
    await page.getByRole("navigation", { name: "Workspace", exact: true }).getByRole("button", { name: "Open account menu", exact: true }).click();
    await expect(page.getByRole("menu").getByText("TC-001", { exact: true })).toBeVisible();
  }
});

for (const role of ["admin", "sub_admin", "agent", "employee", "client"] as const) test(`${role} shows the assigned code in settings`, async ({ page }) => {
  await setup(page, role);
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(codes[role], { exact: true }).first()).toBeVisible();
});

test("missing optional profile metadata keeps staff role and line useful", async ({ page }) => {
  await setup(page, "employee", false);
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  const badge = page.getByLabel("Officer profile");
  await expect(badge).toContainText("Officer");
  await expect(badge).toContainText("Loans and Real Estate");
  await expect(page.getByLabel(/^First name/)).toHaveCount(0);
});

test("Telecaller field tasks show the assigned Officer name and code", async ({ page }) => {
  await setup(page, "telecaller");
  const task = { ...schemaExample("TaskRead"), id: TASK_ID, lead_uuid: LEAD_ID, task_type: "document_collection", status: "assigned", notes: "Collect supporting documents", assigned_employee_profile_uuid: SECOND_PRODUCT, assigned_employee_name: "Synthetic Officer", assigned_employee_code: "EMP-0123" };
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}`, (route) => route.fulfill({ json: { ...schemaExample("TelecallerLeadDetailRead"), id: LEAD_ID, mobile: "+919812345678", name: "Synthetic Client", business_line: "loans", status: "assigned", tasks: [task] } }));
  await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Synthetic Officer", { exact: true })).toBeVisible();
  await expect(page.getByText("EMP-0123", { exact: true })).toBeVisible();
});

test("Officer list, detail and home show the raising Telecaller", async ({ page }, info) => {
  await setup(page, "employee");
  const task = { ...schemaExample("EmployeeTaskRead"), id: TASK_ID, lead_uuid: LEAD_ID, lead_name: "Synthetic Client", lead_mobile: null, lead_contact_mode: "deny", business_line: "loans", task_type: "document_collection", status: "assigned", due_at: new Date().toISOString(), raised_by_telecaller_name: "Synthetic Telecaller", raised_by_telecaller_code: "TC-0123" };
  await page.route("**/api/v1/employee/tasks", (route) => route.fulfill({ json: [task] }));
  await page.route(`**/api/v1/employee/tasks/${TASK_ID}`, (route) => route.fulfill({ json: task }));
  await page.route("**/api/v1/employee/home", (route) => route.fulfill({ json: { tasks_today: [task], overdue_count: 0, counts_by_type: {}, counts_by_status: {} } }));
  await page.setViewportSize({ width: 390, height: 900 });
  for (const path of ["/dashboard/tasks", `/dashboard/tasks/${TASK_ID}`, "/dashboard"]) {
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Synthetic Telecaller", { exact: true })).toBeVisible();
    await expect(page.getByText("TC-0123", { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: info.outputPath("employee-counterpart-390.png"), fullPage: true });
});

test("specialty catalogue failures can be retried without losing the form", async ({ page }) => {
  await setup(page, "admin");
  // Fails until Retry is pressed: React strict mode (dev) mounts the select
  // twice, so "only the first request fails" would be consumed by the discarded mount.
  let available = false;
  await page.route("**/api/v1/admin/loan-types", async (route) => {
    if (!available) { await route.fulfill({ status: 503, json: { detail: "Synthetic catalogue unavailable" } }); return; }
    await route.fulfill({ json: { loan_types: [
      { id: FIXTURE_ID, label: "Personal Loan", active: true, category: "loan" },
      { id: "retired", label: "Retired Loan", active: false, category: "loan" },
      { id: "card", label: "Credit Card", active: true, category: "credit_card" },
    ] } });
  });
  await createForm(page);
  await expect(page.getByRole("alert").filter({ hasText: "Could not load products" })).toBeVisible();
  available = true;
  await page.getByRole("button", { name: "Retry products", exact: true }).click();
  await page.getByLabel("Product specialty (optional)").click();
  await expect(page.getByRole("option", { name: "Personal Loan", exact: true })).toBeVisible();
  await expect(page.getByRole("option", { name: "Retired Loan", exact: true })).toHaveCount(0);
  // Every active category is a specialty now, grouped under its category.
  await expect(page.getByRole("option", { name: "Credit Card", exact: true })).toBeVisible();
  await expect(page.getByRole("group").filter({ hasText: "Credit cards" })).toContainText("Credit Card");
  await page.getByRole("option", { name: "Personal Loan", exact: true }).click();
  await expect(page.getByLabel(/^First name/)).toHaveValue("Synthetic");
});

test("manager member detail displays the reached member's role code and specialty", async ({ page }) => {
  await setup(page, "sub_admin");
  const member = { ...schemaExample("TeamMemberRead"), staff_profile_uuid: SECOND_PRODUCT,
    first_name: "Synthetic", last_name: "Member", staff_code: "TC-TEAM-001", status: "active",
    business_line: "both", loan_specialty_id: FIXTURE_ID, loan_specialty_label: "Personal Loan" };
  const team = { ...schemaExample("StaffTeamRead"), id: FIXTURE_ID, name: "Lending team", business_line: "loans", member_role: "telecaller", members: [member] };
  await page.route("**/api/v1/manager/teams", (route) => route.fulfill({ json: { teams: [team] } }));
  await page.goto(`/dashboard/team/${FIXTURE_ID}/members/${SECOND_PRODUCT}`, { waitUntil: "domcontentloaded" });
  const badge = page.getByLabel("Telecaller profile");
  await expect(badge).toContainText("TC-TEAM-001");
  await expect(badge).toContainText("Specialty: Personal Loan");
  await expect(badge).toContainText("Loans team: Lending team");
});

test("a delayed specialty save cannot replace another open account's metadata", async ({ page }) => {
  await setup(page, "admin");
  const first = { id: FIXTURE_ID, first_name: "Synthetic", last_name: "First", mobile: "+919812345678", email: "first@example.test", status: "active", roles: ["telecaller"], client_profiles: [], role_profiles: [{ ...profile("telecaller"), code: "TC-FIRST" }], created_at: "2026-11-20T06:00:00Z", last_login_at: null };
  const second = { ...first, id: SECOND_PRODUCT, first_name: "Synthetic", last_name: "Second", role_profiles: [{ ...profile("telecaller", null), profile_uuid: SECOND_PRODUCT, code: "TC-SECOND" }] };
  await page.route("**/api/v1/admin/users?**", (route) => route.fulfill({ json: { users: [first, second], total: 2 } }));
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let started = false;
  await page.route(`**/api/v1/admin/users/${FIXTURE_ID}/loan-specialty`, async (route) => {
    started = true; await gate;
    await route.fulfill({ json: [{ ...profile("telecaller", SECOND_PRODUCT), code: "TC-FIRST" }] });
  });
  await page.goto("/dashboard/users", { waitUntil: "domcontentloaded" });
  await page.getByText("Synthetic First", { exact: true }).first().click();
  await choose(page, "Product specialty (optional)", "Home Loan");
  await page.getByRole("button", { name: "Save specialty", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByRole("button", { name: "Close account", exact: true }).click();
  await page.getByText("Synthetic Second", { exact: true }).first().click();
  release();
  await expect(page.getByText("Product specialty saved", { exact: true })).toBeVisible();
  const dialog = page.getByRole("dialog", { name: "Synthetic Second" });
  await expect(dialog.getByText("TC-SECOND", { exact: true })).toBeVisible();
  await expect(dialog.getByText("TC-FIRST", { exact: true })).toHaveCount(0);
  await expect(dialog.getByLabel("Product specialty (optional)")).toContainText("No specialty");
});

test("an Officer's account saves an insurance specialty", async ({ page }) => {
  await setup(page, "admin");
  let current = { ...profile("employee"), loan_specialty_id: null as string | null, loan_specialty_label: null as string | null };
  const account = () => ({ id: FIXTURE_ID, first_name: "Synthetic", last_name: "Officer", mobile: "+919812345679", email: "officer@example.test", status: "active", roles: ["employee"], client_profiles: [], role_profiles: [current], created_at: "2026-11-20T06:00:00Z", last_login_at: null });
  await page.route("**/api/v1/admin/users?**", (route) => route.fulfill({ json: { users: [account()], total: 1 } }));
  const bodies: unknown[] = [];
  await page.route(`**/api/v1/admin/users/${FIXTURE_ID}/loan-specialty`, async (route) => {
    const body = route.request().postDataJSON(); bodies.push(body);
    current = { ...current, loan_specialty_id: body.loan_specialty_id, loan_specialty_label: body.loan_specialty_id ? "Term Insurance" : null };
    await route.fulfill({ json: [current] });
  });
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/dashboard/users", { waitUntil: "domcontentloaded" });
  await page.getByText("Synthetic Officer", { exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "Synthetic Officer" });
  await expect(dialog.getByRole("heading", { name: "Officer routing" })).toBeVisible();
  await choose(page, "Product specialty (optional)", "Term Insurance");
  await dialog.getByRole("button", { name: "Save specialty", exact: true }).click();
  await expect(page.getByText("Product specialty saved", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Specialty: Term Insurance", { exact: true })).toBeVisible();
  expect(bodies).toEqual([{ loan_specialty_id: INSURANCE }]);
});

test("the staffing page's Add Officer link prefills a product specialist", async ({ page }) => {
  await setup(page, "admin");
  await page.goto(`/dashboard/users?role=employee&product=${INSURANCE}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel(/^Role/)).toContainText("Officer");
  await expect(page.getByLabel(/^Business line/)).toContainText("Loans");
  await expect(page.getByLabel("Product specialty (optional)")).toContainText("Term Insurance");
  await expect(page).toHaveURL(/\/dashboard\/users$/);
});
