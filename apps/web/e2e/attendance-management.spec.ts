import { expect, test } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";

const DAY = "2026-11-21";
const NOW = "2026-11-21T04:30:00Z";
const STAFF = "51000000-0000-4000-8000-000000000001";
const REQUEST = "61000000-0000-4000-8000-000000000001";
const REVIEWER = "51000000-0000-4000-8000-000000000002";

test("an Admin configures attendance and reviews a staff leave request", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  await page.clock.setFixedTime(new Date(NOW));
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "admin");
  const leave = {
    id: REQUEST, staff_profile_id: STAFF, kind: "leave", status: "pending",
    start_day: DAY, end_day: DAY, reason: "Appointment",
    leave_type: "annual", half_day: true, requested_check_in: null, requested_check_out: null,
    approved_units: {}, decisions: [], created_at: NOW,
  };
  let configured = false;
  let decision: Record<string, unknown> | null = null;
  let policy: Record<string, unknown> | null = null;
  let assignment: Record<string, unknown> | null = null;
  await page.route("**/api/v1/attendance/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/policy")) {
      if (route.request().method() === "PUT") {
        policy = route.request().postDataJSON();
        configured = true;
      }
      return route.fulfill({ json: {
        active: configured ? { ...policy, version: 1, effective_from: DAY } : null, scheduled: null,
      } });
    }
    if (pathname.endsWith("/holidays")) {
      const line = new URL(route.request().url()).searchParams.get("business_line");
      return route.fulfill({ json: line === "real_estate" ? [{ day: DAY, name: "Real estate holiday" }] : [] });
    }
    if (pathname.endsWith("/employment/reviewers")) return route.fulfill({ json: [
      { staff_profile_id: REVIEWER, name: "Synthetic Reviewer", staff_code: "SA-1", role: "sub_admin" },
    ] });
    if (pathname.endsWith(`/employment/${STAFF}`)) {
      if (route.request().method() === "PUT") assignment = route.request().postDataJSON();
      return route.fulfill({ json: assignment ? { ...assignment, staff_profile_id: STAFF, version: 1 } : null });
    }
    if (pathname.endsWith("/decision")) {
      decision = route.request().postDataJSON();
      return route.fulfill({ json: { ...leave, status: "approved" } });
    }
    if (pathname.endsWith("/requests"))
      return route.fulfill({ json: { requests: decision ? [] : [leave], total: decision ? 0 : 1 } });
    return route.fulfill({ json: {
      configured, members: [{ staff_profile_id: STAFF, name: "Synthetic Staff", staff_code: "ST-1", role: "employee" }],
      total: 1, days: [],
    } });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/attendance-management", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/Admin setup is pending/)).toBeVisible({ timeout: 25_000 });
  const editAssignment = page.getByRole("button", { name: "Edit attendance assignment for Synthetic Staff" });
  await editAssignment.click();
  const assignmentDialog = page.getByRole("dialog", { name: "Attendance assignment" });
  await assignmentDialog.getByLabel("Employment start").fill(DAY);
  await assignmentDialog.getByLabel("Calendar").selectOption("real_estate");
  await assignmentDialog.getByLabel("Direct attendance reviewer (optional)").selectOption(REVIEWER);
  await assignmentDialog.getByRole("button", { name: "Save assignment" }).click();
  await expect(editAssignment).toBeFocused();
  await expect(page.getByText("Attendance assignment saved.")).toBeVisible();
  expect(assignment).toEqual({ start_day: DAY, end_day: null, business_line: "real_estate", reviewer_id: REVIEWER, expected_version: 0 });
  await page.getByRole("tab", { name: "Policy & holidays" }).click();
  await page.getByLabel("Calendar", { exact: true }).selectOption("real_estate");
  await expect(page.getByText(/Real estate holiday/)).toBeVisible();
  await expect(page.getByLabel("Shift start (IST)")).toHaveValue("09:30");
  await page.getByLabel("Shift start (IST)").fill("09:00");
  await page.getByLabel("Shift duration (minutes)").fill("480");
  await page.getByLabel("Grace period (minutes)").fill("10");
  await page.getByLabel("Half-day minimum (minutes)").fill("180");
  await page.getByLabel("Full-day minimum (minutes)").fill("360");
  await page.getByLabel("Annual leave days by type").fill("annual=12.5");
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.getByText("Attendance is now open.")).toBeVisible();
  expect(policy).toMatchObject({ shift_start_minute: 540, leave_quotas: { annual: 25 } });
  await page.getByRole("tab", { name: "Requests" }).click();
  await page.getByRole("button", { name: "Review", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Leave request" });
  await dialog.getByLabel("Decision", { exact: true }).selectOption("approved");
  await dialog.getByLabel("Review note").fill("Shift coverage confirmed");
  await dialog.getByRole("button", { name: "Save decision" }).click();
  await expect(page.getByText("Attendance decision saved.")).toBeVisible();
  expect(decision).toEqual({ status: "approved", note: "Shift coverage confirmed", expected_decisions: 0, stage: "decision" });
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 850 });
    await page.getByRole("tab", { name: "Monthly grid" }).click();
    await expect(page.getByRole("region", { name: "Monthly attendance grid" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  }
});
