import { expect, test } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";
import type { AttendanceMonth } from "../lib/attendance-api";

test("platform Admin closes and reopens a month, then sees revisions in Analytics", async ({ page, baseURL }) => {
  test.setTimeout(180_000);
  const now = "2026-11-21T04:30:00Z";
  await page.clock.setFixedTime(new Date(now));
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "admin");
  const month = "2026-10-01";
  const report: AttendanceMonth = { month, can_close: true, revisions: [], totals: [
    { business_line: "loans", worked_minutes: 480, recorded_days: 2, leave_units: 1, sandwich_units: 0, lop_units: 0, late_days: 0, absences: 0 },
  ] };
  await page.route("**/api/v1/attendance/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith(`/months/${month}/close`)) {
      const { expected_version, note } = route.request().postDataJSON();
      expect(expected_version).toBe(report.revisions[0]?.version ?? 0);
      expect(note).toBe("Reviewed the register");
      report.revisions.unshift({ version: expected_version + 1, closed_at: now, reopened_at: null, totals: report.totals });
      report.can_close = false;
      return route.fulfill({ json: report });
    }
    if (path.endsWith(`/months/${month}/reopen`)) {
      expect(route.request().postDataJSON()).toEqual({ expected_version: 1, note: "Late correction" });
      report.revisions[0].reopened_at = now;
      report.totals = [{ ...report.totals[0], worked_minutes: 600 }];
      report.can_close = true;
      return route.fulfill({ json: report });
    }
    if (path.endsWith(`/months/${month}`)) return route.fulfill({ json: report });
    return route.fulfill({ json: { configured: true, members: [], days: [], total: 0 } });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/attendance-management", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Monthly close" }).click();
  await expect(page.getByLabel("Attendance month (IST)")).toHaveValue("2026-10");
  await page.getByRole("button", { name: "Close month", exact: true }).click();
  const closeDialog = page.getByRole("dialog", { name: "Close attendance month" });
  await closeDialog.getByLabel("Reason").fill("Reviewed the register");
  await closeDialog.getByRole("button", { name: "Close month", exact: true }).click();
  await expect(page.getByText("Attendance month closed.")).toBeVisible();
  const reopen = page.getByRole("button", { name: "Reopen month", exact: true });
  await expect(reopen).toBeFocused();
  await reopen.click();
  const reopenDialog = page.getByRole("dialog", { name: "Reopen attendance month" });
  await reopenDialog.getByLabel("Reason").fill("Late correction");
  await reopenDialog.getByRole("button", { name: "Reopen month", exact: true }).click();
  await expect(page.getByText("Attendance month reopened.")).toBeVisible();
  await page.getByLabel("Report version").selectOption("1");
  await expect(page.getByText("Closed revision 1", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard/analytics", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Attendance", exact: true }).click();
  await expect(page.getByRole("region", { name: "Monthly totals by business line" })).toBeVisible();
  await page.getByLabel("Report version").selectOption("1");
  await expect(page.getByText("Closed revision 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Close month", exact: true })).toHaveCount(0);
});
