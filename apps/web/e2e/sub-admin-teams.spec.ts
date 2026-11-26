import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: Main Admin team management and the Sub Admin
// manager's "My team" pages, edits, notes and filters (CS-019, CS-020).
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const TEAM_ID = "20000000-0000-4000-8000-000000000001";
const ASHA = "30000000-0000-4000-8000-000000000001";
const BALA = "30000000-0000-4000-8000-000000000002";
const MANAGER = "30000000-0000-4000-8000-000000000009";
const LEAD = "40000000-0000-4000-8000-000000000001";
const NOW = "2026-11-15T09:30:00Z";

function person(id: string, first: string, code: string) {
  return {
    staff_profile_uuid: id,
    first_name: first,
    last_name: "Rao",
    staff_code: code,
    status: "active",
    business_line: "loans",
  };
}

const team = {
  id: TEAM_ID,
  name: "North callers",
  business_line: "loans",
  member_role: "telecaller",
  manager: person(MANAGER, "Meera", "SA-0001"),
  members: [
    { ...person(ASHA, "Asha", "TC-0001"), added_at: NOW },
    { ...person(BALA, "Bala", "TC-0002"), added_at: NOW },
  ],
  archived_at: null,
  created_at: NOW,
  updated_at: NOW,
};

const kpis = (calls: number, rate: number | null) => [
  { key: "calls", label: "Calls logged", value: calls, unit: "count", hint: null },
  { key: "connect_rate", label: "Connect rate", value: rate, unit: "percent", hint: null },
  { key: "active_leads", label: "Active leads", value: 4, unit: "count", hint: null },
  { key: "converted", label: "Converted", value: 1, unit: "count", hint: null },
  { key: "overdue_follow_ups", label: "Overdue follow-ups", value: 0, unit: "count", hint: null },
];

function analytics(range: number) {
  return {
    role: "telecaller",
    range_days: range,
    date_from: "2026-10-17",
    date_to: "2026-11-15",
    bucket: "day",
    kpis: kpis(31, 48.4),
    trend: {
      title: "Calls per day",
      description: "Every call they logged, by outcome.",
      series: [{ key: "connected", label: "Connected" }],
      points: [{ day: "2026-11-15", values: { connected: 3 } }],
    },
    breakdowns: [],
    funnel: null,
  };
}

const PRIYA_LEAD = "40000000-0000-4000-8000-000000000002";
type Signals = {
  loan_statuses: string[];
  last_disposition: string | null;
  last_interest_level: string | null;
  referrer: { kind: string; reference_id: string } | null;
};
const NO_SIGNALS: Signals = { loan_statuses: [], last_disposition: null, last_interest_level: null, referrer: null };

function leadRow(
  id: string,
  name: string,
  mobile: string,
  holder: string,
  first: string,
  signals: Signals = NO_SIGNALS,
  leadRef = "LD-00000101",
) {
  return {
    id,
    lead_ref: leadRef,
    name,
    mobile,
    status: "working",
    business_line: "loans",
    created_at: NOW,
    updated_at: NOW,
    requests: [{ kind: "loan_application", id, title: "Home Loan", status: "Docs collected", applied_at: NOW }],
    last_call: { disposition: "callback_requested", interest_level: "warm", follow_up_at: NOW, created_at: NOW },
    assigned_to: { staff_profile_uuid: holder, first_name: first, last_name: "Rao" },
    signals,
    hidden_fields: [],
  };
}

const KIRAN = leadRow(LEAD, "Kiran Kumar", "+919800000001", ASHA, "Asha");
const PRIYA = leadRow(PRIYA_LEAD, "Priya Shah", "+919811122233", BALA, "Bala", {
  loan_statuses: ["under_review"],
  last_disposition: "connected",
  last_interest_level: "hot",
  referrer: { kind: "agent", reference_id: "AG-1042" },
}, "LD-00000102");

async function mockManager(page: Page, teams: unknown[]) {
  await mockMobileApi(page, "sub_admin");
  const calls = { moves: [] as unknown[], edits: [] as unknown[], notes: [] as unknown[], overview: [] as string[] };
  const savedNotes: unknown[] = [];
  await page.route("**/api/v1/manager/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/api/v1/manager/teams") return route.fulfill({ json: { teams } });
    if (path.endsWith("/overview")) {
      calls.overview.push(url.search);
      const members = [
        { member: team.members[0], kpis: kpis(31, 48.4) },
        { member: team.members[1], kpis: kpis(21, null) },
      ];
      return route.fulfill({
        json: {
          team,
          range_days: 30,
          date_from: url.searchParams.get("date_from"),
          date_to: url.searchParams.get("date_to"),
          totals: kpis(52, 41.2),
          members,
          report: { ...analytics(30), kpis: kpis(52, 41.2) },
        },
      });
    }
    if (path.endsWith("/analytics")) return route.fulfill({ json: analytics(30) });
    if (path.endsWith(`/teams/${TEAM_ID}/work`)) {
      return route.fulfill({ json: { team_id: TEAM_ID, kind: "leads", leads: [KIRAN, PRIYA], tasks: [] } });
    }
    if (path.endsWith("/work")) {
      return route.fulfill({ json: { member: team.members[0], kind: "leads", leads: [KIRAN], tasks: [] } });
    }
    if (path.endsWith("/notes") && method === "POST") {
      const body = route.request().postDataJSON();
      calls.notes.push({ path, body });
      const note = { id: `6000000${savedNotes.length}-0000-4000-8000-000000000001`, author_name: "Meera Rao", body: body.body, follow_up_at: body.follow_up_at ?? null, created_at: NOW };
      savedNotes.unshift(note);
      return route.fulfill({ status: 201, json: note });
    }
    if (method === "PATCH") {
      calls.edits.push({ path, body: route.request().postDataJSON() });
      return route.fulfill({ json: { id: LEAD, status: "converted", due_at: null } });
    }
    if (path.endsWith(`/leads/${LEAD}`)) {
      return route.fulfill({
        json: {
          lead: KIRAN,
          assigned_to: team.members[0],
          notes: savedNotes,
          activities: [
            {
              id: "50000000-0000-4000-8000-000000000001", lead_uuid: LEAD,
              disposition: "callback_requested", interest_level: "warm",
              notes: "Asked us to call after salary credit.", follow_up_at: NOW, created_at: NOW, request: null,
            },
          ],
        },
      });
    }
    if (path.endsWith("/reassign")) {
      calls.moves.push({ path, body: route.request().postDataJSON() });
      return route.fulfill({ json: { id: LEAD, assigned_staff_profile_uuid: BALA, status: "assigned" } });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  return calls;
}

async function signIn(page: Page, baseURL: string | undefined) {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
}

test("a manager filters team analytics by period and call outcome", async ({ page, baseURL }, testInfo) => {
  const calls = await mockManager(page, [team]);
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "My team" })).toBeVisible();
  await expect(page.locator('nav[aria-label="Workspace"]:visible').getByRole("link", { name: "My team" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Key figures" }).getByText("41.2%")).toBeVisible();
  await expect(page.getByText("Every call they logged, by outcome.")).toBeVisible();
  // The period travels as calendar dates, like every analytics dashboard.
  expect(calls.overview[0]).toMatch(/date_from=\d{4}-\d{2}-\d{2}&date_to=\d{4}-\d{2}-\d{2}/);
  const table = page.getByRole("table", { name: /figures per member/ });
  await expect(table.getByRole("row")).toHaveCount(3);

  const filters = page.getByRole("group", { name: "Analytics filters" });
  await filters.getByRole("button", { name: "More filters" }).click();
  await page.getByRole("combobox", { name: "Filter by call status" }).click();
  await page.getByRole("option", { name: "Connected", exact: true }).click();
  await expect.poll(() => calls.overview.some((query) => query.includes("call_status=connected"))).toBe(true);
  await page.keyboard.press("Escape");

  await filters.getByRole("button", { name: "Members" }).click();
  await page.getByRole("checkbox", { name: "Bala Rao" }).click();
  await expect.poll(() => calls.overview.some((query) => query.includes(`member=${BALA}`))).toBe(true);
  await page.keyboard.press("Escape");
  await page.screenshot({ path: testInfo.outputPath("my-team-overview-1440.png"), fullPage: true });
});

test("a manager filters the team's work, changes a lead and leaves a note", async ({ page, baseURL }, testInfo) => {
  const calls = await mockManager(page, [team]);
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Work" }).click();

  const list = page.getByRole("list", { name: "Leads" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list).toContainText("Agent · AG-1042");

  const filters = page.getByRole("group", { name: "Work filters" });
  await filters.getByRole("combobox", { name: "Filter by team member" }).click();
  await page.getByRole("option", { name: "Bala Rao" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("Priya Shah");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list).toContainText("LD-00000101");
  await filters.getByLabel("Search client name, mobile or lead ref").fill("98000");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("Kiran Kumar");
  await filters.getByLabel("Search client name, mobile or lead ref").fill("ld-102");
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("Priya Shah");
  await filters.getByLabel("Search client name, mobile or lead ref").fill("");
  await filters.getByRole("button", { name: "More filters" }).click();
  await page.getByRole("combobox", { name: "Filter by lead interest" }).click();
  await page.getByRole("option", { name: "Hot" }).click();
  await expect(list.getByRole("listitem")).toHaveCount(1);
  await expect(list).toContainText("Priya Shah");
  await page.screenshot({ path: testInfo.outputPath("my-team-work-1440.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(filters.getByRole("list", { name: "Active filters" })).toContainText("Lead interest: Hot");
  await page.getByRole("button", { name: "Clear all" }).click();

  await page.getByRole("button", { name: "Edit Kiran Kumar" }).click();
  const edit = page.getByRole("dialog", { name: "Change lead status" });
  await edit.getByRole("combobox", { name: "New status" }).click();
  await page.getByRole("option", { name: "Converted" }).click();
  await edit.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => calls.edits.length).toBe(1);
  expect(calls.edits[0]).toEqual({
    path: `/api/v1/manager/teams/${TEAM_ID}/leads/${LEAD}`,
    body: { status: "converted" },
  });

  await page.getByRole("button", { name: "Details for Kiran Kumar" }).click();
  const details = page.getByRole("dialog", { name: "Kiran Kumar" });
  await expect(details.getByText("Asked us to call after salary credit.")).toBeVisible();
  await details.getByLabel("Add a note for the team member").fill("Call before noon; they prefer Telugu.");
  await details.getByRole("button", { name: "Add note" }).click();
  await expect.poll(() => calls.notes.length).toBe(1);
  expect(calls.notes[0]).toEqual({
    path: `/api/v1/manager/teams/${TEAM_ID}/leads/${LEAD}/notes`,
    body: { body: "Call before noon; they prefer Telugu." },
  });
  await expect(details.getByRole("list", { name: "Manager notes" })).toContainText("they prefer Telugu");
  await page.screenshot({ path: testInfo.outputPath("lead-details-1440.png") });
});

test("a manager moves a member's lead to a teammate", async ({ page, baseURL }, testInfo) => {
  const calls = await mockManager(page, [team]);
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/dashboard/team/${TEAM_ID}/members/${ASHA}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Asha Rao" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Leads" })).toContainText("Kiran Kumar");
  // One member's page has no "team member" filter.
  await expect(page.getByRole("combobox", { name: "Filter by team member" })).toHaveCount(0);

  await page.getByRole("button", { name: "Move Kiran Kumar" }).click();
  const dialog = page.getByRole("dialog", { name: "Move to a teammate" });
  await dialog.getByRole("combobox", { name: "Teammate" }).click();
  // Only other active members are offered; the current holder is not.
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByRole("option", { name: "Bala Rao" }).click();
  await dialog.getByRole("button", { name: "Move", exact: true }).click();
  await expect.poll(() => calls.moves.length).toBe(1);
  expect(calls.moves[0]).toEqual({
    path: `/api/v1/manager/teams/${TEAM_ID}/leads/${LEAD}/reassign`,
    body: { to_staff_profile_uuid: BALA },
  });
  await expect(page.getByText("Moved to Bala Rao")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("team-member-1440.png"), fullPage: true });
});

test("my team fits a 360px phone", async ({ page, baseURL }, testInfo) => {
  await mockManager(page, [team]);
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("list", { name: "Team members" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("my-team-360.png"), fullPage: true });

  await page.getByRole("tab", { name: "Work" }).click();
  await expect(page.getByRole("list", { name: "Leads" })).toContainText("Priya Shah");
  // Phones keep the lead signals behind "More filters", which opens as a bottom sheet.
  await expect(page.getByRole("combobox", { name: "Filter by lead interest" })).toHaveCount(0);
  await page.getByRole("button", { name: "More filters" }).click();
  await expect(page.getByRole("dialog", { name: "More filters" }).getByRole("combobox", { name: "Filter by lead interest" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("my-team-work-360.png"), fullPage: true });

  await page.goto(`/dashboard/team/${TEAM_ID}/members/${ASHA}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("list", { name: "Leads" })).toContainText("Kiran Kumar");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("team-member-360.png"), fullPage: true });
});

test("a Sub Admin without a team gets no menu entry and a clear empty page", async ({ page, baseURL }) => {
  await mockManager(page, []);
  await signIn(page, baseURL);
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("You don't manage a team yet")).toBeVisible();
  await expect(page.locator('nav[aria-label="Workspace"]:visible').getByRole("link", { name: "My team" })).toHaveCount(0);
});

test("the Main Admin creates a team and manages its members", async ({ page, baseURL }, testInfo) => {
  await mockMobileApi(page, "admin");
  const created: unknown[] = [];
  await page.route("**/api/v1/admin/teams**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === "/api/v1/admin/teams/eligible") {
      return route.fulfill({
        json: {
          managers: [person("30000000-0000-4000-8000-000000000010", "Nisha", "SA-0002")],
          members: [person("30000000-0000-4000-8000-000000000011", "Chitra", "TC-0003")],
        },
      });
    }
    if (url.pathname === "/api/v1/admin/teams" && method === "POST") {
      const body = route.request().postDataJSON();
      created.push(body);
      return route.fulfill({
        status: 201,
        json: {
          ...team,
          id: "20000000-0000-4000-8000-000000000002",
          name: body.name,
          business_line: body.business_line,
          manager: person(body.manager_staff_profile_uuid, "Nisha", "SA-0002"),
          members: [],
        },
      });
    }
    return route.fulfill({ json: { teams: [team], can_edit: true } });
  });
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/teams", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Teams", exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "North callers members" })).toContainText("Asha Rao");
  await expect(page.getByText("No Real Estate teams yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove Bala Rao from North callers" })).toBeVisible();

  await page.getByRole("button", { name: "New team" }).click();
  const dialog = page.getByRole("dialog", { name: "New team" });
  await dialog.getByLabel("Team name").fill("South callers");
  await dialog.getByRole("combobox", { name: "Manager (Sub Admin)" }).click();
  await page.getByRole("option", { name: "Nisha Rao · SA-0002" }).click();
  await dialog.getByRole("button", { name: "Create team" }).click();
  await expect.poll(() => created.length).toBe(1);
  expect(created[0]).toEqual({
    name: "South callers",
    business_line: "loans",
    member_role: "telecaller",
    manager_staff_profile_uuid: "30000000-0000-4000-8000-000000000010",
  });
  await expect(page.getByRole("heading", { name: "South callers" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("teams-1440.png"), fullPage: true });

  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("teams-360.png"), fullPage: true });
});
