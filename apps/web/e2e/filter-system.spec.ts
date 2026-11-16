import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. The shared dashboard filter system (CS-021): field
// names on unfiltered selects, "More filters (n)" as a popover on desktop and
// a bottom sheet on phones, removable chips, From / To dates, and the default
// lead order that keeps closed leads off the first rows.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

function lead(id: string, name: string, patch: Record<string, unknown>) {
  return {
    id,
    name,
    mobile: "+919876543210",
    business_line: "loans",
    status: "working",
    requirement: null,
    last_disposition: null,
    last_interest_level: null,
    next_follow_up_at: null,
    created_at: "2026-11-12T04:00:00Z",
    updated_at: "2026-11-14T08:45:00Z",
    latest_request: null,
    loan_statuses: [],
    referrer: null,
    ...patch,
  };
}

const LEADS = [
  lead("65000000-0000-4000-8000-0000000000b1", "Closed Lead", { status: "closed" }),
  lead("65000000-0000-4000-8000-0000000000b2", "Working Later", {
    next_follow_up_at: "2026-12-20T09:00:00Z",
    last_interest_level: "hot",
  }),
  lead("65000000-0000-4000-8000-0000000000b3", "Released Lead", { status: "released" }),
  lead("65000000-0000-4000-8000-0000000000b4", "Working Sooner", {
    next_follow_up_at: "2026-12-01T09:00:00Z",
    referrer: { kind: "agent", reference_id: "AG-1234ABCD" },
  }),
  lead("65000000-0000-4000-8000-0000000000b5", "New Lead", { status: "new" }),
];

async function openLeads(page: Page, baseURL: string) {
  await mockMobileApi(page, "telecaller", "loans");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
  await page.route("**/api/v1/telecaller/leads", (route) => route.fulfill({ json: LEADS }));
  await page.goto("/dashboard/leads", { waitUntil: "domcontentloaded" });
  await expect(page.locator("tbody tr")).toHaveCount(5);
}

const names = (page: Page) => page.locator("tbody tr td:first-child p.font-medium").allTextContents();

test("leads open in status order with closed work last, and filters read their field names", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openLeads(page, baseURL!);

  expect(await names(page)).toEqual(["New Lead", "Working Sooner", "Working Later", "Closed Lead", "Released Lead"]);

  const status = page.getByRole("combobox", { name: "Filter by status" });
  await expect(status).toHaveText("Status");
  await status.click();
  await expect(page.getByRole("option").first()).toHaveText("All");
  await page.keyboard.press("Escape");
  await expect(page.getByLabel("Follow-up from date")).toBeVisible();
  await expect(page.getByText("To", { exact: true })).toBeVisible();

  const more = page.getByRole("button", { name: "More filters" });
  await more.click();
  const dialog = page.getByRole("dialog", { name: "More filters" });
  await expect(dialog.getByRole("group", { name: "Lead" })).toBeVisible();
  await expect(dialog.getByRole("group", { name: "Loan" })).toBeVisible();
  await expect(dialog.getByRole("combobox", { name: "Filter by lead source" })).toHaveText("Lead source");
  await dialog.getByRole("combobox", { name: "Filter by lead source" }).click();
  await expect(page.getByRole("option")).toHaveText(["All", "Direct lead", "Referred by agent", "Referred by client"]);
  await page.getByRole("option", { name: "Referred by agent" }).click();
  await dialog.getByRole("combobox", { name: "Filter by lead interest" }).click();
  await page.getByRole("option", { name: "Hot" }).click();
  await expect(page.getByRole("heading", { name: "No leads match your filters" })).toBeVisible();
  await page.keyboard.press("Escape");

  await expect(page.getByRole("button", { name: "More filters (2)" })).toBeVisible();
  const chips = page.getByRole("list", { name: "Active filters" });
  await expect(chips.getByRole("listitem")).toHaveCount(2);
  await page.getByRole("button", { name: "Remove filter Lead interest: Hot" }).click();
  expect(await names(page)).toEqual(["Working Sooner"]);
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(5);
  await expect(page.getByRole("button", { name: "More filters" })).toBeVisible();
});

for (const colorScheme of ["light", "dark"] as const) {
  for (const width of [1440, 390]) {
    test(`filter bar layout at ${width}px in ${colorScheme} mode`, async ({ page, baseURL }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
      await openLeads(page, baseURL!);
      await page.getByRole("button", { name: "More filters" }).click();
      const dialog = page.getByRole("dialog", { name: "More filters" });
      await dialog.getByRole("combobox", { name: "Filter by call status" }).click();
      await page.getByRole("option", { name: "Not called yet" }).click();
      await page.screenshot({ path: testInfo.outputPath(`filters-open-${colorScheme}-${width}.png`) });
      if (width < 600) {
        // Phones get a bottom sheet with its own Done button.
        await dialog.getByRole("button", { name: "Done" }).click();
      } else {
        await page.keyboard.press("Escape");
      }
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole("list", { name: "Active filters" })).toContainText("Call status: Not called yet");
      // The filter bar itself fits the viewport (the lead table scrolls on its own).
      const bar = await page.getByRole("region", { name: "Filters" }).boundingBox();
      expect((bar?.x ?? 0) + (bar?.width ?? 0)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: testInfo.outputPath(`filters-chips-${colorScheme}-${width}.png`), fullPage: true });
    });
  }
}
