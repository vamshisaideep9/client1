import { expect, test, type Page } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";

const NOW = "2026-11-21T04:30:00Z";
const STAFF = "51000000-0000-4000-8000-000000000011";
const SERIES = "71000000-0000-4000-8000-000000000011";

test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(150_000);

function day(date: string, extra: Record<string, unknown>) {
  return {
    staff_profile_id: STAFF, day: date, policy_version: 1, status: "present", source: "clock",
    original_check_in: null, original_check_out: null, check_in: `${date}T04:00:00Z`, check_out: `${date}T12:30:00Z`,
    worked_minutes: 480, late: false, leave_units: 0, system_check_out: null, calendar_status: "absent",
    morning_covered: true, afternoon_covered: true, early_exit: false, lop_units: 0, adjustments: [],
    leave_sessions: [], leave_codes: [], leave_badges: [], ...extra,
  };
}

async function signIn(page: Page, baseURL: string) {
  await page.clock.setFixedTime(new Date(NOW));
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await mockMobileApi(page, "admin");
}

test("the monthly grid shares one filter bar and explains every code", async ({ page, baseURL }, info) => {
  await signIn(page, baseURL!);
  const rosterQueries: URLSearchParams[] = [];
  await page.route("**/api/v1/attendance/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/policy")) return route.fulfill({ json: {
      active: { version: 1, effective_from: "2026-01-01", shift_start_minute: 570, shift_minutes: 540, grace_minutes: 15,
        half_day_minutes: 240, full_day_minutes: 480, weekly_off: [6], leave_quotas: { earned: 24 }, session_clock: true },
      scheduled: null, can_configure_leave_rules: false,
    } });
    if (url.pathname.endsWith("/roster")) {
      rosterQueries.push(url.searchParams);
      return route.fulfill({ json: {
        configured: true, total: 1,
        members: [{ staff_profile_id: STAFF, name: "Grid Officer", staff_code: "OF-11", role: "employee",
          department: "loans", product_id: null, sub_admin_groups: [] }],
        days: [
          day("2026-11-03", { early_exit: true }),
          day("2026-11-04", { adjustments: ["holiday_work"], calendar_status: "holiday" }),
          day("2026-11-05", { status: "on_leave", check_in: null, check_out: null, worked_minutes: 0,
            leave_badges: [{ code: "EL", label: "Earned leave" }] }),
          day("2026-11-06", { late: true }),
        ],
      } });
    }
    return route.fulfill({ json: { requests: [], total: 0 } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard/attendance-management", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Monthly grid" }).click();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue("2026-11-01", { timeout: 25_000 });
  await expect(page.getByLabel("To", { exact: true })).toHaveValue("2026-11-21");
  await expect.poll(() => rosterQueries.at(-1)?.get("start")).toBe("2026-11-01");

  const grid = page.getByRole("region", { name: "Monthly attendance grid" });
  await expect(grid.getByText("SD", { exact: true })).toBeVisible();
  await expect(grid.getByText("WOH", { exact: true })).toBeVisible();
  // Each badge announces its own meaning (not the day's status).
  await expect(grid.getByText("Late login", { exact: false })).toHaveCount(1);
  await expect(grid.getByText("Earned leave", { exact: false })).toHaveCount(1);
  const legend = page.getByRole("list", { name: "Attendance codes" });
  for (const meaning of ["Short day (left early)", "Work on holiday", "Late login", "Casual leave", "Earned leave"]) {
    await expect(legend.getByText(meaning, { exact: true })).toBeVisible();
  }

  await page.getByLabel("Role").selectOption({ label: "Loan Officers" });
  await expect.poll(() => rosterQueries.at(-1)?.get("role")).toBe("employee");
  expect(rosterQueries.at(-1)?.get("department")).toBe("loans");
  await expect(page.getByLabel("Department")).toHaveValue("loans");
  await page.getByLabel("Team-wise").selectOption({ label: "Relationship Managers" });
  await expect.poll(() => rosterQueries.at(-1)?.get("sub_admin_group")).toBe("relationship_manager");
  await page.getByLabel("Leave type").selectOption("earned");
  await expect.poll(() => rosterQueries.at(-1)?.get("leave_type")).toBe("earned");
  await page.screenshot({ path: info.outputPath("attendance-grid-1440.png"), fullPage: true });

  // More than 31 days is refused before any request.
  const before = rosterQueries.length;
  await page.getByLabel("From", { exact: true }).fill("2026-09-01");
  await expect(page.getByText("Choose a range of up to 31 days.")).toBeVisible();
  expect(rosterQueries.length).toBe(before);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Daily roster" }).click();
  await expect(page.getByLabel("From", { exact: true })).toHaveValue("2026-11-21");
  await expect(page.getByRole("columnheader", { name: "Login (IST)" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Logout (IST)" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test("holidays have a year view and can repeat every year", async ({ page, baseURL }, info) => {
  await signIn(page, baseURL!);
  let saved: Record<string, unknown> | null = null;
  let stopped = false;
  const yearly = { day: "2026-12-25", name: "Founders day", business_line: null, recurring_id: SERIES,
    repeats_yearly: true, starts_on: "2025-12-25", ends_on: null };
  await page.route("**/api/v1/attendance/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/policy")) return route.fulfill({ json: {
      active: { version: 1, effective_from: "2026-01-01", shift_start_minute: 570, shift_minutes: 540, grace_minutes: 15,
        half_day_minutes: 240, full_day_minutes: 480, weekly_off: [6], leave_quotas: {}, session_clock: false },
      scheduled: null, can_configure_leave_rules: false,
    } });
    if (url.pathname.endsWith(`/holidays/recurring/${SERIES}`)) { stopped = true; return route.fulfill({ status: 204, body: "" }); }
    if (url.pathname.includes("/holidays/") && method === "PUT") {
      saved = route.request().postDataJSON();
      return route.fulfill({ status: 204, body: "" });
    }
    if (url.pathname.endsWith("/holidays")) {
      return route.fulfill({ json: url.searchParams.get("year") ? [
        { day: "2026-08-15", name: "Independence day", business_line: null, recurring_id: null, repeats_yearly: false, starts_on: null, ends_on: null },
        yearly,
      ] : [] });
    }
    return route.fulfill({ json: { configured: true, members: [], days: [], total: 0 } });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/attendance-management", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Policy & holidays" }).click();
  await expect(page.getByText("9h 0m", { exact: true })).toBeVisible({ timeout: 25_000 });
  await page.getByRole("button", { name: "Year", exact: true }).click();
  await expect(page.getByText("Yearly", { exact: true })).toBeVisible();
  await expect(page.getByText(/Independence day/)).toBeVisible();
  await page.getByRole("button", { name: "Stop repeating Founders day" }).click();
  await page.getByRole("button", { name: "Stop repeating", exact: true }).click();
  await expect.poll(() => stopped).toBe(true);
  await expect(page.getByText("The holiday no longer repeats after today.")).toBeVisible();

  await page.getByLabel("Holiday date").fill("2026-12-31");
  await page.getByLabel("Holiday name").fill("Year end");
  await page.getByLabel("Repeat every year").check();
  await page.getByRole("button", { name: "Save holiday" }).click();
  await expect.poll(() => saved).toEqual({ name: "Year end", repeat_yearly: true });
  await expect(page.getByText("Holiday saved. It repeats every year.")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: info.outputPath("attendance-holidays-390.png"), fullPage: true });
});
