import { expect, test, type Page } from "@playwright/test";
import ExcelJS from "exceljs";
import { mockMobileApi, FIXTURE_ID } from "./helpers/mobile-fixtures";

test.setTimeout(180_000);
test.use({ contextOptions: { reducedMotion: "reduce" } });
const LEAD_ID = "20000000-0000-4000-8000-000000000001";
const RATE_ID = "30000000-0000-4000-8000-000000000001";
const rate = {
  id: RATE_ID, loan_type_id: FIXTURE_ID, kind: "percent", percent_bps: 50, amount_paise: null,
  note: "Paid on disbursal", status: "approved", created_by_uuid: FIXTURE_ID,
  created_by_name: "Rate Maker", created_by_role: "sub_admin", is_mine: false,
  checker_name: "Admin Reviewer", reviewed_at: "2026-11-19T10:00:00Z", review_note: null,
  version: 1, created_at: "2026-11-19T09:00:00Z", updated_at: "2026-11-19T10:00:00Z",
};
const product = { loan_type_id: FIXTURE_ID, product_slug: "personal-loan", product_label: "Personal Loan", product_active: true, current: rate, pending: null, history: [] };
async function session(page: Page, role: "agent" | "admin" | "sub_admin" | "telecaller", line = "loans") {
  await mockMobileApi(page, role, line);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: String(test.info().project.use.baseURL ?? "http://localhost:3001") }]);
}
async function fillLead(page: Page) {
  await page.getByLabel("Mobile number").fill("9812345678");
  await page.getByLabel(/^Name/).fill("Asha");
  await page.getByLabel("Email (optional)").fill("asha@example.com");
}
function lead(count = 0, name = "Asha", id = LEAD_ID) {
  return {
    id, name, mobile: "+919812345678", business_line: "loans", status: "assigned",
    requirement: null, registered: false, editable: false, resubmittable: false,
    resubmit_count: count, last_resubmitted_at: count ? "2026-11-19T10:00:00Z" : null,
    created_at: "2026-11-19T10:00:00Z", updated_at: "2026-11-19T10:00:00Z",
    eligibility: "eligible", eligibility_reason: "accepted", eligibility_reason_label: "Accepted",
    facets: { loans: [], properties: [] }, loan_statuses: [], last_disposition: null, next_follow_up_at: null,
  };
}
test("loans Agent sees approved commission and sends email with the product", async ({ page }, info) => {
  await session(page, "agent");
  await page.route("**/api/v1/agent/commission-rates", (route) => route.fulfill({ json: { rates: { "personal-loan": rate } } }));
  let body: Record<string, unknown> | null = null;
  await page.route("**/api/v1/agent/leads", async (route) => {
    if (route.request().method() === "POST") { body = route.request().postDataJSON(); await route.fulfill({ status: 201, json: lead() }); }
    else await route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/leads/new");
  await fillLead(page);
  await page.getByLabel("Loan product (optional)").click();
  await page.getByRole("option", { name: "Personal Loan", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Product details" });
  await expect(dialog.getByText("Your commission: 0.5% of disbursed amount")).toBeVisible();
  await expect(dialog.getByText("Paid on disbursal")).toBeVisible();
  await dialog.getByRole("button", { name: "Attach to lead" }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("agent-loan-form-390.png"), fullPage: true });
  await page.getByRole("button", { name: "Introduce lead", exact: true }).click();
  await expect.poll(() => body).toMatchObject({ requirement: { email: "asha@example.com", product_slug: "personal-loan" } });
});
test("real-estate Agent chooses a property type without a listing", async ({ page }, info) => {
  await session(page, "agent", "real_estate");
  let body: unknown;
  await page.route("**/api/v1/agent/leads", async (route) => {
    body = route.request().postDataJSON(); await route.fulfill({ status: 201, json: { ...lead(), business_line: "real_estate" } });
  });
  await page.setViewportSize({ width: 768, height: 1000 });
  await page.goto("/dashboard/leads/new");
  await fillLead(page);
  await page.getByLabel("Property type (optional)").click();
  await page.getByRole("option", { name: "Villas", exact: true }).click();
  await page.screenshot({ path: info.outputPath("agent-property-form-768.png"), fullPage: true });
  await page.getByRole("button", { name: "Introduce lead", exact: true }).click();
  await expect.poll(() => body).toMatchObject({ requirement: { email: "asha@example.com", property_type: "villa" } });
  expect((body as { requirement: Record<string, unknown> }).requirement).not.toHaveProperty("property_id");
});
test("email-only editing leaves hidden notes untouched", async ({ page }) => {
  await session(page, "agent");
  let saved: unknown;
  await page.route(`**/api/v1/agent/leads/${LEAD_ID}`, async (route) => {
    if (route.request().method() === "PATCH") saved = route.request().postDataJSON();
    await route.fulfill({ json: { ...lead(), editable: true, requirement: { product_slug: "personal-loan", ...(saved ? { email: "new@example.com" } : {}) } } });
  });
  await page.goto(`/dashboard/leads/${LEAD_ID}`);
  await page.getByLabel("Email (optional)").fill("new@example.com");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => saved).toEqual({ requirement: { email: "new@example.com" } });
});
test("CSV preview skips invalid and repeated rows and downloads safe results", async ({ page }, info) => {
  await session(page, "agent");
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/v1/agent/leads/bulk", async (route) => {
    const request = route.request().postDataJSON();
    if (request.dry_run) await route.fulfill({ json: { dry_run: true, totals: {}, rows: [
      { row_index: 0, sno: "1", outcome: "ready", requirement_label: "Personal Loan", errors: [] },
      { row_index: 1, sno: "2", outcome: "invalid", errors: [{ field: "mobile", message: "Enter a 10-digit Indian mobile number." }] },
      { row_index: 2, sno: "3", outcome: "duplicate_in_file", reason_label: "This number appears on an earlier row", errors: [] },
    ] } });
    else { submitted = request; await route.fulfill({ json: { dry_run: false, totals: {}, rows: [{ row_index: 0, outcome: "created", lead_id: LEAD_ID, errors: [] }] } }); }
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/leads/bulk");
  const csv = "SNO,Name,Mobile Number,Email,Requirement,Description\n1,=1,9812345678,,Personal Loan,Call later\n2,Invalid,bad,,,\n3,Repeat,9812345678,,,";
  await page.getByLabel("Choose CSV or Excel file").setInputFiles({ name: "leads.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByText("1 of 3 rows ready.", { exact: false })).toBeVisible();
  const preview = page.getByRole("list", { name: "Lead upload rows" });
  await expect(preview.getByText("Needs correction")).toBeVisible();
  await expect(preview.getByText("Repeated in file")).toBeVisible();
  await page.getByRole("button", { name: "Submit 1 valid row", exact: true }).click();
  await expect(preview.getByText("Introduced", { exact: true })).toBeVisible();
  expect((submitted as unknown as { rows: unknown[] }).rows).toHaveLength(1);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download results" }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks).toString()).toContain('"\'=1"');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("bulk-results-390.png"), fullPage: true });
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(preview.getByText("Introduced", { exact: true })).toBeVisible();
  await expect(preview.getByText("Needs correction")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.screenshot({ path: info.outputPath("bulk-results-320.png"), fullPage: true });
});
test("Excel file is parsed in browser before preview", async ({ page }) => {
  await session(page, "agent");
  let posted: { rows: { mobile: string }[]; dry_run: boolean } | null = null;
  await page.route("**/api/v1/agent/leads/bulk", async (route) => {
    posted = route.request().postDataJSON();
    await route.fulfill({ json: { dry_run: true, totals: {}, rows: [{ row_index: 0, outcome: "ready", errors: [] }] } });
  });
  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet("Leads");
  sheet.addRow(["SNO", "Name", "Mobile Number", "Email", "Requirement", "Description"]);
  sheet.addRow([1, "Asha", 9812345678, "", "Personal Loan", ""]);
  await page.goto("/dashboard/leads/bulk");
  await page.getByLabel("Choose CSV or Excel file").setInputFiles({ name: "leads.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from(await workbook.xlsx.writeBuffer()) });
  await expect(page.getByRole("button", { name: "Submit 1 valid row", exact: true })).toBeVisible();
  expect(posted).toMatchObject({ dry_run: true, rows: [{ mobile: "9812345678" }] });
});
for (const role of ["agent", "telecaller"] as const) {
  test(`${role} can filter resubmitted leads`, async ({ page }) => {
    await session(page, role);
    await page.route(`**/api/v1/${role}/leads`, (route) => route.fulfill({ json: [
      lead(2, "Repeat Lead"), lead(0, "Fresh Lead", RATE_ID),
    ] }));
    await page.goto("/dashboard/leads");
    await expect(page.getByText("Resubmitted ×2")).toBeVisible();
    await page.getByRole("combobox", { name: "Filter by resubmission" }).click();
    await page.getByRole("option", { name: "Resubmitted", exact: true }).click();
    await expect(page.getByText("Fresh Lead", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Repeat Lead", { exact: true })).toBeVisible();
  });
}
test("Admin reviews a proposal and edits the immediate rate", async ({ page }, info) => {
  await session(page, "admin");
  let current = { ...product, pending: { ...rate, status: "pending_approval", checker_name: null } as Record<string, unknown> | null };
  let saved: unknown;
  await page.route("**/api/v1/commission-rates**", async (route) => {
    const request = route.request();
    if (request.method() === "PUT") saved = request.postDataJSON();
    if (request.method() === "POST") current = { ...current, pending: null };
    await route.fulfill({ json: request.method() === "GET" ? { products: [current] } : current });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/commission-rates");
  await page.getByRole("button", { name: "Review proposal" }).click();
  const review = page.getByRole("dialog", { name: "Review commission · Personal Loan" });
  await review.getByRole("button", { name: "Reject proposal" }).click();
  await expect(review.getByRole("alert")).toHaveText("Add feedback before rejecting.");
  await review.getByRole("button", { name: "Approve proposal" }).click();
  await expect(review).toHaveCount(0);
  await page.getByRole("button", { name: "Set rate", exact: true }).click();
  const form = page.getByRole("dialog", { name: "Set agent commission" });
  await form.getByLabel("Percent of disbursed amount (%)").fill("0.75");
  await form.getByRole("button", { name: "Set commission" }).click();
  await expect.poll(() => saved).toMatchObject({ kind: "percent", percent_bps: 75, amount_paise: null });
  await page.screenshot({ path: info.outputPath("admin-rates-1440.png"), fullPage: true });
});
test("Sub Admin proposal waits for review and can be withdrawn", async ({ page }, info) => {
  await session(page, "sub_admin");
  let current = { ...product, pending: null as Record<string, unknown> | null };
  await page.route("**/api/v1/commission-rates**", async (route) => {
    if (route.request().method() === "PUT") current = { ...current, pending: { ...rate, is_mine: true, checker_name: null, status: "pending_approval" } };
    if (route.request().method() === "POST") current = { ...current, pending: null };
    await route.fulfill({ json: route.request().method() === "GET" ? { products: [current] } : current });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/commission-rates");
  await page.getByRole("button", { name: "Propose rate" }).click();
  const form = page.getByRole("dialog", { name: "Propose agent commission" });
  await form.getByLabel("Percent of disbursed amount (%)").fill("0.5");
  await form.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByRole("button", { name: "Withdraw proposal" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review proposal" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("subadmin-rates-390.png"), fullPage: true });
  await page.getByRole("button", { name: "Withdraw proposal" }).click();
  await expect(page.getByRole("button", { name: "Withdraw proposal" })).toHaveCount(0);
});
test("Admin commission suggestion remains editable", async ({ page }) => {
  await session(page, "admin");
  let entered: unknown;
  await page.route("**/api/v1/admin/commissions/eligible?**", (route) => route.fulfill({ json: { total: 1, deals: [{
    deal_type: "loan_application", deal_uuid: LEAD_ID, agent_profile_uuid: FIXTURE_ID, agent_code: "AG-0001",
    agent_name: "Agent Asha", business_line: "loans", eligible_since: "2026-11-19T09:00:00Z",
    commission_rate: rate, suggested_amount_paise: 250000, suggestion_basis: "sanctioned", basis_amount_paise: 50000000,
  }] } }));
  await page.route("**/api/v1/admin/commissions", async (route) => {
    entered = route.request().postDataJSON(); await route.fulfill({ status: 201, json: { id: RATE_ID } });
  });
  await page.goto("/dashboard/commissions");
  await page.getByRole("button", { name: "Enter commission", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Enter commission" });
  await expect(dialog.getByLabel("Agreed amount (₹)")).toHaveValue("2500.00");
  await dialog.getByLabel("Agreed amount (₹)").fill("2600");
  await dialog.getByRole("button", { name: "Enter commission" }).click();
  await expect.poll(() => entered).toMatchObject({ agreed_amount_paise: 260000 });
});
