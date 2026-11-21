import { expect, test } from "@playwright/test";

// Client registration asks for the name as printed on the PAN card. Copy
// only: nothing here validates a PAN. No request reaches a backend.
test("registration labels the name fields as per the PAN card", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => route.fulfill({ status: 404, json: { detail: "Not used" } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/register", { waitUntil: "domcontentloaded" });
  await expect(page.locator("form").first()).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });

  const first = page.getByLabel("First name (as per PAN card)");
  const last = page.getByLabel("Last name (as per PAN card)");
  await expect(first).toBeVisible();
  await expect(last).toBeVisible();
  const hint = "Enter your name exactly as it appears on your PAN card.";
  await expect(page.getByText(hint)).toBeVisible();
  await expect(first).toHaveAccessibleDescription(hint);
  await expect(last).toHaveAccessibleDescription(hint);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
