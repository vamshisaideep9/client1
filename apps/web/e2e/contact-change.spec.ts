import { expect, test, type Page } from "@playwright/test";

import type { UserRole } from "@/lib/auth";

import { mockMobileApi } from "./helpers/mobile-fixtures";
import { selectToggleAfterHydration } from "./helpers/release-client-readiness";

// Synthetic fixtures only. CS-025: mandatory email (the blocking "Add your
// email" step and the registration email step), self-service phone/email
// change for Clients/Agents/Admins, staff contact-change requests, and the
// Admin "Contact change requests" queue with the contact history. The API is
// mocked; it enforces every rule itself.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

// Mocked API: no real account or credential exists. Built from parts so secret
// scanners do not read it as a hard-coded password.
const MOCK_ADMIN_SECRET = ["mock", "secret", "not", "real"].join("-");
const CHANGE_ID = "91000000-0000-4000-8000-000000000001";
const STAFF_UUID = "92000000-0000-4000-8000-000000000001";

function challenge(patch: Record<string, unknown>) {
  return {
    change_id: CHANGE_ID,
    kind: "self_service",
    field: "mobile",
    status: "awaiting_current_otp",
    expires_at: "2099-01-01T00:00:00Z",
    message: "We sent a code.",
    destination_hint: "***3210",
    delivery_channel: "none",
    otp_hint: null,
    ...patch,
  };
}

const ME = {
  first_name: "Mobile",
  last_name: "Reviewer",
  mobile: "+919876543210",
  email: "mobile@example.test",
  email_verified: true,
  email_required: false,
  gender: null,
  gender_self_description: null,
  income_source: null,
  income_amount_minor: null,
  income_period: null,
  occupation: null,
  location: null,
  profiles: ["loans", "real_estate"].map((business_line) => ({ business_line, customer_code: "MOBILE-0001" })),
};

async function signedIn(page: Page, baseURL: string, role: UserRole) {
  await mockMobileApi(page, role);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL }]);
}

async function typeCode(page: Page, code = "123456") {
  await page.locator("#otp-input").fill(code);
}

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

for (const width of [1440, 390]) {
  test(`client changes their phone with codes to the old and new number (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await signedIn(page, baseURL!, "client");
    const calls: string[] = [];
    await page.route((url) => url.pathname === "/api/v1/auth/me", (route) => route.fulfill({ json: ME }));
    await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) => route.fulfill({ json: { change: null } }));
    await page.route((url) => url.pathname.startsWith("/api/v1/auth/contact-change/") && url.pathname !== "/api/v1/auth/contact-change/active", async (route) => {
      const step = new URL(route.request().url()).pathname.split("/").pop()!;
      calls.push(`${step}:${route.request().postData()}`);
      if (step === "start") return route.fulfill({ json: challenge({}) });
      if (step === "verify-current") return route.fulfill({ json: challenge({ status: "awaiting_new_value", destination_hint: null }) });
      if (step === "new-value") return route.fulfill({ json: challenge({ status: "awaiting_new_otp", destination_hint: "***1111" }) });
      if (step === "verify-new") return route.fulfill({ json: { message: "Changed.", signed_out: true } });
      return route.fulfill({ json: { message: "ok" } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

    const card = page.getByRole("region", { name: "Phone and email" });
    await expect(card).toContainText("98765 43210");
    await expect(card).toContainText("mobile@example.test");
    await expect(card.getByRole("link", { name: "Recover your account" })).toHaveAttribute("href", "/change-mobile");
    // The profile form no longer edits email or the number.
    await expect(page.getByLabel("Email", { exact: true })).toHaveCount(0);
    await expectNoPageOverflow(page);

    await card.getByRole("button", { name: "Change phone" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Change your phone number" })).toBeVisible();
    await dialog.getByLabel("Current password").fill("Secret@123");
    await dialog.getByRole("button", { name: "Continue" }).click();
    await expect(dialog.getByRole("heading", { name: "Confirm your current phone number" })).toBeVisible();
    await expect(dialog).toContainText("***3210");
    await typeCode(page);
    await dialog.getByRole("button", { name: "Verify current" }).click();
    await expect(dialog.getByRole("heading", { name: "Enter your new phone number" })).toBeVisible();
    await dialog.getByLabel("New mobile number").fill("98765 11111");
    await page.screenshot({ path: testInfo.outputPath(`change-phone-${width}.png`) });
    await dialog.getByRole("button", { name: "Send code" }).click();
    await expect(dialog.getByRole("heading", { name: "Confirm your new phone number" })).toBeVisible();
    await typeCode(page, "654321");
    await dialog.getByRole("button", { name: "Change phone number" }).click();

    await expect(page).toHaveURL(/\/login\?changed=mobile/);
    await expect(page.getByRole("status").filter({ hasText: "every device was signed out" })).toBeVisible();
    expect(calls[0]).toContain('"field":"mobile"');
    expect(calls.find((c) => c.startsWith("new-value"))).toContain("+919876511111");
  });
}

test("an email change is offered only with a verified email; otherwise Add email", async ({ page, baseURL }) => {
  await signedIn(page, baseURL!, "agent");
  await page.route((url) => url.pathname === "/api/v1/auth/me", (route) =>
    route.fulfill({ json: { ...ME, email: null, email_verified: false } }),
  );
  await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) => route.fulfill({ json: { change: null } }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  const card = page.getByRole("region", { name: "Phone and email" });
  await expect(card).toContainText("Not added");
  await expect(card.getByRole("button", { name: "Change email" })).toHaveCount(0);
  await card.getByRole("button", { name: "Add email" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Email")).toBeVisible();
  await expect(dialog.getByLabel("Current password")).toBeVisible();
});

for (const width of [1280, 390]) {
  test(`staff send a contact change request instead of changing it (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await signedIn(page, baseURL!, "telecaller");
    let pending = false;
    await page.route((url) => url.pathname === "/api/v1/auth/me", (route) => route.fulfill({ json: ME }));
    await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) =>
      route.fulfill({
        json: {
          change: pending
            ? { change_id: CHANGE_ID, kind: "staff_request", field: "email", status: "pending_approval", new_value_hint: "n***@example.test", expires_at: "2099-01-01T00:00:00Z", created_at: "2026-11-17T00:00:00Z" }
            : null,
        },
      }),
    );
    await page.route((url) => url.pathname === "/api/v1/auth/contact-change/requests", (route) =>
      route.fulfill({ json: challenge({ kind: "staff_request", field: "email", status: "awaiting_new_otp", destination_hint: "n***@example.test" }) }),
    );
    await page.route((url) => url.pathname === "/api/v1/auth/contact-change/requests/verify", (route) => {
      pending = true;
      return route.fulfill({ json: challenge({ kind: "staff_request", field: "email", status: "pending_approval" }) });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

    const card = page.getByRole("region", { name: "Phone and email" });
    await expect(card.getByRole("button", { name: "Change phone" })).toHaveCount(0);
    await card.getByRole("button", { name: "Request a contact change" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("radio", { name: "Email" }).click();
    await dialog.getByLabel("New email").fill("new@example.test");
    await dialog.getByLabel("Current password").fill("Secret@123");
    await dialog.getByRole("button", { name: "Send code" }).click();
    await expect(dialog).toContainText("n***@example.test");
    await typeCode(page);
    await dialog.getByRole("button", { name: "Send request" }).click();
    await expect(card.getByRole("status")).toContainText("waiting for an Admin");
    await expect(card.getByRole("button", { name: "Withdraw" })).toBeVisible();
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`staff-request-${width}.png`), fullPage: true });
  });
}

for (const width of [1440, 390]) {
  test(`an account without a verified email is held on the add-email step (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await signedIn(page, baseURL!, "client");
    let required = true;
    await page.route((url) => url.pathname === "/api/v1/auth/me", (route) =>
      route.fulfill({ json: { ...ME, email: null, email_verified: !required, email_required: required } }),
    );
    await page.route((url) => url.pathname === "/api/v1/auth/email/add", (route) =>
      route.fulfill({ json: challenge({ kind: "email_add", field: "email", status: "awaiting_new_otp", destination_hint: "j***@example.test" }) }),
    );
    await page.route((url) => url.pathname === "/api/v1/auth/email/add/verify", (route) => {
      required = false;
      return route.fulfill({ json: { ...ME, email: "jane@example.test" } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

    await expect(page).toHaveURL(/\/add-email$/);
    await expect(page.getByRole("heading", { name: "Add your email" })).toBeVisible();
    await page.getByLabel("Email").fill("jane@example.test");
    await page.getByLabel("Current password").fill("Secret@123");
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`add-email-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "Send code" }).click();
    await expect(page.getByText("j***@example.test")).toBeVisible();
    await typeCode(page);
    await page.getByRole("button", { name: "Verify email" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
}

test("registration asks for a verified email when the server requires it", async ({ page }) => {
  await mockMobileApi(page);
  await page.route((url) => url.pathname === "/api/v1/auth/register/initiate", (route) =>
    route.fulfill({ json: { message: "Sent.", delivery_channel: "none", otp_hint: null } }),
  );
  await page.route((url) => url.pathname === "/api/v1/auth/register/verify-otp", (route) =>
    route.fulfill({ json: { registration_token: "reg.token", email_required: true } }),
  );
  let emailBody = "";
  await page.route((url) => url.pathname === "/api/v1/auth/register/email/initiate", (route) => {
    emailBody = route.request().postData() ?? "";
    return route.fulfill({ json: { message: "Sent.", delivery_channel: "none", otp_hint: null } });
  });
  await page.route((url) => url.pathname === "/api/v1/auth/register/email/verify", (route) =>
    route.fulfill({ json: { registration_token: "reg.token.email", email_required: true } }),
  );
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/register", { waitUntil: "domcontentloaded" });
  await expect(page.locator("form").first()).toHaveAttribute("aria-busy", "false", { timeout: 30_000 });
  await selectToggleAfterHydration(page.getByRole("button", { name: "Loans" }));
  await page.getByLabel("First name").fill("Jane");
  await page.getByLabel("Last name").fill("Doe");
  await page.getByLabel("Phone number").fill("9876543210");
  await page.getByRole("button", { name: "Continue" }).click();
  await typeCode(page);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();
  await page.getByLabel("Email").fill("Jane@Example.test");
  await page.getByRole("button", { name: "Send code" }).click();
  expect(JSON.parse(emailBody)).toMatchObject({ registration_token: "reg.token", email: "jane@example.test" });
  await typeCode(page);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page.getByRole("heading", { name: "Create a password" })).toBeVisible();
  await expectNoPageOverflow(page);
});

for (const width of [1365, 390]) {
  test(`admin approves a staff request and reads the contact history (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await signedIn(page, baseURL!, "admin");
    let approvedWith = "";
    await page.route((url) => url.pathname === "/api/v1/admin/contact-change-requests", (route) =>
      route.fulfill({
        json: {
          requests: approvedWith
            ? []
            : [{
                id: CHANGE_ID, auth_user_uuid: STAFF_UUID, requester_name: "Synthetic Staff", requester_role: "telecaller",
                field: "mobile", current_value: "+919876543210", requested_value: "+919811111111", current_changed: false,
                new_verified_at: "2026-11-17T00:00:00Z", expires_at: "2099-01-01T00:00:00Z", created_at: "2026-11-17T00:00:00Z",
              }],
        },
      }),
    );
    await page.route((url) => url.pathname === `/api/v1/admin/contact-change-requests/${CHANGE_ID}/approve`, (route) => {
      approvedWith = route.request().postData() ?? "";
      return route.fulfill({ json: { message: "Approved." } });
    });
    await page.route((url) => url.pathname === `/api/v1/admin/users/${STAFF_UUID}/contact-history`, (route) =>
      route.fulfill({
        json: {
          entries: [{
            id: "93000000-0000-4000-8000-000000000001", field: "mobile", old_value: "+919800000000", new_value: "+919876543210",
            method: "lost_number_recovery", proof_category: "staff_confirmation", proof_reference: "BV-ALPHA",
            approved_by_name: "Second Admin", changed_at: "2026-10-01T10:00:00Z",
          }],
        },
      }),
    );
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/support-tickets", { waitUntil: "domcontentloaded" });

    const queue = page.getByRole("region", { name: "Contact change requests" });
    await expect(queue).toContainText("Synthetic Staff");
    await expect(queue).toContainText("98111 11111");
    await queue.getByRole("button", { name: "Contact history" }).first().click();
    const history = page.getByRole("dialog");
    await expect(history).toContainText("+919800000000");
    await expect(history).toContainText("Lost-number recovery");
    await expect(history).toContainText("approved by Second Admin");
    await page.screenshot({ path: testInfo.outputPath(`contact-history-${width}.png`) });
    await page.keyboard.press("Escape");

    await queue.getByRole("button", { name: "Review" }).click();
    const review = page.getByRole("dialog");
    await review.getByLabel(/Your current Admin password/).fill(MOCK_ADMIN_SECRET);
    await review.getByRole("button", { name: "Approve and apply" }).click();
    await expect(queue).toContainText("No staff contact changes are waiting.");
    expect(JSON.parse(approvedWith)).toEqual({ current_password: MOCK_ADMIN_SECRET });
    await expectNoPageOverflow(page);
  });
}
