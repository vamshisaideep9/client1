import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only (CS-027): an Agent's contests page and home card, a
// Telecaller team member's view and the managing Sub Admin's My team panel.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LIVE = "50000000-0000-4000-8000-000000000011";
const SOON = "50000000-0000-4000-8000-000000000012";
const TEAM = "50000000-0000-4000-8000-000000000013";

const LOAN_CRITERIA = {
  version: 1,
  loans: {
    loan_type_ids: [],
    bank_ids: [],
    counted_stage: "disbursed",
    count_at_least: 1,
    count_at_most: 5,
    amount_at_least_paise: 500000000,
    case_amount_min_paise: null,
    case_amount_max_paise: null,
  },
  real_estate: null,
  activity: null,
  eligibility: { min_tenure_days: 0, kyc_verified: false },
};

function summary(id: string, status: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: "Personal loan sprint",
    business_line: "loans",
    audience: "agent",
    team_member_role: null,
    metric: "amount",
    win_mode: "top_n",
    top_n: 3,
    prize_paise: 1000000,
    manager_prize_paise: null,
    member_prize_paise: null,
    member_min_contribution: null,
    starts_on: "2026-11-01",
    ends_on: "2026-11-30",
    status,
    my_role: "participant",
    eligible: true,
    participants: 42,
    me: status === "approved" ? null : {
      rank: 2,
      metric_value: 320000000,
      progress: { count: 3, amount_paise: 320000000 },
      qualified: false,
      won: null,
      prize_paise: null,
      payment_status: null,
      excluded_reason: null,
    },
    ...overrides,
  };
}

function detail(id: string, overrides: Record<string, unknown> = {}) {
  return {
    ...summary(id, "live"),
    description: "Disburse personal loans this month.",
    terms: "Prizes are paid after the end date.",
    criteria: LOAN_CRITERIA,
    budget_cap_paise: null,
    computed_at: "2026-11-17T09:30:00Z",
    leaderboard: [
      { rank: 1, name: null, achieved: null, qualified: true, is_me: false },
      { rank: 2, name: "Asha R.", achieved: 320000000, qualified: false, is_me: true },
      { rank: 3, name: null, achieved: null, qualified: false, is_me: false },
    ],
    team: null,
    ...overrides,
  };
}

async function signIn(page: Page, baseURL: string | undefined, role: "agent" | "telecaller" | "sub_admin") {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, role);
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

test("an Agent follows a live contest: progress, the at-most limit and a minimal leaderboard", async ({ page, baseURL }) => {
  await signIn(page, baseURL, "agent");
  await page.route("**/api/v1/my-contests**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/my-contests") {
      return route.fulfill({ json: { contests: [summary(LIVE, "live"), summary(SOON, "approved", { title: "December sprint" })] } });
    }
    if (path === `/api/v1/my-contests/${LIVE}`) return route.fulfill({ json: detail(LIVE) });
    return route.fulfill({ status: 404, json: { detail: "Contest not found." } });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const card = page.getByRole("region", { name: "Contests" }).or(page.locator("section", { hasText: "Open to you now or starting soon" }));
  await expect(card.getByText("Personal loan sprint")).toBeVisible();
  await expect(card.getByText(/rank 2/)).toBeVisible();

  await page.goto("/dashboard/contests", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Live now" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Starting soon" })).toBeVisible();
  await page.getByRole("link", { name: /Personal loan sprint/ }).click();

  await expect(page.getByRole("heading", { name: "Your progress" })).toBeVisible();
  await expect(page.getByText("rank 2 of 42")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Total amount" })).toHaveAttribute("aria-valuenow", "64");
  await expect(page.getByText("at most 5")).toBeVisible();
  const board = page.getByRole("list", { name: "Leaderboard" });
  await expect(board.getByText("You")).toBeVisible();
  await expect(board.getByText("Participant")).toHaveCount(2);
  await expect(board.getByText("Hidden")).toHaveCount(2);
  await expect(page.getByText("The top 3 participants who meet every target win", { exact: false })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
});

test("a team member sees the team standing and only their own contribution", async ({ page, baseURL }) => {
  await signIn(page, baseURL, "telecaller");
  const teamDetail = detail(TEAM, {
    audience: "team",
    team_member_role: "telecaller",
    metric: "calls_logged",
    my_role: "team_member",
    prize_paise: null,
    manager_prize_paise: 500000,
    member_prize_paise: 100000,
    member_min_contribution: 40,
    criteria: { ...LOAN_CRITERIA, loans: null, activity: { calls_logged_at_least: 100 } },
    me: { rank: 1, metric_value: 120, progress: { calls_logged: 120 }, qualified: true, won: null, prize_paise: null, payment_status: null, excluded_reason: null },
    leaderboard: [{ rank: 1, name: "North callers", achieved: 120, qualified: true, is_me: true }],
    team: {
      team_name: "North callers",
      rank: 1,
      metric_value: 120,
      progress: { calls_logged: 120 },
      qualified: true,
      won: null,
      members: [{ name: "Ravi Rao", metric_value: 35, progress: { calls_logged: 35 }, meets_member_minimum: false, won: null, prize_paise: null, payment_status: null, is_me: true }],
    },
  });
  await page.route("**/api/v1/my-contests**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/my-contests/${TEAM}`) return route.fulfill({ json: teamDetail });
    return route.fulfill({ json: { contests: [teamDetail] } });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/dashboard/contests?contest=${TEAM}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "North callers's progress" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your contribution" })).toBeVisible();
  await expect(page.getByText("Below the minimum")).toBeVisible();
  await expect(page.getByText("The team's manager gets ₹5,000.")).toBeVisible();
});

test("a managing Sub Admin sees team contests in My team", async ({ page, baseURL }) => {
  await signIn(page, baseURL, "sub_admin");
  const managerDetail = detail(TEAM, {
    audience: "team",
    team_member_role: "telecaller",
    metric: "calls_logged",
    my_role: "team_manager",
    prize_paise: null,
    manager_prize_paise: 500000,
    member_prize_paise: 100000,
    member_min_contribution: 40,
    criteria: { ...LOAN_CRITERIA, loans: null, activity: { calls_logged_at_least: 100 } },
    me: { rank: 1, metric_value: 120, progress: { calls_logged: 120 }, qualified: true, won: null, prize_paise: null, payment_status: null, excluded_reason: null },
    team: {
      team_name: "North callers",
      rank: 1,
      metric_value: 120,
      progress: { calls_logged: 120 },
      qualified: true,
      won: null,
      members: [
        { name: "Asha Rao", metric_value: 85, progress: { calls_logged: 85 }, meets_member_minimum: true, won: null, prize_paise: null, payment_status: null, is_me: false },
        { name: "Ravi Rao", metric_value: 35, progress: { calls_logged: 35 }, meets_member_minimum: false, won: null, prize_paise: null, payment_status: null, is_me: false },
      ],
    },
  });
  await page.route("**/api/v1/manager/teams", (route) =>
    route.fulfill({
      json: {
        teams: [
          {
            id: "20000000-0000-4000-8000-000000000001",
            name: "North callers",
            business_line: "loans",
            member_role: "telecaller",
            manager: { staff_profile_uuid: "30000000-0000-4000-8000-000000000009", first_name: "Meera", last_name: "Rao", staff_code: "SA-1", status: "active", business_line: null },
            members: [],
            archived_at: null,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: "2026-11-01T00:00:00Z",
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/my-contests**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/api/v1/my-contests/${TEAM}`) return route.fulfill({ json: managerDetail });
    return route.fulfill({ json: { contests: [managerDetail] } });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/team", { waitUntil: "domcontentloaded" });
  const panel = page.locator("section", { hasText: "Team contests" });
  await expect(panel.getByText("Personal loan sprint")).toBeVisible();
  await panel.getByRole("button", { name: "Show progress" }).click();
  await expect(panel.getByRole("list", { name: "Member contributions" }).getByText("Asha Rao")).toBeVisible();
  await expect(panel.getByText("Above the minimum")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
});
