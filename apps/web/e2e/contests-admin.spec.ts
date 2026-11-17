import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only (CS-027): Sub Admin contest authoring and the
// platform Admin's approval, winners and prize desk. No live backend.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const NOW = "2026-11-17T09:30:00Z";
const DRAFT = "50000000-0000-4000-8000-000000000001";
const PENDING = "50000000-0000-4000-8000-000000000002";
const FINAL = "50000000-0000-4000-8000-000000000003";
const AGENT_RESULT = "60000000-0000-4000-8000-000000000001";
const STAFF_RESULT = "60000000-0000-4000-8000-000000000002";

function contest(id: string, status: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: "Personal loan sprint",
    description: "Disburse personal loans this month.",
    terms: "Prizes are paid after the end date.",
    business_line: "loans",
    audience: "agent",
    team_member_role: null,
    metric: "amount",
    criteria: {
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
      eligibility: { min_tenure_days: 0, kyc_verified: true },
    },
    win_mode: "threshold",
    top_n: null,
    prize_paise: 1000000,
    manager_prize_paise: null,
    member_prize_paise: null,
    member_min_contribution: null,
    budget_cap_paise: null,
    starts_on: "2026-12-01",
    ends_on: "2026-12-31",
    status,
    created_by_uuid: "70000000-0000-4000-8000-000000000001",
    created_by_name: "Meera Rao",
    is_mine: true,
    submitted_at: null,
    checker_name: null,
    reviewed_at: null,
    review_note: null,
    live_at: null,
    ended_at: null,
    finalized_at: null,
    cancelled_at: null,
    cancel_reason: null,
    version: 1,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

function standingRow(overrides: Record<string, unknown>) {
  return {
    result_id: AGENT_RESULT,
    kind: "individual",
    participant_type: "agent",
    agent_profile_uuid: "80000000-0000-4000-8000-000000000001",
    name: "Asha Rao",
    team_name: null,
    rank: 1,
    metric_value: 650000000,
    achieved_count: 4,
    achieved_amount_paise: 650000000,
    progress: { count: 4, amount_paise: 650000000 },
    qualified: true,
    won: true,
    prize_paise: 1000000,
    excluded_reason: null,
    payment_status: "unpaid",
    payout_uuid: null,
    paid_reference: null,
    paid_marked_at: null,
    ...overrides,
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

test("a Sub Admin drafts a contest, sees the at-most rule and submits it", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "sub_admin");
  const bodies: Record<string, unknown>[] = [];
  let rows = [contest(DRAFT, "draft", { title: "Existing draft" })];
  await page.route("**/api/v1/loans/banks", (route) => route.fulfill({ json: { banks: [] } }));
  await page.route("**/api/v1/contests**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === "/api/v1/contests" && method === "GET") {
      return route.fulfill({ json: { contests: rows, total: rows.length } });
    }
    if (url.pathname === "/api/v1/contests" && method === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      bodies.push(body);
      const created = contest(PENDING, "draft", { ...body, criteria: body.criteria });
      rows = [created, ...rows];
      return route.fulfill({ status: 201, json: created });
    }
    if (url.pathname.endsWith("/submit")) {
      rows = rows.map((row) => (row.id === PENDING ? { ...row, status: "pending_approval" } : row));
      return route.fulfill({ json: rows.find((row) => row.id === PENDING) });
    }
    return route.fallback();
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/contests", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Contests", exact: true })).toBeVisible();
  await expect(page.getByText("Existing draft")).toBeVisible();

  await page.getByRole("button", { name: "New contest" }).click();
  const dialog = page.getByRole("dialog", { name: "New contest" });
  await dialog.getByLabel("Title").fill("December disbursals");
  await dialog.getByLabel("Cases, at most (optional)").fill("5");
  await dialog.getByLabel("Prize per winner").fill("10000");
  await dialog.getByRole("button", { name: "Save draft" }).click();
  await expect(dialog.getByText(/rewards doing less/)).toBeVisible();
  expect(bodies).toHaveLength(0);

  await dialog.getByLabel("Cases, at least").fill("1");
  await dialog.getByLabel("Total amount, at least").fill("50,00,000");
  await dialog.getByRole("button", { name: "Save draft" }).click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).toMatchObject({
    title: "December disbursals",
    audience: "agent",
    prize_paise: 1000000,
    criteria: { version: 1, loans: { count_at_least: 1, count_at_most: 5, amount_at_least_paise: 500000000 } },
  });

  const detail = page.getByRole("dialog", { name: /December disbursals/ });
  await expect(detail.getByText("Each winner gets ₹10,000.")).toBeVisible();
  await detail.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Submitted for approval")).toBeVisible();

  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
});

test("the Admin approves, confirms winners and pays or records prizes", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "admin");
  const calls: string[] = [];
  let rows = [
    contest(PENDING, "pending_approval", { is_mine: false, title: "December disbursals" }),
    contest(FINAL, "finalized", {
      is_mine: false,
      title: "November sprint",
      audience: "team",
      team_member_role: "telecaller",
      metric: "calls_logged",
      criteria: { version: 1, loans: null, real_estate: null, activity: { calls_logged_at_least: 100 }, eligibility: { min_tenure_days: 0, kyc_verified: false } },
      prize_paise: null,
      manager_prize_paise: 500000,
      member_prize_paise: 100000,
      member_min_contribution: 40,
      checker_name: "Arun Admin",
    }),
  ];
  await page.route("**/api/v1/contests**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    calls.push(`${method} ${url.pathname}`);
    if (url.pathname === "/api/v1/contests" && method === "GET") {
      return route.fulfill({ json: { contests: rows, total: rows.length } });
    }
    if (url.pathname.endsWith("/approve")) {
      rows = rows.map((row) => (row.id === PENDING ? { ...row, status: "approved" } : row));
      return route.fulfill({ json: rows[0] });
    }
    if (url.pathname.endsWith("/standings")) {
      return route.fulfill({
        json: {
          contest: rows[1],
          source: "snapshot",
          computed_at: NOW,
          rows: [standingRow({ kind: "team", participant_type: "team", name: "North callers", agent_profile_uuid: null, result_id: "60000000-0000-4000-8000-000000000009", prize_paise: 0, payment_status: "none", metric_value: 160 })],
          team_people: [
            standingRow({ result_id: STAFF_RESULT, kind: "team_manager", participant_type: "staff", agent_profile_uuid: null, name: "Meera Rao", team_name: "North callers", metric_value: 160, prize_paise: 500000 }),
            standingRow({ result_id: AGENT_RESULT, kind: "team_member", participant_type: "staff", agent_profile_uuid: null, name: "Bala Rao", team_name: "North callers", metric_value: 30, won: false, prize_paise: 0, payment_status: "none", excluded_reason: "below_member_minimum" }),
          ],
          winners: 1,
          prize_total_paise: 500000,
          paid_total_paise: 0,
        },
      });
    }
    if (url.pathname.endsWith("/mark-paid")) {
      return route.fulfill({ json: { result_id: STAFF_RESULT, payment_status: "paid", paid_marked_at: NOW, paid_reference: "November payroll" } });
    }
    return route.fallback();
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/contest-approvals", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Contest approvals" })).toBeVisible();
  await expect(page.getByText("1 waiting on you")).toBeVisible();
  await page.getByText("December disbursals").click();
  const review = page.getByRole("dialog", { name: /December disbursals/ });
  await expect(review.getByText("Between 1 case and 5 cases.")).toBeVisible();
  await review.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Contest approved")).toBeVisible();
  expect(calls).toContain(`POST /api/v1/contests/${PENDING}/approve`);
  await page.keyboard.press("Escape");

  await page.getByRole("tab", { name: /Closed/ }).click();
  await page.getByText("November sprint").click();
  const winners = page.getByRole("dialog", { name: /November sprint/ });
  await expect(winners.getByText("Winners and prizes")).toBeVisible();
  await expect(winners.getByText("Below the member minimum")).toBeVisible();
  await winners.getByRole("button", { name: "Mark paid" }).click();
  await page.getByLabel(/How it was paid/).fill("November payroll");
  await page.getByRole("button", { name: "Mark paid" }).last().click();
  await expect.poll(() => calls.some((call) => call.endsWith(`/results/${STAFF_RESULT}/mark-paid`))).toBe(true);

  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
});
