import { expect, test } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";

test("staff can clock in and request a half day after Admin setup", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  await page.clock.setFixedTime(new Date("2026-11-21T04:30:00Z"));
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "employee");
  await page.setViewportSize({ width: 390, height: 844 });
  let configured = false;
  let clocked = false;
  let leave: Record<string, unknown> | null = null;
  const day = "2026-11-21";
  const now = "2026-11-21T04:30:00Z";
  const profile = "50000000-0000-4000-8000-000000000001";
  const record = {
    staff_profile_id: profile, day, policy_version: 1, status: "checked_in", source: "clock",
    check_in: now, check_out: null, original_check_in: now, original_check_out: null,
    worked_minutes: 0, late: false, leave_units: 0,
  };
  await page.route("**/api/v1/attendance/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/check-in")) {
      clocked = true;
      return route.fulfill({ json: record });
    }
    if (path.endsWith("/leave")) {
      leave = route.request().postDataJSON();
      return route.fulfill({ status: 201, json: { id: profile, status: "pending", start_day: day } });
    }
    return route.fulfill({ json: {
      policy: configured ? {
        version: 1, effective_from: day, weekly_off: [],
        shift_start_minute: 600, shift_minutes: 480, grace_minutes: 5,
        half_day_minutes: 180, full_day_minutes: 420, leave_quotas: { annual: 10 },
      } : null,
      server_time: now, work_day: day, today: clocked ? record : null,
      days: clocked ? [record] : [], holidays: [], requests: [],
      balance_year: 2026, balances: configured ? [{ leave_type: "annual", allocated_units: 10, used_units: 0 }] : [],
    } });
  });
  await page.goto("/dashboard/attendance", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/Admin setup is pending/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Check in" })).toHaveCount(0);
  configured = true;
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Check in" }).click();
  await expect(page.getByRole("button", { name: "Check out" })).toBeVisible();
  await page.getByRole("button", { name: "Request leave" }).click();
  const dialog = page.getByRole("dialog", { name: "Request leave" });
  await dialog.getByLabel("Half day on one date").check();
  await dialog.getByLabel("Reason").fill("Scheduled appointment");
  await dialog.getByRole("button", { name: "Submit request" }).click();
  await expect(dialog).toBeHidden();
  expect(leave).toMatchObject({ start_day: day, end_day: day, leave_type: "annual", half_day: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});

test("a staff member attaches and downloads private leave evidence", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  const now = "2026-11-21T04:30:00Z";
  const request = "55000000-0000-4000-8000-000000000001";
  await page.clock.setFixedTime(new Date(now));
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "employee");
  await page.setViewportSize({ width: 390, height: 844 });
  const certificate = Buffer.from("%PDF-1.7\nSynthetic browser certificate\n%%EOF");
  let uploaded = false;
  await page.route("**/api/v1/attendance/**", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith(`/requests/${request}/certificate`)) {
      if (route.request().method() === "POST") {
        expect(route.request().headers()["content-type"]).toMatch(/^multipart\/form-data; boundary=/);
        expect(route.request().postDataBuffer()?.includes(certificate)).toBeTruthy();
        uploaded = true;
        return route.fulfill({ status: 204 });
      }
      return route.fulfill({ status: uploaded ? 200 : 404, contentType: "application/pdf", body: uploaded ? certificate : undefined });
    }
    return route.fulfill({ json: {
      policy: { version: 1, effective_from: "2026-11-01", session_clock: true, weekly_off: [6], leave_quotas: { sick: 0 } },
      server_time: now, work_day: "2026-11-21", today: null, days: [], holidays: [], balance_year: 2026,
      balances: [{ leave_type: "sick", allocated_units: 8, used_units: 2, month: "2026-11-01" }],
      requests: [{ id: request, kind: "leave", leave_type: "sick", status: "pending", two_stage: true, certificate_required: true,
        start_day: "2026-11-21", end_day: "2026-11-24", created_at: now, decisions: [] }],
    } });
  });
  await page.goto("/dashboard/attendance", { waitUntil: "domcontentloaded" });
  await expect(page.getByText(/3 days left of 4 \(November 2026\)/)).toBeVisible();
  await page.getByLabel("Medical certificate (PDF, JPEG or PNG, up to 5 MB)").setInputFiles({ name: "certificate.pdf", mimeType: "application/pdf", buffer: certificate });
  await page.getByRole("button", { name: "Upload certificate" }).click();
  await expect(page.getByText("Certificate uploaded.")).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download certificate" }).click();
  expect((await downloadEvent).suggestedFilename()).toBe("medical-certificate.pdf");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
});
