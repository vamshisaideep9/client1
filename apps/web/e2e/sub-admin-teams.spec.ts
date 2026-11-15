import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: Main Admin team management and the Sub Admin
// manager's "My team" pages (CS-019).
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

async function mockManager(page: Page, teams: unknown[]) {
  await mockMobileApi(page, "sub_admin");
  const moves: unknown[] = [];
  const overviewQueries: string[] = [];
  await page.route("**/api/v1/manager/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/v1/manager/teams") return route.fulfill({ json: { teams } });
    if (path.endsWith("/overview")) {
      overviewQueries.push(url.search);
      return route.fulfill({
        json: {
          team,
          range_days: 30,
          date_from: url.searchParams.get("date_from"),
          date_to: url.searchParams.get("date_to"),
          totals: kpis(52, 41.2),
          members: [
            { member: team.members[0], kpis: kpis(31, 48.4) },
            { member: team.members[1], kpis: kpis(21, null) },
          ],
        },
      });
    }
    if (path.endsWith("/analytics")) {
      return route.fulfill({ json: analytics(Number(url.searchParams.get("days") ?? 30)) });
    }
    if (path.endsWith("/work")) {
      return route.fulfill({
        json: {
          member: team.members[0],
          kind: "leads",
          tasks: [],
          leads: [
            {
              id: LEAD,
              name: "Kiran Kumar",
              mobile: "+919800000001",
              status: "working",
              business_line: "loans",
              created_at: NOW,
              updated_at: NOW,
              requests: [
                { kind: "loan_application", id: LEAD, title: "Home Loan", status: "Docs collected", applied_at: NOW },
              ],
              last_call: { disposition: "callback_requested", interest_level: "warm", follow_up_at: NOW, created_at: NOW },
            },
          ],
        },
      });
    }
    if (path.endsWith(`/leads/${LEAD}`)) {
      return route.fulfill({
        json: {
          lead: {
            id: LEAD, name: "Kiran Kumar", mobile: "+919800000001", status: "working",
            business_line: "loans", created_at: NOW, updated_at: NOW, requests: [], last_call: null,
          },
          assigned_to: team.members[0],
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
      moves.push({ path, body: route.request().postDataJSON() });
      return route.fulfill({ json: { id: LEAD, assigned_staff_profile_uuid: BALA, status: "assigned" } });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  return Object.assign(moves, { overviewQueries });
}

async function signIn(page: Page, baseURL: string | undefined) {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
}

test("a manager sees team figures, a member's work and moves a lead", async ({ page, baseURL }, testInfo) => {
  const moves = await mockManager(page, [team]);
  await signIn(page, baseURL);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "My team" })).toBeVisible();
  await expect(page.locator('nav[aria-label="Workspace"]:visible').getByRole("link", { name: "My team" })).toBeVisible();
  const totals = page.getByRole("region", { name: "Team totals" });
  await expect(totals.getByText("41.2%")).toBeVisible();
  // The period travels as calendar dates, like every analytics dashboard.
  expect(moves.overviewQueries[0]).toMatch(/date_from=\d{4}-\d{2}-\d{2}&date_to=\d{4}-\d{2}-\d{2}/);
  const table = page.getByRole("table", { name: /figures per member/ });
  await expect(table.getByRole("row")).toHaveCount(3);
  await page.screenshot({ path: testInfo.outputPath("my-team-1440.png"), fullPage: true });

  await table.getByRole("link", { name: "View Asha Rao" }).click();
  await expect(page.getByRole("heading", { name: "Asha Rao" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Leads" })).toContainText("Kiran Kumar");
  await expect(page.getByText(/Last call .*Callback requested/)).toBeVisible();

  await page.getByRole("button", { name: "Calls for Kiran Kumar" }).click();
  await expect(page.getByRole("dialog").getByText("Asked us to call after salary credit.")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Move Kiran Kumar" }).click();
  const dialog = page.getByRole("dialog", { name: "Move to a teammate" });
  await dialog.getByRole("combobox", { name: "Teammate" }).click();
  // Only other active members are offered; the current holder is not.
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByRole("option", { name: "Bala Rao" }).click();
  await dialog.getByRole("button", { name: "Move", exact: true }).click();
  await expect.poll(() => moves.length).toBe(1);
  expect(moves[0]).toEqual({
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
