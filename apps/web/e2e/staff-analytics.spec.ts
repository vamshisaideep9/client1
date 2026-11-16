import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: the personal analytics page for staff roles.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

function days(count: number) {
  const today = new Date();
  return Array.from({ length: count }, (_, index) => {
    const day = new Date(today);
    day.setDate(today.getDate() - (count - 1 - index));
    const iso = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    return {
      day: iso,
      values: { connected: index % 3, not_reached: index % 2, callback: index % 4 === 0 ? 1 : 0, lost: 0 },
    };
  });
}

function telecallerAnalytics(range: number) {
  return {
    role: "telecaller",
    range_days: range,
    kpis: [
      { key: "calls", label: "Calls logged", value: 48, unit: "count", hint: null },
      { key: "connect_rate", label: "Connect rate", value: 41.7, unit: "percent", hint: "Calls marked connected" },
      { key: "active_leads", label: "Active leads", value: 12, unit: "count", hint: null },
      { key: "converted", label: "Converted", value: 3, unit: "count", hint: null },
      { key: "overdue_follow_ups", label: "Overdue follow-ups", value: 2, unit: "count", hint: null },
    ],
    trend: {
      title: "Calls per day",
      description: "Every call you logged, by outcome.",
      series: [
        { key: "connected", label: "Connected" },
        { key: "not_reached", label: "Not reached" },
        { key: "callback", label: "Callback asked" },
        { key: "lost", label: "Not interested / wrong number" },
      ],
      points: days(range),
    },
    breakdowns: [
      {
        key: "interest",
        title: "Interest on connected calls",
        description: "How interested the client sounded.",
        kind: "share",
        unit: "count",
        items: [
          { key: "warm", label: "Warm", value: 9 },
          { key: "hot", label: "Hot", value: 6 },
          { key: "cold", label: "Cold", value: 5 },
        ],
      },
      {
        key: "request_status",
        title: "Applications by stage",
        description: "Every application, enquiry, visit and deal on your leads.",
        kind: "ranked",
        unit: "count",
        items: [
          { key: "submitted_to_bank", label: "Submitted to bank", value: 7 },
          { key: "docs_collected", label: "Docs collected", value: 4 },
          { key: "sanctioned", label: "Sanctioned", value: 2 },
        ],
      },
    ],
    funnel: {
      title: "Lead funnel",
      description: "All leads assigned to you.",
      steps: [
        { key: "assigned", label: "Assigned", value: 20 },
        { key: "contacted", label: "Contacted", value: 16 },
        { key: "converted", label: "Converted", value: 3 },
      ],
    },
  };
}

async function mockAnalytics(page: Page) {
  await mockMobileApi(page, "telecaller");
  const requested: URLSearchParams[] = [];
  await page.route("**/api/v1/me/analytics*", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    requested.push(params);
    const from = params.get("date_from");
    const to = params.get("date_to");
    const range = from && to ? Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1 : 30;
    await route.fulfill({ json: { ...telecallerAnalytics(range), date_from: from, date_to: to, bucket: "day" } });
  });
  return requested;
}

test("telecaller analytics shows figures, a daily chart and breakdowns", async ({ page, baseURL }, testInfo) => {
  const requested = await mockAnalytics(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/insights", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "My analytics" })).toBeVisible();
  const figures = page.getByRole("region", { name: "Key figures" });
  await expect(figures.getByText("41.7%")).toBeVisible();
  await expect(figures.getByText("Overdue follow-ups")).toBeVisible();

  // The daily chart renders (lazy Recharts) with a legend naming every series.
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  await expect(page.getByRole("list", { name: "Legend" }).first()).toContainText("Callback asked");
  await expect(page.getByText("Submitted to bank")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Lead funnel" })).toBeVisible();
  await expect(page.getByText("15%")).toBeVisible(); // 3 of 20 converted

  // The page opens on the previous calendar month and labels the KPI tiles with it.
  const now = new Date();
  const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const daysInLastMonth = new Date(now.getFullYear(), now.getMonth(), 0).getDate();
  expect(requested[0].get("date_from")).toBe(
    `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, "0")}-01`,
  );
  const monthLabel = new Intl.DateTimeFormat("en-IN", { month: "short", year: "numeric" }).format(lastMonth);
  await expect(figures.getByText(monthLabel).first()).toBeVisible();

  // Table view for readers who cannot rely on color.
  await page.getByText("Show as table").first().click();
  await expect(page.getByRole("table").first().getByRole("row")).toHaveCount(daysInLastMonth + 1);

  // The navigation offers the page to this role.
  await expect(page.locator('nav[aria-label="Workspace"]:visible').getByRole("link", { name: "My analytics" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("analytics-1440.png"), fullPage: true });

  // The calendar range picker replaces the old 7/30/90 toggle.
  const first = requested[0];
  expect(first.get("date_from")).toBeTruthy();
  expect(first.has("days")).toBe(false);
  await page.getByRole("button", { name: /^Date range:/ }).click();
  await expect(page.getByRole("dialog").getByRole("grid").first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("analytics-range-picker.png"), animations: "disabled" });
  await page.getByRole("group", { name: "Quick ranges" }).getByRole("button", { name: "Last 7 days" }).click();
  await expect
    .poll(() => requested.some((params) => {
      const from = params.get("date_from");
      const to = params.get("date_to");
      return Boolean(from && to) && Math.round((Date.parse(to!) - Date.parse(from!)) / 86_400_000) === 6;
    }))
    .toBe(true);
  await expect(page.getByRole("table").first().getByRole("row")).toHaveCount(8);

  // Role filters sit behind "More filters" and travel to the API.
  await page.getByRole("button", { name: "More filters" }).click();
  await page.getByRole("combobox", { name: "Filter by call status" }).click();
  await page.getByRole("option", { name: "Busy", exact: true }).click();
  await expect.poll(() => requested.some((params) => params.get("call_status") === "busy")).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "More filters (1)" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Active filters" })).toContainText("Call status: Busy");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect.poll(() => requested.at(-1)?.has("call_status")).toBe(false);
});

test("analytics fits a 360px phone", async ({ page, baseURL }, testInfo) => {
  await mockAnalytics(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/dashboard/insights", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: testInfo.outputPath("analytics-360.png"), fullPage: true });
});

function subAdminAnalytics(from: string | null, to: string | null) {
  return {
    role: "sub_admin",
    range_days: 30,
    date_from: from,
    date_to: to,
    bucket: "day",
    kpis: [
      { key: "created", label: "Content created", value: 6, unit: "count", hint: null },
      { key: "live", label: "Live now", value: 2, unit: "count", hint: null },
      { key: "pending", label: "Awaiting approval", value: 1, unit: "count", hint: null },
      { key: "approval_rate", label: "Approval rate", value: 75, unit: "percent", hint: "Of your banners and offers that were reviewed" },
    ],
    trend: {
      title: "Content created per day",
      description: "Banners and offers you created.",
      series: [
        { key: "banners", label: "Banners" },
        { key: "offers", label: "Offers" },
      ],
      points: days(30).map((point, index) => ({ day: point.day, values: { banners: index % 2, offers: index % 3 === 0 ? 1 : 0 } })),
    },
    breakdowns: [
      {
        key: "banner_status",
        title: "Your banners by status",
        description: "Every banner you created.",
        kind: "share",
        unit: "count",
        items: [{ key: "live", label: "Live", value: 2 }],
      },
      {
        key: "offer_status",
        title: "Your offers by status",
        description: "Every offer you created.",
        kind: "ranked",
        unit: "count",
        items: [{ key: "active", label: "Active", value: 1 }],
      },
    ],
    funnel: null,
  };
}

test("sub admin analytics filters content by status, placement and type", async ({ page, baseURL }, testInfo) => {
  await mockMobileApi(page, "sub_admin");
  const requested: URLSearchParams[] = [];
  await page.route("**/api/v1/me/analytics*", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    requested.push(params);
    await route.fulfill({ json: subAdminAnalytics(params.get("date_from"), params.get("date_to")) });
  });
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/dashboard/insights", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("region", { name: "Key figures" }).getByText("Content created")).toBeVisible();

  // Review status stays in the first row; the content filters sit behind "More filters".
  await page.getByRole("combobox", { name: "Filter by review status" }).click();
  await page.getByRole("option", { name: "Live", exact: true }).click();
  await page.getByRole("button", { name: "More filters" }).click();
  for (const name of ["Content type", "Placement", "Banner type", "Discount type"]) {
    await expect(page.getByRole("combobox", { name: `Filter by ${name.toLowerCase()}` })).toBeVisible();
  }
  await page.getByRole("combobox", { name: "Filter by placement" }).click();
  await page.getByRole("option", { name: "Homepage", exact: true }).click();
  await expect
    .poll(() => {
      const last = requested.at(-1);
      return `${last?.get("content_status")}|${last?.get("placement")}`;
    })
    .toBe("live|homepage");
  // A placement means banners only, so the offer-only filter goes away.
  await expect(page.getByRole("combobox", { name: "Filter by discount type" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("sub-admin-analytics-filters.png") });

  // Offers have no placement or banner type: picking Offers hides and clears them.
  await page.getByRole("combobox", { name: "Filter by content type" }).click();
  await page.getByRole("option", { name: "Offers", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Filter by placement" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Filter by banner type" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Filter by discount type" })).toBeVisible();
  await expect
    .poll(() => {
      const last = requested.at(-1);
      return `${last?.get("content_type")}|${last?.get("content_status")}|${last?.has("placement")}`;
    })
    .toBe("offers|live|false");

  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect
    .poll(() => {
      const last = requested.at(-1);
      return ["content_type", "content_status", "placement", "banner_type", "discount_type"].some((key) => last?.has(key));
    })
    .toBe(false);
  await page.getByRole("button", { name: "More filters" }).click();
  await expect(page.getByRole("combobox", { name: "Filter by placement" })).toBeVisible();
});

test("clients are sent back to their dashboard", async ({ page, baseURL }) => {
  await mockMobileApi(page, "client");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.goto("/dashboard/insights", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/dashboard$/);
});
