import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only. CS-026: the profile pincode with its place name,
// the one-time "Use my location" (browser position → nearest pincode on the
// server, never stored), and the Sub Admin campaign pincode/city targets. The
// API is mocked; it enforces every rule itself.
test.use({
  contextOptions: { reducedMotion: "reduce" },
  geolocation: { latitude: 17.44123, longitude: 78.34871 },
  permissions: ["geolocation"],
});
test.setTimeout(120_000);

const ME = {
  first_name: "Pin",
  last_name: "Code",
  mobile: "+919876543210",
  email: "pin@example.test",
  email_verified: true,
  email_required: false,
  gender: null,
  gender_self_description: null,
  income_source: null,
  income_amount_minor: null,
  income_period: null,
  occupation: null,
  location: null,
  pincode: null,
  place: null,
  profiles: ["loans", "real_estate"].map((business_line) => ({ business_line, customer_code: "PIN-0001" })),
};

const GACHIBOWLI = { pincode: "500032", area: "Gachibowli", district: "K.V.Rangareddy", state: "Telangana" };
const HYDERABAD = { pincode: "500001", area: "Hyderabad", district: "Hyderabad", state: "Telangana" };

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

for (const width of [1440, 390]) {
  test(`client sets a pincode by typing or with one-time location (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await mockMobileApi(page, "client");
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    const nearestCalls: { url: string; body: string | null }[] = [];
    const patches: Record<string, unknown>[] = [];
    let me: Record<string, unknown> = { ...ME };
    await page.route((url) => url.pathname === "/api/v1/auth/me", async (route) => {
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        patches.push(body);
        me = { ...me, pincode: body.pincode ?? null, place: body.pincode === "500032" ? GACHIBOWLI : null };
      }
      return route.fulfill({ json: me });
    });
    await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) =>
      route.fulfill({ json: { change: null } }),
    );
    await page.route((url) => url.pathname === "/api/v1/pincodes/500001", (route) =>
      route.fulfill({ json: HYDERABAD, headers: { "Cache-Control": "private, max-age=86400" } }),
    );
    await page.route((url) => url.pathname === "/api/v1/pincodes/999999", (route) =>
      route.fulfill({ status: 404, json: { detail: "We don't recognise this pincode." } }),
    );
    await page.route((url) => url.pathname === "/api/v1/pincodes/nearest", (route) => {
      nearestCalls.push({ url: route.request().url(), body: route.request().postData() });
      return route.fulfill({ json: GACHIBOWLI });
    });

    await page.setViewportSize({ width, height: 900 });
    const response = await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
    // The page may use the browser's location only on this origin.
    expect(response?.headers()["permissions-policy"]).toContain("geolocation=(self)");

    const pincode = page.getByRole("textbox", { name: "Pincode", exact: true });
    await expect(pincode).toBeVisible();
    await expect(page.getByText("we don't store your position", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: "GeoNames" }).first()).toHaveAttribute("href", "https://www.geonames.org/");

    // Typing a pincode shows its place name from the built-in list.
    await pincode.fill("500001");
    await expect(page.getByText("Hyderabad, Telangana")).toBeVisible();
    await pincode.fill("999999");
    await expect(page.getByText("We don't have a place name for this pincode.", { exact: false })).toBeVisible();
    await pincode.fill("012345");
    await expect(pincode).toHaveValue("012345");

    // "Use my location": one position, sent in the body, answered with a pincode.
    await page.getByRole("button", { name: "Use my location" }).click();
    await expect(pincode).toHaveValue("500032");
    await expect(page.getByText("Gachibowli, K.V.Rangareddy, Telangana")).toBeVisible();
    expect(nearestCalls).toHaveLength(1);
    expect(nearestCalls[0].url).not.toContain("17.44");
    expect(JSON.parse(nearestCalls[0].body ?? "{}")).toEqual({ latitude: 17.44123, longitude: 78.34871 });
    // Nothing is saved until the person saves the profile.
    expect(patches).toEqual([]);
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`pincode-${width}.png`), fullPage: true });

    await page.getByRole("button", { name: "Save changes" }).click();
    await expect.poll(() => patches.length).toBe(1);
    expect(patches[0].pincode).toBe("500032");
    // Only the pincode is saved: no coordinates travel with the profile.
    expect(JSON.stringify(patches[0])).not.toContain("17.44");
    expect(patches[0]).not.toHaveProperty("latitude");
  });
}

test("a malformed pincode is refused before saving", async ({ page, baseURL }) => {
  await mockMobileApi(page, "client");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  const patches: unknown[] = [];
  await page.route((url) => url.pathname === "/api/v1/auth/me", (route) => {
    if (route.request().method() === "PATCH") patches.push(route.request().postDataJSON());
    return route.fulfill({ json: ME });
  });
  await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) =>
    route.fulfill({ json: { change: null } }),
  );
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });
  await page.getByRole("textbox", { name: "Pincode", exact: true }).fill("012345");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Enter a 6-digit pincode that doesn't start with 0.")).toBeVisible();
  expect(patches).toEqual([]);
});

test("offers for your area need their own consent, given and withdrawn in Settings", async ({ page, baseURL }) => {
  await mockMobileApi(page, "client");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.route((url) => url.pathname === "/api/v1/auth/me", (route) =>
    route.fulfill({ json: { ...ME, pincode: "500001", place: HYDERABAD } }),
  );
  await page.route((url) => url.pathname === "/api/v1/auth/contact-change/active", (route) =>
    route.fulfill({ json: { change: null } }),
  );
  const calls: string[] = [];
  let preference = { personalization_enabled: true, location_enabled: false, location_captured_at: null };
  await page.route((url) => url.pathname === "/api/v1/personalization/preferences", (route) =>
    route.fulfill({ json: preference }),
  );
  await page.route((url) => url.pathname.startsWith("/api/v1/personalization/location"), (route) => {
    const request = route.request();
    calls.push(`${request.method()} ${new URL(request.url()).pathname} ${request.postData() ?? ""}`.trim());
    preference = { ...preference, location_enabled: request.method() === "PUT" };
    return route.fulfill({ json: preference });
  });
  await page.goto("/dashboard/settings", { waitUntil: "domcontentloaded" });

  const areaOffers = page.getByRole("checkbox", { name: "Offers for your area, using your profile pincode" });
  await expect(areaOffers).not.toBeChecked();
  await expect(page.getByText("Your device location is not used.", { exact: false })).toBeVisible();
  await areaOffers.click();
  await expect(areaOffers).toBeChecked();
  await areaOffers.click();
  await expect(areaOffers).not.toBeChecked();
  // Consent is given without sending any position, and withdrawn with DELETE.
  expect(calls).toEqual([
    "PUT /api/v1/personalization/location/consent",
    "DELETE /api/v1/personalization/location",
  ]);
});

for (const width of [1280, 390]) {
  test(`sub admin targets an offer by pincode and city (${width}px)`, async ({ page, baseURL }, testInfo) => {
    await mockMobileApi(page, "sub_admin");
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.route((url) => url.pathname === "/api/v1/offers", (route) =>
      route.fulfill({ json: { offers: [] } }),
    );
    await page.route((url) => url.pathname === "/api/v1/pincodes/districts", (route) =>
      route.fulfill({
        json: [
          { district: "Hyderabad", state: "Telangana" },
          { district: "Pune", state: "Maharashtra" },
        ],
      }),
    );
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/dashboard/offers", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "New offer" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Pincodes and cities")).toBeVisible();

    const pincodes = dialog.getByRole("textbox", { name: "Pincodes", exact: true });
    await pincodes.fill("012345");
    await dialog.getByRole("button", { name: "Add pincodes" }).click();
    await expect(dialog.getByText("012345 is not a valid pincode", { exact: false })).toBeVisible();
    await pincodes.fill("500001, 500032");
    await dialog.getByRole("button", { name: "Add pincodes" }).click();
    const pinChips = dialog.getByRole("list", { name: "Targeted pincodes" });
    await expect(pinChips.getByRole("listitem")).toHaveCount(2);

    await dialog.getByRole("button", { name: "Search for a city (district)" }).click();
    await page.getByRole("option", { name: "Hyderabad, Telangana" }).click();
    const cityChips = dialog.getByRole("list", { name: "Targeted cities" });
    await expect(cityChips.getByRole("listitem")).toHaveText(["Hyderabad, Telangana"]);
    await cityChips.getByRole("button", { name: "Remove Hyderabad, Telangana" }).click();
    await expect(cityChips).toHaveCount(0);

    // Place targets exist only for a Clients-only audience.
    await dialog.getByRole("checkbox", { name: "Agents" }).check();
    await expect(dialog.getByText("Available for a Clients-only audience", { exact: false })).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "Pincodes", exact: true })).toHaveCount(0);
    await expectNoPageOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`offer-places-${width}.png`) });
  });
}
