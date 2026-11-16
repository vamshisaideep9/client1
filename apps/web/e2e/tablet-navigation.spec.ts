import { expect, test, type Page } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";

// iPad widths: mini/portrait (768), Air portrait (820), landscape / Pro portrait (1024).
const TABLET_WIDTHS = [768, 820, 1024] as const;

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

for (const width of TABLET_WIDTHS) {
  test(`public header shows the full navigation on a ${width}px tablet`, async ({ page }, testInfo) => {
    await mockMobileApi(page);
    await page.setViewportSize({ width, height: 1024 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const header = page.locator("header").first();

    await expect(header.getByRole("button", { name: "Open menu", exact: true })).toBeHidden();
    // Items render as links or mega-menu triggers depending on published
    // content, so match the visible label inside the main navigation.
    const nav = header.getByRole("navigation", { name: "Main" });
    for (const label of ["Home", "Financial Services", "Properties", "Calculators", "Earn with Us", "Become a Partner"]) {
      await expect(nav.getByText(label, { exact: true })).toBeInViewport({ ratio: 1 });
    }
    for (const label of ["Login", "Register", "Contact"]) {
      await expect(header.getByRole("link", { name: label, exact: true })).toBeInViewport();
    }
    await expectNoHorizontalScroll(page);

    // Sticky bars under the header follow its taller tablet height.
    const headerHeight = await header.evaluate((el) => el.getBoundingClientRect().height);
    expect(headerHeight).toBeGreaterThan(100);
    await page.screenshot({ path: testInfo.outputPath(`public-${width}.png`), animations: "disabled" });
  });

  test(`dashboard keeps the sidebar rail instead of the menu button at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await mockMobileApi(page, "telecaller");
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width, height: 1024 });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

    const rail = page.locator("aside").getByRole("navigation", { name: "Workspace" });
    await expect(rail).toBeVisible();
    await expect(page.getByRole("button", { name: "Open menu", exact: true })).toBeHidden();
    // Up to 1024px the rail stays the collapsed icon rail, with no expand toggle.
    if (width < 1024) {
      expect((await rail.boundingBox())!.width).toBeLessThanOrEqual(96);
      await expect(rail.getByRole("button", { name: "Expand sidebar" })).toHaveCount(0);
    }
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: testInfo.outputPath(`dashboard-${width}.png`), animations: "disabled" });
  });
}

test("phones keep the menu button on the public site and dashboard", async ({ page, baseURL }) => {
  await mockMobileApi(page, "telecaller");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("header").first().getByRole("button", { name: "Open menu", exact: true })).toBeVisible();
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Open menu", exact: true })).toBeVisible();
});

test.describe("announcement bar", () => {
  test("home scrolls both lines right-to-left", async ({ page }) => {
    await mockMobileApi(page);
    await page.setViewportSize({ width: 1365, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const bar = page.getByRole("region", { name: "Site announcement" });
    const track = bar.locator(".announcement-track");

    await expect(track).toHaveCSS("animation-name", "announcement-marquee");
    await expect(bar.locator('[data-trust-line="finance"]').first()).toContainText("Loans");
    await expect(bar.locator('[data-trust-line="property"]').first()).toContainText("Real estate");

    // Right-to-left: the track's x position decreases over time.
    const x = () => track.evaluate((el) => el.getBoundingClientRect().x);
    const start = await x();
    await page.waitForTimeout(600);
    expect(await x()).toBeLessThan(start);
  });

  for (const [path, kind] of [["/loans", "finance"], ["/real-estate", "property"]] as const) {
    test(`${path} shows its single line without motion`, async ({ page }) => {
      await mockMobileApi(page);
      await page.setViewportSize({ width: 1365, height: 900 });
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const bar = page.getByRole("region", { name: "Site announcement" });

      await expect(bar.locator(".announcement-track")).toHaveCount(0);
      await expect(bar.locator("[data-trust-line]")).toHaveCount(1);
      await expect(bar.locator(`[data-trust-line="${kind}"]`)).toBeVisible();
    });
  }
});
