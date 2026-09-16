import { expect, test } from "@playwright/test";

// Run against an env-free web build backed by the release catalogue fixture
// with --sponsor. The opt-in keeps other suites' empty campaign scenario intact.
test.describe("homepage sponsor curtain reveal", () => {
  test.skip(process.env.PLAYWRIGHT_SPONSOR_FIXTURE !== "1", "Requires the opt-in --sponsor server-side catalogue fixture.");
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const motion = { starts: 0, ends: 0, heights: [] as number[] };
      Object.assign(window, { sponsorMotion: motion });
      for (const name of ["animationstart", "animationend"]) {
        document.addEventListener(name, (event) => {
          if (!(event as AnimationEvent).animationName.startsWith("sponsorCurtain")) return;
          if (name === "animationstart") motion.starts++;
          else motion.ends++;
          const ad = document.querySelector('[data-layout="ad-strip"]');
          if (ad) motion.heights.push(ad.getBoundingClientRect().height);
        });
      }
    });
  });

  for (const width of [320, 390, 768, 1440]) {
    test(`artwork, copy and controls fit at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 960 });
      await page.goto("/");
      const ad = page.getByRole("region", { name: "Sponsored", exact: true });
      await expect(ad.getByText("A little planning. A bigger possibility.")).toBeVisible();
      await expect(ad.locator("img")).toBeVisible();
      await expect.poll(() => ad.locator("img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
      const action = ad.getByRole("link", { name: "Explore options" });
      await expect(action).toBeVisible();
      const bounds = await action.boundingBox();
      expect(bounds!.height).toBeGreaterThanOrEqual(44);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await expect(ad.locator("h1,h2,h3,h4,h5,h6")).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(ad.getByRole("button")).toHaveCount(0);
      await expect(page.locator('[aria-roledescription="carousel"]')).toBeVisible();
    });
  }

  test("opens once without moving the ad, including when hydration is unavailable", async ({ page }) => {
    await page.route("**/*.js*", (route) => route.abort());
    await page.goto("/");
    const motion = () => page.evaluate(() => (window as unknown as {
      sponsorMotion: { starts: number; ends: number; heights: number[] };
    }).sponsorMotion);
    await expect.poll(async () => (await motion()).ends).toBe(2);
    const measured = await motion();
    expect(measured.starts).toBe(2);
    expect(new Set(measured.heights).size).toBe(1);
    const curtains = page.locator(".sponsor-curtain");
    expect(await curtains.evaluateAll((panels) => panels.map((panel) => {
      const style = getComputedStyle(panel);
      return [style.animationDuration, style.animationIterationCount, style.pointerEvents];
    }))).toEqual([["0.8s", "1", "none"], ["0.8s", "1", "none"]]);
    await expect(page.getByRole("link", { name: "Explore options" })).toBeVisible();
    // No animation remains running or holds a forwards-fill layer after entry.
    expect(await curtains.evaluateAll((panels) => panels.flatMap((panel) => panel.getAnimations()).length)).toBe(0);
  });

  test("reduced motion shows the completed ad and its CTA works", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.locator(".sponsor-curtain-left")).toBeHidden();
    await expect(page.locator(".sponsor-curtain-right")).toBeHidden();
    await page.getByRole("link", { name: "Explore options" }).click();
    await expect(page).toHaveURL(/\/loans$/);
  });

  test("keyboard focus cancels the reveal without replay on blur", async ({ page }) => {
    await page.addInitScript(() => {
      document.addEventListener("animationstart", (event) => {
        if (!(event as AnimationEvent).animationName.startsWith("sponsorCurtain")) return;
        for (const animation of (event.target as Element).getAnimations()) animation.pause();
      });
    });
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    const stage = ad.locator(".sponsor-stage");
    const action = ad.getByRole("link", { name: "Explore options" });
    await expect(stage).toHaveAttribute("data-reveal", "curtain");
    await action.focus();
    await expect(action).toBeFocused();
    await expect(stage).toHaveAttribute("data-reveal", "none");
    await page.keyboard.press("Tab");
    await expect(stage).toHaveAttribute("data-reveal", "none");
    await expect(ad.locator(".sponsor-curtain-left")).toBeHidden();
  });

  test("failed artwork keeps readable copy and the campaign link", async ({ page }) => {
    await page.route("**/banner-templates/homepage_ad/*.webp", (route) => route.abort());
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    await expect(ad.locator("img")).toHaveCount(0);
    await expect(ad.getByRole("link", { name: "Explore options" })).toBeVisible();
    await expect(ad.getByRole("button")).toHaveCount(0);
  });

  test("client navigation does not replay, but a reload opens the curtains again", async ({ page }) => {
    await page.goto("/");
    const stage = page.locator(".sponsor-stage");
    const starts = () => page.evaluate(() => (window as unknown as { sponsorMotion: { starts: number } }).sponsorMotion.starts);
    await expect.poll(starts).toBe(2);
    await expect(stage).toHaveAttribute("data-reveal", "none");
    await page.getByRole("link", { name: "Explore options" }).click();
    await expect(page).toHaveURL(/\/loans$/);
    await page.getByRole("link", { name: "Dhanadhara home", exact: true }).first().click();
    await expect(stage).toHaveAttribute("data-reveal", "none");
    expect(await starts()).toBe(2);
    await page.reload();
    await expect.poll(starts).toBe(2);
    await expect(stage).toHaveAttribute("data-reveal", "none");
  });

  test("changing motion preferences after completion does not replay", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".sponsor-stage")).toHaveAttribute("data-reveal", "none");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expect(page.locator(".sponsor-curtain-left")).toBeHidden();
  });

  test("long copy reflows without clipping at mobile and desktop sizes", async ({ page }) => {
    await page.goto("/");
    const ad = page.getByRole("region", { name: "Sponsored", exact: true });
    // Layout stress case: vary the text of the real rendered component without
    // changing campaign data or publishing a fixture through the CMS.
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
