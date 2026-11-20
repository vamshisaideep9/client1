import { expect, test } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. On a touch screen the account menu opens with a
// tap and stays open; the desktop hover-open keeps working with a mouse.
test.setTimeout(120_000);

test.describe("on a phone", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 }, contextOptions: { reducedMotion: "reduce" } });

  test("a tap opens the account menu and it stays open", async ({ page, baseURL }) => {
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await mockMobileApi(page, "telecaller");
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    const trigger = page.locator("header").getByRole("button", { name: "Open account menu" });
    await expect(trigger).toBeVisible();

    await trigger.tap();
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    // The old hover-intent close fired on the pointer-leave that ends a tap.
    await page.waitForTimeout(600);
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Settings" })).toBeVisible();
  });
});

test("a mouse still opens the account menu on hover", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "telecaller");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  // The top bar's trigger; the sidebar has its own account control.
  const trigger = page.locator("header").getByRole("button", { name: "Open account menu" });
  await expect(trigger).toBeVisible();
  await trigger.hover();
  await expect(page.getByRole("menu")).toBeVisible();
});
