import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Telecaller leads and Employee tasks filter by loan
// status, call status, interest and "referred by", and show who referred the
// lead on the list row and the detail page.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const AGENT_LEAD = "65000000-0000-4000-8000-0000000000a1";
const CLIENT_LEAD = "65000000-0000-4000-8000-0000000000a2";
const DIRECT_LEAD = "65000000-0000-4000-8000-0000000000a3";

function lead(id: string, name: string, patch: Record<string, unknown>) {
  return {
    id,
    name,
    mobile: "+919876543210",
    business_line: "loans",
    status: "working",
    requirement: null,
    last_disposition: null,
    last_interest_level: null,
    next_follow_up_at: null,
    created_at: "2026-11-12T04:00:00Z",
    updated_at: "2026-11-14T08:45:00Z",
    latest_request: null,
    loan_statuses: [],
    referrer: null,
    ...patch,
  };
}

const LEADS = [
  lead(AGENT_LEAD, "Agent Lead", {
    last_disposition: "connected",
    last_interest_level: "hot",
    loan_statuses: ["sanctioned"],
    referrer: { kind: "agent", reference_id: "AG-1234ABCD" },
  }),
  lead(CLIENT_LEAD, "Client Lead", {
    last_disposition: "busy",
    referrer: { kind: "client", reference_id: "7K2M9QXA" },
  }),
  lead(DIRECT_LEAD, "Direct Lead", {}),
];

async function mockTelecaller(page: Page, baseURL: string) {
  await mockMobileApi(page, "telecaller", "loans");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: LEADS }));
  await page.route(`**/api/v1/telecaller/leads/${CLIENT_LEAD}`, (route) =>
    route.fulfill({
      json: {
        ...LEADS[1],
        activities: [],
        loan_applications: [],
        financial_enquiries: [],
        property_enquiries: [],
        site_visits: [],
        property_deals: [],
        tasks: [],
      },
    }),
  );
  await page.route(`**/api/v1/telecaller/leads/${CLIENT_LEAD}/client-history`, (route) =>
    route.fulfill({ json: { business_line: "loans", leads: [] } }),
  );
}

/** Picks an option; secondary filters live behind "More filters", which opens first. */
async function pick(page: Page, label: string, option: string) {
  const box = page.getByRole("combobox", { name: label });
  if (!(await box.isVisible())) await page.getByRole("button", { name: /^More filters/ }).click();
  await box.click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

/** Closes "More filters" and clears everything from the bar. */
async function clearAll(page: Page) {
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Clear all" }).click();
}

const rows = (page: Page) => page.locator("tbody tr");

test("telecaller filters leads by loan status, call status, interest and referrer", async ({ page, baseURL }) => {
  await mockTelecaller(page, baseURL!);
  await page.setViewportSize({ width: 1365, height: 900 });
  await page.goto("/dashboard/leads");

  await expect(rows(page)).toHaveCount(3);
  await expect(page.getByText("Agent · AG-1234ABCD")).toBeVisible();
  await expect(page.getByText("Client · 7K2M9QXA")).toBeVisible();
  // Unfiltered selects read the field name; the secondary ones wait behind More filters.
  await expect(page.getByRole("combobox", { name: "Filter by status" })).toHaveText("Status");
  await expect(page.getByRole("combobox", { name: "Filter by lead interest" })).toHaveCount(0);
  await expect(page.getByText("From", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("telecaller-leads-filters.png"), fullPage: true, animations: "disabled" });

  await pick(page, "Filter by loan status", "Approved");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Agent Lead");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "More filters (1)" })).toBeVisible();
  await page.getByRole("button", { name: "Remove filter Loan status: Approved" }).click();
  await expect(rows(page)).toHaveCount(3);

  await pick(page, "Filter by call status", "Busy");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Client Lead");
  await pick(page, "Filter by call status", "Not called yet");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Direct Lead");
  await clearAll(page);

  await pick(page, "Filter by lead interest", "Hot");
  await expect(rows(page)).toHaveCount(1);
  await clearAll(page);

  await pick(page, "Filter by lead source", "Referred by client");
  await expect(rows(page)).toHaveCount(1);
  await clearAll(page);

  await page.getByRole("button", { name: /^More filters/ }).click();
  await page.getByRole("textbox", { name: "Referred by ID" }).fill("ag-1234");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Agent Lead");
});

test("lead detail shows who referred the lead", async ({ page, baseURL }) => {
  await mockTelecaller(page, baseURL!);
  await page.setViewportSize({ width: 1365, height: 900 });
  await page.goto(`/dashboard/leads/${CLIENT_LEAD}`);

  await expect(page.getByTestId("lead-referrer")).toHaveText("Referred by Client · 7K2M9QXA");
});

test("employee tasks filter by the lead's signals and show the referrer", async ({ page, baseURL }) => {
  await mockMobileApi(page, "employee", "loans");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  const base = {
    lead_contact_mode: "allow",
    business_line: "loans",
    task_type: "document_collection",
    status: "assigned",
    outcome: null,
    notes: null,
    due_at: null,
    created_at: "2026-11-15T00:00:00Z",
    updated_at: "2026-11-15T00:00:00Z",
    lead_mobile: "+919876543210",
  };
  const tasks = [
    {
      ...base,
      id: "70000000-0000-4000-8000-000000000001",
      lead_uuid: AGENT_LEAD,
      lead_name: "Agent Lead",
      lead_last_disposition: "connected",
      lead_last_interest_level: "warm",
      lead_loan_statuses: ["sanctioned"],
      lead_referrer: { kind: "agent", reference_id: "AG-1234ABCD" },
    },
    {
      ...base,
      id: "70000000-0000-4000-8000-000000000002",
      lead_uuid: DIRECT_LEAD,
      lead_name: "Direct Lead",
      lead_last_disposition: null,
      lead_last_interest_level: null,
      lead_loan_statuses: [],
      lead_referrer: null,
    },
  ];
  await page.route("**/api/v1/employee/tasks**", (route) => {
    const path = new URL(route.request().url()).pathname;
    return path.endsWith("/employee/tasks") ? route.fulfill({ json: tasks }) : route.fallback();
  });
  await page.setViewportSize({ width: 1365, height: 900 });
  await page.goto("/dashboard/tasks");

  await expect(rows(page)).toHaveCount(2);
  await expect(page.getByText("Agent · AG-1234ABCD")).toBeVisible();
  await expect(page.getByText("Last call: Connected")).toBeVisible();

  await pick(page, "Filter by lead interest", "Warm");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Agent Lead");

  await pick(page, "Filter by lead interest", "All");
  await pick(page, "Filter by lead source", "Direct lead");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Direct Lead");
});
