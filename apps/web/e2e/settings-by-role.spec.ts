import { expect, test } from "@playwright/test";

import type { UserRole } from "@/lib/auth";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. Settings by role (CS-021): Clients, Agents and
// Admins edit their profile and can delete their account; Telecallers,
// Employees and Sub Admins see their details read-only with no Save, no
// personalization card and no Danger zone. Only Clients get the
// personalization card. The API enforces the same rules.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const CASES: { role: UserRole; editable: boolean; personalization: boolean }[] = [
  { role: "client", editable: true, personalization: true },
  { role: "agent", editable: true, personalization: false },
  { role: "admin", editable: true, personalization: false },
  { role: "telecaller", editable: false, personalization: false },
  { role: "employee", editable: false, personalization: false },
  { role: "sub_admin", editable: false, personalization: false },
];

for (const { role, editable, personalization } of CASES) {
  test(`${role} settings follow the role rules`, async ({ page, baseURL }, testInfo) => {
    await mockMobileApi(page, role);
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

    // Shared sections render for every role.
    await expect(page.getByText("Mobile Reviewer").or(page.getByLabel("First name")).first()).toBeVisible();

    if (editable) {
      await expect(page.getByLabel("First name")).toBeEditable();
      await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Danger zone" })).toBeVisible();
    } else {
      const details = page.getByRole("region", { name: "Your details" });
      await expect(details).toContainText("Mobile");
      await expect(details).toContainText("Reviewer");
      await expect(details).toContainText("ask an Admin");
      await expect(page.locator("main").getByRole("textbox")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Danger zone" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Delete account/ })).toHaveCount(0);
    }

    await expect(page.getByRole("heading", { name: /Personali[sz]ed/ })).toHaveCount(personalization ? 1 : 0);

    // Only a Client's name must match their PAN card.
    if (role === "client") {
      const first = page.getByLabel("First name (as per PAN card)");
      await expect(first).toBeEditable();
      await expect(first).toHaveAccessibleDescription(/exactly as it appears on your PAN card/);
      await expect(page.getByLabel("Last name (as per PAN card)")).toHaveAccessibleDescription(
        /exactly as it appears on your PAN card/,
      );
    } else {
      await expect(page.getByText(/PAN card/)).toHaveCount(0);
    }
    await page.screenshot({ path: testInfo.outputPath(`settings-${role}.png`), fullPage: true });
  });
}
