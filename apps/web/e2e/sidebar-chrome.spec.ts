import { expect, test } from "@playwright/test";
import { mockMobileApi } from "./helpers/mobile-fixtures";

test.use({ contextOptions: { reducedMotion: "reduce" } });
test.beforeEach(async ({ page }) => { await page.emulateMedia({ reducedMotion: "reduce" }); });

for (const role of ["client", "admin", "sub_admin", "agent", "employee", "telecaller"] as const) {
  test(`${role} sidebar logo, toggle and scrollbars stay aligned`, async ({ page, baseURL }, testInfo) => {
    await mockMobileApi(page, role);
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width: 1365, height: 844 });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    const sidebar = page.locator("aside").getByRole("navigation", { name: "Workspace" });
    const logo = sidebar.getByRole("link", { name: "Dhanadhara dashboard" });
    await expect(logo).toBeVisible();
    if (role === "client") {
      const collapsed = await logo.boundingBox();
      const expand = sidebar.getByRole("button", { name: "Expand sidebar" });
      expect((await expand.boundingBox())!.y).toBeGreaterThan(collapsed!.y + collapsed!.height);
      await expand.click();
      const collapse = sidebar.getByRole("button", { name: "Collapse sidebar" });
      await expect(collapse).toBeVisible();
      await expect(logo.locator('img[src*="logo-horizontal.png"]')).toHaveCSS("opacity", "1");
      await expect(logo.locator("img")).toHaveCount(2);
      const expandedLogo = await logo.boundingBox();
      const toggle = await collapse.boundingBox();
      expect(expandedLogo!.x + expandedLogo!.width).toBeLessThanOrEqual(toggle!.x + 1);
      expect(Math.abs(toggle!.y - expandedLogo!.y)).toBeLessThan(2);
      expect(toggle!.width).toBeGreaterThanOrEqual(44);
      await page.screenshot({ path: testInfo.outputPath("client-expanded.png"), animations: "disabled" });
      await collapse.focus();
      await page.keyboard.press("Enter");
      await expect(expand).toBeFocused();
      expect((await logo.boundingBox())!.width).toBe(collapsed!.width);
    } else {
      await expect(logo).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      const horizontal = logo.locator('img[src*="logo-horizontal.png"]');
      await expect(horizontal).toHaveCSS("filter", "none");
      await expect(horizontal).toHaveCSS("width", "176px");
      await expect(horizontal).toHaveCSS("opacity", "1");
      // Operational roles start expanded and can collapse like the Client.
      const collapse = sidebar.getByRole("button", { name: "Collapse sidebar" });
      await expect(collapse).toBeVisible();
      const toggle = (await collapse.boundingBox())!;
      const expandedLogo = (await logo.boundingBox())!;
      expect(expandedLogo.x + expandedLogo.width).toBeLessThanOrEqual(toggle.x + 1);
      expect(toggle.width).toBeGreaterThanOrEqual(44);
      await collapse.focus();
      await page.keyboard.press("Enter");
      const expand = sidebar.getByRole("button", { name: "Expand sidebar" });
      await expect(expand).toBeFocused();
      await expect(horizontal).toHaveCSS("opacity", "0");
      await page.keyboard.press("Enter");
      await expect(collapse).toBeFocused();
    }
    const scroller = sidebar.locator("[data-sidebar-scroll]");
    await expect(scroller).toHaveCSS("scrollbar-width", "thin");
    await page.mouse.move(1300, 820);
    // Muted grey thumb at 40% on the white rail.
    await expect(scroller).toHaveCSS("scrollbar-color", "color(srgb 0.360784 0.360784 0.360784 / 0.4) rgba(0, 0, 0, 0)");
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({ width, height: 568 });
      await page.getByRole("button", { name: "Open menu", exact: true }).click();
      const drawer = page.getByRole("dialog");
      await expect(drawer).toHaveCSS("animation-name", "none");
      const mobileLogo = drawer.getByRole("link", { name: "Dhanadhara dashboard" });
      // Opening the drawer can place its logo under the menu-button pointer.
      // Check its resting treatment separately from the intended hover feedback.
      await page.mouse.move(width - 2, 566);
      await expect(mobileLogo).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      await expect(mobileLogo.locator('img[src*="logo-horizontal.png"]')).toHaveCSS("filter", "none");
      await mobileLogo.hover();
      await expect(mobileLogo).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      await expect(mobileLogo.locator('img[src*="logo-horizontal.png"]')).toHaveCSS("filter", "none");
      await page.mouse.move(width - 2, 566);
      await page.screenshot({ path: testInfo.outputPath(`${role}-${width}.png`), animations: "disabled" });
      await drawer.getByRole("button", { name: "Close", exact: true }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await page.emulateMedia({ forcedColors: "active" });
    await expect(page.locator("html")).toHaveCSS("scrollbar-width", "auto");
    await expect(page.locator("html")).toHaveCSS("scrollbar-color", "auto");
  });
}

test("native scrollbars stay thin in pages, form dialogs and horizontal tables", async ({ page, baseURL }) => {
  await page.goto("/loans", { waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveCSS("scrollbar-width", "thin");
  await mockMobileApi(page, "admin");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.goto("/dashboard/support-tickets", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#dashboard-main-content")).toBeVisible();
  await expect(page.locator("table").first().locator("..")).toHaveCSS("scrollbar-width", "thin");
  await page.goto("/dashboard/loan-config", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "New product", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveCSS("scrollbar-width", "thin");
  await expect(dialog).toHaveCSS("scrollbar-color", "rgb(127, 137, 156) rgba(0, 0, 0, 0)");
});
