import { expect, test } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

test.setTimeout(120_000);

test("public contact shows call and WhatsApp actions and Knowledge Sharing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const response = await page.goto("/contact", { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBe(200);
  const actions = page.locator("main");
  await expect(actions.getByRole("link", { name: /^Call \+91/ })).toHaveAttribute("href", "tel:+919010053010");
  await expect(actions.getByRole("link", { name: "WhatsApp", exact: true })).toHaveAttribute(
    "href", "https://wa.me/919010053010",
  );
  await expect(actions.getByRole("button", { name: "Send message" })).toBeVisible();
  await expect(page.locator("footer").getByRole("link", { name: "WhatsApp" })).toBeVisible();
  await page.getByRole("link", { name: "Knowledge Sharing", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Knowledge Sharing", level: 1 })).toBeVisible({ timeout: 30_000 });
  expect(await page.locator("body").evaluate((body) => body.scrollWidth)).toBeLessThanOrEqual(390);
});

test("public real estate search shares filters in the URL and separates rent from sale budgets", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const response = await page.goto("/real-estate", { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBe(200);
  await page.getByRole("link", { name: "Rent / Lease", exact: true }).click();
  await expect(page.getByLabel("Minimum budget (₹ per month)")).toBeVisible();
  await page.getByLabel("Locality or city").fill("Test locality");
  await page.getByLabel("Bedrooms").selectOption("2");
  await page.getByLabel("Minimum area (sq ft)").fill("800");
  await page.getByLabel("Maximum budget (₹ per month)").fill("30000");
  await page.getByRole("button", { name: "Search properties" }).click();
  await expect(page).toHaveURL(/mode=rent/);
  await expect(page).toHaveURL(/budget_max=30000/);
  await expect(page).toHaveURL(/bhk=2/);
  await expect(page).toHaveURL(/area_min=800/);
  await expect(page.getByText(/propert(?:y|ies) found/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Resale", exact: true }).click();
  await expect(page).toHaveURL(/mode=resale/);
  await expect(page).not.toHaveURL(/budget_max/);
  await expect(page.getByLabel("Maximum budget (₹ total)")).toBeVisible();
});

test("an assigned Sub Admin can save and preview a draft through the dashboard", async ({ page, baseURL }) => {
  await mockMobileApi(page, "sub_admin");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.route("**/api/v1/website-content/access", (route) => route.fulfill({
    json: { can_edit: true, can_publish: false },
  }));
  await page.route("**/api/v1/website-content/documents", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/website-content/documents/page/home", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 404, json: { detail: "Website document not found." } });
      return;
    }
    const { content } = route.request().postDataJSON();
    await route.fulfill({ json: { key: "page/home", draft: content, version: 1, published_revision: null } });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard/website-content", { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("Title", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Title", { exact: true }).fill("Preview homepage");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Draft saved." })).toBeVisible();
  await page.getByRole("button", { name: "Preview draft" }).click();
  await expect(page.getByRole("region", { name: "Private draft preview" }).getByText("Preview homepage")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0);
});
