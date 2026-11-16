import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Admin Analytics: calendar date range plus the
// per-report filters, all carried to the API and to the exports.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const summary = { total_count: 12, converted_count: 3 };

async function mockReports(page: Page) {
  await mockMobileApi(page, "admin");
  const requests: URL[] = [];
  await page.route("**/api/v1/admin/reports/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const path = url.pathname;
    if (path.endsWith("/telecallers")) {
      return route.fulfill({
        json: [{ staff_profile_uuid: "71000000-0000-4000-8000-000000000001", staff_code: "TC-0001", name: "Ravi Kumar", business_line: "loans" }],
      });
    }
    if (path.endsWith("/agents")) {
      return route.fulfill({
        json: {
          rows: [],
          total: 0,
          summary: { agent_count: 0, leads_total: 0, leads_converted: 0, loans_total: 0, loans_converted: 0, deals_total: 0, deals_converted: 0 },
          team_summaries: [],
        },
      });
    }
    return route.fulfill({
      json: {
        rows: [{ bucket_start: "2026-11-10T00:00:00+05:30", business_line: "loans", total: 12, converted: 3 }],
        total: 1,
        summary,
      },
    });
  });
  await page.route("**/api/v1/admin/loan-types", (route) =>
    route.fulfill({ json: { loan_types: [] } }),
  );
  await page.route("**/api/v1/admin/banks", (route) => route.fulfill({ json: { banks: [] } }));
  return requests;
}

const leadsRequests = (requests: URL[]) => requests.filter((url) => url.pathname.endsWith("/reports/leads"));

test("admin analytics filters by calendar range and lead filters", async ({ page, baseURL }, testInfo) => {
  const requests = await mockReports(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/analytics", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("button", { name: /^Date range:/ })).toBeVisible();
  // The native date inputs and the old preset buttons are gone.
  await expect(page.getByLabel("Report from date")).toHaveCount(0);

  await page.getByRole("button", { name: /^Date range:/ }).click();
  await page.getByRole("group", { name: "Quick ranges" }).getByRole("button", { name: "Last month" }).click();
  await expect.poll(() => leadsRequests(requests).some((url) => url.searchParams.get("date_from")?.endsWith("-01"))).toBe(true);

  await page.getByRole("combobox", { name: "Lead source" }).click();
  await page.getByRole("option", { name: "Referred by a client" }).click();
  await expect.poll(() => leadsRequests(requests).at(-1)?.searchParams.get("lead_source")).toBe("client");

  await page.getByRole("combobox", { name: "Telecaller" }).click();
  await page.getByRole("option", { name: "Ravi Kumar (TC-0001)" }).click();
  await expect
    .poll(() => leadsRequests(requests).at(-1)?.searchParams.get("telecaller_profile_uuid"))
    .toBe("71000000-0000-4000-8000-000000000001");

  await page.getByRole("combobox", { name: "Latest call status" }).click();
  await page.getByRole("option", { name: "Busy", exact: true }).click();
  await expect.poll(() => leadsRequests(requests).at(-1)?.searchParams.get("call_status")).toBe("busy");
  await page.screenshot({ path: testInfo.outputPath("admin-analytics-filters.png"), fullPage: true });
});

test("every report tab has charts read from the whole filtered period", async ({ page, baseURL }, testInfo) => {
  const requests = await mockReports(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/analytics", { waitUntil: "domcontentloaded" });

  // Leads: the stacked per-week chart and the conversion-rate line chart.
  await expect(page.getByRole("heading", { name: "Leads per week" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Conversion rate" })).toBeVisible();
  await expect(page.locator(".recharts-surface")).toHaveCount(2);
  // The chart read is separate from the 25-row table page: first 500 rows, oldest first.
  await expect
    .poll(() =>
      leadsRequests(requests).some(
        (url) =>
          url.searchParams.get("limit") === "500" &&
          url.searchParams.get("offset") === "0" &&
          url.searchParams.get("sort_by") === "bucket_start" &&
          url.searchParams.get("sort_dir") === "asc",
      ),
    )
    .toBe(true);
  expect(leadsRequests(requests).some((url) => url.searchParams.get("limit") === "25")).toBe(true);

  // Each chart has a table view; the conversion table shows 3 of 12 as 25%.
  await page.getByText("Show as table").nth(1).click();
  await expect(page.getByRole("table", { name: "Conversion rate" })).toContainText("25%");
  await page.screenshot({ path: testInfo.outputPath("admin-analytics-charts.png"), fullPage: true });

  // Agents: top agents and leads by line, with empty states when nothing matched.
  await page.getByRole("tab", { name: "Agents" }).click();
  await expect(page.getByRole("heading", { name: "Top 10 agents by leads" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Leads by line" })).toBeVisible();
  await expect
    .poll(() =>
      requests.some(
        (url) =>
          url.pathname.endsWith("/reports/agents") &&
          url.searchParams.get("sort_by") === "leads_total" &&
          url.searchParams.get("limit") === "10",
      ),
    )
    .toBe(true);
  await expect(
    page.getByRole("tabpanel", { name: "Agents" }).getByText("No activity in this date range.").first(),
  ).toBeVisible();
});

test("charts fit a 360px phone", async ({ page, baseURL }) => {
  await mockReports(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dashboard/analytics", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
});

test("deals tab offers property filters", async ({ page, baseURL }) => {
  const requests = await mockReports(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/analytics", { waitUntil: "domcontentloaded" });

  await page.getByRole("tab", { name: "Deals" }).click();
  await page.getByRole("combobox", { name: "Property category" }).click();
  await page.getByRole("option", { name: "Villas" }).click();
  await page.getByRole("textbox", { name: "Property city" }).fill("Hyderabad");
  await expect
    .poll(() => {
      const last = requests.filter((url) => url.pathname.endsWith("/reports/deals")).at(-1);
      return last ? `${last.searchParams.get("property_category")}|${last.searchParams.get("property_city")}` : "";
    })
    .toBe("villas|Hyderabad");
});
