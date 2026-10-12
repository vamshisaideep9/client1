import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const artifact = pathToFileURL(resolve(process.cwd(), "../../build/client-draft/Dhanadhara-Client-Draft.html")).href;
test.beforeEach(async ({ context }, info) => {
  test.skip(!info.project.metadata.clientDraft, "Run with playwright.client-draft.config.ts after export:client.");
  await context.setOffline(true);
});

test("all public routes render offline with embedded artwork and no API traffic", async ({ page }) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
  await page.goto(artifact);
  await expect(page.locator("main h1")).toBeVisible();
  const routes = await page.evaluate(() => window.__DRAFT_ROUTES__);
  expect(routes.filter(route => route.startsWith("/calculators/"))).toHaveLength(18);
  expect(routes.filter(route => route.startsWith("/loans/"))).toHaveLength(16);
  for (const route of routes) {
    await page.evaluate(route => { window.location.hash = `#${route}`; }, route);
    await expect(page.locator("main")).toHaveAttribute("data-draft-route", route);
    await expect(page.locator("main h1")).toHaveCount(1);
    await expect(page.locator("main")).not.toContainText("Page unavailable");
    await page.waitForFunction(() => !document.querySelector('main [role="status"]'));
    const brokenImages = await page.locator("img").evaluateAll(images => images.filter((image): image is HTMLImageElement => image instanceof HTMLImageElement).filter(image => image.getBoundingClientRect().width > 0 && image.complete && image.naturalWidth === 0).map(image => image.alt));
    expect(brokenImages, route).toEqual([]);
    expect(errors, route).toEqual([]);
  }
  expect(requests).toEqual([]);
});

test("sponsor, mobile navigation and calculator values work", async ({ page }) => {
  await page.goto(artifact);
  await expect(page.getByText("A little planning. A bigger possibility.")).toBeVisible();
  await page.screenshot({ path: "../../build/client-draft/home-desktop.png", fullPage: true });
  await page.evaluate(() => { window.location.hash = "#/calculators/emi"; });
  await expect(page.locator('input[type="number"]').first()).toBeVisible();
  const before = await page.locator("main").innerText();
  await page.locator('input[type="number"]').first().fill("5000000");
  await page.locator('input[type="number"]').first().press("Enter");
  await expect.poll(() => page.locator("main").innerText()).not.toBe(before);
  await expect(page.locator('input[type="number"]').first()).toBeFocused();
  await page.screenshot({ path: "../../build/client-draft/calculator-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { window.location.hash = "#/"; });
  await expect(page.getByText("A little planning. A bigger possibility.")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../../build/client-draft/home-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Primary mobile" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
});

test("calculator exports and browser history work without a server", async ({ page }) => {
  await page.goto(`${artifact}#/calculators/emi`);
  for (const [button, extension] of [["Download CSV", ".csv"], ["Download Excel", ".xlsx"]]) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: button, exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toContain(extension);
    expect(await file.failure()).toBeNull();
  }
  await page.locator('main a[href="#/calculators"]').first().click();
  await expect(page.locator("main")).toHaveAttribute("data-draft-route", "/calculators");
  await page.goBack();
  await expect(page.locator("main")).toHaveAttribute("data-draft-route", "/calculators/emi");
});

test("forms disclose preview status and cannot report a live submission", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
  await page.goto(`${artifact}#/contact`);
  await expect(page.locator("main form")).toBeVisible();
  await page.locator("main form").evaluate(form => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await expect(page.getByText("Preview only. Nothing was submitted.")).toBeVisible();
  expect(requests).toEqual([]);
});

test("every calculator accepts an edit and remains usable offline", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(artifact);
  const routes = await page.evaluate(() => window.__DRAFT_ROUTES__.filter(route => route.startsWith("/calculators/")));
  for (const route of routes) {
    await page.evaluate(route => { window.location.hash = `#${route}`; }, route);
    await expect(page.locator("main")).toHaveAttribute("data-draft-route", route);
    const input = page.locator('main input[type="number"]').first();
    await expect(input, route).toBeVisible();
    const previous = await input.inputValue();
    await input.fill(String(Number(previous) + 1));
    await input.press("Enter");
    await expect(input, route).not.toHaveValue(previous);
    expect(errors, route).toEqual([]);
  }
});

test("representative pages fit narrow, tablet and desktop viewports", async ({ page }) => {
  await page.goto(artifact);
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ["/", "/loans/personal-loan", "/real-estate", "/calculators/emi", "/contact"]) {
      await page.evaluate(route => { window.location.hash = `#${route}`; }, route);
      await expect(page.locator("main")).toHaveAttribute("data-draft-route", route);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth), `${width}px ${route}`).toBeLessThanOrEqual(1);
    }
  }
});
