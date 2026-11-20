import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Regression cover for "forms in floating windows
// close by themselves": a form dialog must survive a press outside it (the
// overlay, a toast) and a token refresh that fails for a transient reason,
// while a genuine sign-out still ends the session.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const DRAFT = "50000000-0000-4000-8000-000000000001";

function draft() {
  return {
    id: DRAFT,
    title: "Existing draft",
    description: null,
    terms: null,
    business_line: "loans",
    audience: "agent",
    team_member_role: null,
    metric: "count",
    criteria: {
      version: 1,
      loans: {
        loan_type_ids: [],
        bank_ids: [],
        counted_stage: "disbursed",
        count_at_least: 1,
        count_at_most: null,
        amount_at_least_paise: null,
        case_amount_min_paise: null,
        case_amount_max_paise: null,
      },
      real_estate: null,
      activity: null,
      eligibility: { min_tenure_days: 0, kyc_verified: true },
    },
    win_mode: "threshold",
    top_n: null,
    prize_paise: 100000,
    manager_prize_paise: null,
    member_prize_paise: null,
    member_min_contribution: null,
    budget_cap_paise: null,
    starts_on: "2026-12-01",
    ends_on: "2026-12-31",
    status: "draft",
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
    created_at: "2026-11-17T09:30:00Z",
    updated_at: "2026-11-17T09:30:00Z",
  };
}

type Controls = {
  /** The next N contest requests answer 401, as an expired access token does. */
  expireToken: (count: number) => void;
  /** The next refresh answers with this status instead of a new token. */
  failRefresh: (status: number) => void;
};

async function openContestForm(page: Page, baseURL: string): Promise<Controls> {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await mockMobileApi(page, "sub_admin");
  let expired = 0;
  let refreshStatus: number | null = null;
  await page.route("**/api/v1/auth/refresh", (route) => {
    if (refreshStatus === null) return route.fallback();
    const status = refreshStatus;
    refreshStatus = null;
    return route.fulfill({ status, json: { detail: status === 401 ? "Refresh token expired." : "Unavailable" } });
  });
  await page.route("**/api/v1/loans/banks", (route) => route.fulfill({ json: { banks: [] } }));
  await page.route("**/api/v1/contests**", (route) => {
    if (expired > 0) {
      expired -= 1;
      return route.fulfill({ status: 401, json: { detail: "Token expired." } });
    }
    if (route.request().method() === "GET") {
      return route.fulfill({ json: { contests: [draft()], total: 1 } });
    }
    // Saving is refused, so the form stays open and raises an error toast.
    return route.fulfill({
      status: 422,
      json: { detail: [{ loc: ["body", "title"], msg: "Value error, Pick another title" }] },
    });
  });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/contests", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Contests", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New contest" }).click();
  const dialog = page.getByRole("dialog", { name: "New contest" });
  await dialog.getByLabel("Title").fill("December disbursals");
  await dialog.getByLabel("Cases, at least").fill("1");
  await dialog.getByLabel("Total amount, at least").fill("50,00,000");
  await dialog.getByLabel("Prize per winner").fill("10000");
  return {
    expireToken: (count) => {
      expired = count;
    },
    failRefresh: (status) => {
      refreshStatus = status;
    },
  };
}

test("a form dialog ignores presses outside it and closes only on request", async ({ page, baseURL }) => {
  await openContestForm(page, baseURL!);
  const dialog = page.getByRole("dialog", { name: "New contest" });

  // The overlay beside the dialog.
  await page.mouse.click(8, 450);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Title")).toHaveValue("December disbursals");

  // The form's own error toast, which sits outside the dialog.
  await dialog.getByRole("button", { name: "Save draft" }).click();
  const toast = page.locator("[data-sonner-toast]").filter({ hasText: "Could not save the contest" });
  await expect(toast).toBeVisible();
  await toast.click({ force: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Title")).toHaveValue("December disbursals");

  // Keyboard and the explicit controls still close it.
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: "New contest" }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(dialog).toBeHidden();
});

test("a read-only detail dialog keeps closing on an outside press", async ({ page, baseURL }) => {
  await openContestForm(page, baseURL!);
  await page.keyboard.press("Escape");
  await page.getByText("Existing draft").click();
  const detail = page.getByRole("dialog", { name: /Existing draft/ });
  await expect(detail).toBeVisible();
  await page.mouse.click(8, 450);
  await expect(detail).toBeHidden();
});

test("a transient refresh failure keeps the page and the typed form", async ({ page, baseURL }) => {
  const controls = await openContestForm(page, baseURL!);
  const dialog = page.getByRole("dialog", { name: "New contest" });

  // The access token has expired and the refresh endpoint has a blip.
  controls.expireToken(1);
  controls.failRefresh(503);
  await dialog.getByRole("button", { name: "Save draft" }).click();
  await expect(page.locator("[data-sonner-toast]").first()).toBeVisible();
  await expect(page).toHaveURL(/\/dashboard\/contests$/);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Title")).toHaveValue("December disbursals");

  // A refresh that succeeds rotates the token without touching the form.
  controls.expireToken(1);
  await dialog.getByRole("button", { name: "Save draft" }).click();
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: "Could not save the contest" })).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Title")).toHaveValue("December disbursals");
});

test("a refused refresh still signs the user out", async ({ page, baseURL }) => {
  const controls = await openContestForm(page, baseURL!);
  controls.expireToken(1);
  controls.failRefresh(401);
  await page.getByRole("dialog", { name: "New contest" }).getByRole("button", { name: "Save draft" }).click();
  // Authenticated content must disappear immediately; the public destination
  // can still need a cold dev compilation and its anonymous catalogue reads.
  await expect(page.getByRole("dialog", { name: "New contest" })).toHaveCount(0);
  await expect(page).toHaveURL(`${baseURL}/`, { timeout: 30_000 });
});
