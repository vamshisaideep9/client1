import { expect, test, type Locator } from "@playwright/test";

// Run against an env-free web build backed by the release catalogue fixture
// with --sponsor. The opt-in preserves other suites' empty campaign scenario.
async function expectStaticAd(ad: Locator) {
  await expect(ad.getByText("A little planning. A bigger possibility.")).toBeVisible();
  await expect(ad.getByRole("link", { name: "Explore options" })).toBeVisible();
  await expect(ad.locator("canvas, .sponsor-curtain, [data-reveal]")).toHaveCount(0);
  expect(await ad.evaluate((node) => node.getAnimations({ subtree: true }).length)).toBe(0);
}

test.describe("homepage sponsor highlight", () => {
  test.skip(process.env.PLAYWRIGHT_SPONSOR_FIXTURE !== "1", "Requires the opt-in --sponsor server-side catalogue fixture.");

  for (const width of [320, 390, 768, 1440]) {
    test(`artwork, copy and CTA fit at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 960 });
      await page.goto("/");
      const ad = page.getByRole("region", { name: "Sponsored", exact: true });
      await expectStaticAd(ad);
      await expect(ad.locator("img")).toBeVisible();
      await expect(ad.locator("img")).toHaveCSS("object-fit", "contain");
      await expect.poll(() => ad.locator("img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
      const bounds = await ad.getByRole("link", { name: "Explore options" }).boundingBox();
      expect(bounds!.height).toBeGreaterThanOrEqual(44);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await expect(ad.locator("h1,h2,h3,h4,h5,h6")).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(ad.getByRole("button")).toHaveCount(0);
      await expect(page.locator('[aria-roledescription="carousel"]')).toBeVisible();
    });
  }

  test("the complete ad is visible and usable before hydration", async ({ page }) => {
    // Preserve React's inline streaming reveal, but block all app bundles.
    // The existing route-level loading boundary requires the streaming script.
    await page.route("**/*.js*", (route) => route.abort());
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    await expectStaticAd(ad);
    await ad.getByRole("link", { name: "Explore options" }).click();
    await expect(page).toHaveURL(/\/loans$/);
  });

  test("keyboard focus stays visible and activates the campaign link", async ({ page }) => {
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    const action = ad.getByRole("link", { name: "Explore options" });
    await action.focus();
    await expect(action).toBeFocused();
    expect(await action.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/loans$/);
  });

  test("the full preview catalogue appears in desktop and mobile navigation", async ({ page, request }) => {
    test.skip(process.env.PLAYWRIGHT_FULL_CATALOGUE !== "1", "Requires --full-catalogue preview data.");
    const response = await request.get("/api/v1/public/financial-products?page_size=100");
    expect(response.ok()).toBe(true);
    const { items } = await response.json();
    expect(items).toHaveLength(16);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.goto("/");
      if (width < 1280) {
        await page.locator("header").getByRole("button", { name: "Open menu", exact: true }).click();
        await page.getByRole("dialog").locator("summary").filter({ hasText: "Financial Services" }).click();
      } else {
        await page.locator("header").getByRole("button", { name: "Financial Services", exact: true }).focus();
        await page.keyboard.press("Enter");
      }
      const menu = width < 1280 ? page.getByRole("dialog") : page.locator('[data-slot="navigation-menu-viewport"]');
      for (const product of items) {
        await expect(menu.getByRole("link", { name: product.label, exact: true })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    }
  });

  test("failed artwork keeps readable copy and the campaign link", async ({ page }) => {
    await page.route("**/banner-templates/homepage_ad/*.webp", (route) => route.abort());
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    await expect(ad.locator("img")).toHaveCount(0);
    await expectStaticAd(ad);
  });

  test("navigation, reload and motion preferences keep the ad static", async ({ page }) => {
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    await expectStaticAd(ad);
    await ad.getByRole("link", { name: "Explore options" }).click();
    await expect(page).toHaveURL(/\/loans$/);
    await page.getByRole("link", { name: "Dhanadhara home", exact: true }).first().click();
    await expectStaticAd(ad);
    await page.reload();
    await expectStaticAd(ad);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expectStaticAd(ad);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expectStaticAd(ad);
  });

  test("long copy reflows without clipping at mobile and desktop sizes", async ({ page }) => {
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    // Stress the rendered layout without publishing fixture data through CMS.
    await ad.locator("p").first().evaluate((node) => {
      node.textContent = "Plan a new home, an education or your next business milestone with guidance for every step. ".repeat(3);
    });
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 960 });
      const title = ad.locator("p").first();
      expect(await title.evaluate((node) => node.scrollHeight <= node.clientHeight)).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await expect(ad.getByRole("link", { name: "Explore options" })).toBeVisible();
    }
  });
});
