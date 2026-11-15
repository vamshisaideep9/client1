import { expect, test } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic, mocked API only. CS-018 listing form refinements, as seen by any
// lister (this run uses a Real Estate Agent).
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

test("the listing form shows the refined property fields", async ({ page, baseURL }, testInfo) => {
  await mockMobileApi(page, "agent", "real_estate");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/property-submit", { waitUntil: "domcontentloaded" });

  await expect(page.getByLabel("Property name")).toBeVisible();
  await expect(page.getByText("Listing name")).toHaveCount(0);

  await page.locator("#property-type").click();
  await page.getByRole("option", { name: /gated community/i }).first().click();

  // Configurations include the half sizes.
  await expect(page.getByRole("button", { name: "2.5 BHK" })).toBeVisible();
  await expect(page.getByRole("button", { name: "3.5 BHK" })).toBeVisible();

  // Unit or flat area and undivided share are From-To ranges; UDS has a unit.
  await expect(page.getByRole("group", { name: "Unit or flat area" })).toBeVisible();
  await expect(page.locator("#unit-area-from")).toBeVisible();
  await expect(page.locator("#unit-area-to")).toBeVisible();
  await expect(page.locator("#uds-area-from")).toBeVisible();
  await expect(page.locator("#uds-area-unit")).toBeVisible();
  await expect(page.getByLabel(/Flat facing/)).toBeVisible();
  await expect(page.getByText("Plot facing")).toHaveCount(0);

  // Approval authority is a list with Other, and the number label changed.
  await page.locator("#approval-authority").click();
  for (const name of ["GHMC", "HMDA", "DTCP", "GP", "Other"]) {
    await expect(page.getByRole("option", { name, exact: true })).toBeVisible();
  }
  await page.getByRole("option", { name: "Other", exact: true }).click();
  await expect(page.getByLabel("Approval authority name")).toBeVisible();
  await expect(page.getByLabel(/Local approval number/)).toBeVisible();

  // RERA number only when RERA applies.
  await expect(page.locator("#rera-number")).toHaveCount(0);
  await page.locator("#rera-applicability").click();
  await page.getByRole("option", { name: "RERA applies" }).click();
  await expect(page.locator("#rera-number")).toBeVisible();

  // Pre-defined amenities add to the list with one click.
  const pool = page.getByRole("button", { name: "Swimming pool", exact: true });
  await pool.click();
  await expect(pool).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Remove Swimming pool" })).toBeVisible();

  // The Description section sits above Media, and 360 images take several files.
  const description = page.getByRole("heading", { name: "Description" });
  const media = page.getByRole("heading", { name: "Media and review material" });
  await expect(description).toBeVisible();
  const descriptionBox = (await description.boundingBox())!;
  const mediaBox = (await media.boundingBox())!;
  expect(descriptionBox.y).toBeLessThan(mediaBox.y);
  await expect(page.locator("#about-property")).toBeVisible();
  const panoramaInput = page.locator("#property-panorama");
  await expect(panoramaInput).toHaveAttribute("multiple", "");
  await expect(panoramaInput).toHaveAttribute("accept", /image\/avif/);
  await expect(page.locator("#property-images")).toHaveAttribute("accept", /image\/avif/);

  await page.screenshot({ path: testInfo.outputPath("property-form.png"), fullPage: true });
});
