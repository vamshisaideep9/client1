import { expect, test } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. The Telecaller home greets the signed-in person by
// first name (the fixture profile is "Mobile Reviewer").
test.setTimeout(120_000);

test("the Telecaller home greets by first name", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await mockMobileApi(page, "telecaller");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  const main = page.locator("main");
  await expect(main.getByRole("heading", { level: 1, name: "Hi, Mobile" })).toBeVisible();
  await expect(main.getByText("Welcome to your workspace.")).toBeVisible();
  await expect(main.getByText("Lead follow-up workspace")).toHaveCount(0);
});
