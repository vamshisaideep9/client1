import { expect, test } from "@playwright/test";

import { FIXTURE_ID, mockMobileApi } from "./helpers/mobile-fixtures";
import type { AuthenticatedPlacement } from "@/lib/personalization-api";

// External and YouTube CTAs need server-rendered public banners. Run against a
// web server whose API_INTERNAL_URL is release-catalogue-server.mjs started
// with --external-cta (see that fixture for the synthetic campaigns).
test.describe("external banner calls to action", () => {
  test.skip(
    process.env.PLAYWRIGHT_EXTERNAL_CTA_FIXTURE !== "1",
    "Requires the opt-in --external-cta server-side catalogue fixture.",
  );

  test("an https CTA opens in a new tab and says so", async ({ page }) => {
    await page.goto("/");
    const hero = page.locator('[aria-roledescription="carousel"]').first();
    const partner = hero.getByRole("link", { name: /Visit the partner/ });
    await expect(partner).toHaveAttribute("href", "https://partner.example/home-loans");
    await expect(partner).toHaveAttribute("target", "_blank");
    await expect(partner).toHaveAttribute("rel", "noopener noreferrer");
    await expect(partner).toHaveAccessibleName("Visit the partner (opens in a new tab)");

    const sponsor = page.getByRole("region", { name: "Sponsored", exact: true });
    const sponsorLink = sponsor.getByRole("link", { name: /Compare plans/ });
    await expect(sponsorLink).toHaveAttribute("href", "https://partner.example/plans");
    await expect(sponsorLink).toHaveAttribute("target", "_blank");

    // The synthetic partner domain does not resolve; serve a stub page so the
    // new tab can be inspected.
    await page.context().route("https://partner.example/**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>Partner</title>" }),
    );
    const [popup] = await Promise.all([page.waitForEvent("popup"), sponsorLink.click()]);
    await popup.waitForLoadState();
    expect(popup.url()).toBe("https://partner.example/plans");
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    await popup.close();
    await expect(page).toHaveURL(/\/$/);
  });

  test("a YouTube banner without a destination links to the video", async ({ page }) => {
    await page.goto("/");
    const hero = page.locator('[aria-roledescription="carousel"]').first();
    const watch = hero.getByRole("link", { name: /Watch on YouTube/, includeHidden: true });
    await expect(watch).toHaveAttribute("href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    await expect(watch).toHaveAttribute("target", "_blank");
    await expect(watch).toHaveAttribute("rel", "noopener noreferrer");
  });
});

const TEMPLATE = {
  id: "30000000-0000-4000-8000-000000000001", placement: "homepage", category_key: "general",
  label: "General", version: 1, image_url: "/banner-templates/homepage/general.webp",
  media_asset_id: null, active: true, created_at: "2026-11-16T09:00:00Z",
};

function bannerRow(status: string, title = "Partner campaign") {
  return {
    id: "20000000-0000-4000-8000-000000000001", business_line: "both", placement: "homepage",
    category_key: "general", template_id: TEMPLATE.id, offer_id: null, property_id: null,
    replaces_banner_id: null, banner_type: "default", title, subtitle: null,
    cta_label: "Visit partner", image_key: null, image_url: null, media_asset_id: null,
    youtube_video_id: null, video_media_asset_id: null, video_url: null,
    deep_link: "https://partner.example/offer", audience_rules: { version: 1 }, priority: 0,
    status, created_by_uuid: FIXTURE_ID, approved_by_uuid: null, review_note: null, version: 1,
    removed_by_uuid: null, removal_reason: null, removed_at: null, starts_at: null, ends_at: null,
    created_at: "2026-11-16T09:00:00Z", updated_at: "2026-11-16T09:00:00Z",
  };
}

test("a new banner is submitted for approval only when the author asks", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await mockMobileApi(page, "sub_admin");
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  const writes: string[] = [];
  await page.route("**/api/v1/banners/templates?**", (route) => route.fulfill({ json: { templates: [TEMPLATE] } }));
  await page.route("**/api/v1/banners", (route) => {
    if (route.request().method() === "POST") {
      writes.push(`create ${route.request().postDataJSON().deep_link}`);
      return route.fulfill({ status: 201, json: bannerRow("draft") });
    }
    return route.fulfill({ json: { banners: [] } });
  });
  await page.route("**/api/v1/banners/*/submit", (route) => {
    writes.push(`submit ${new URL(route.request().url()).pathname}`);
    return route.fulfill({ json: bannerRow("pending_approval") });
  });
  await page.goto("/dashboard/banners", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "New banner" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Next" }).click();
  await dialog.getByRole("radio", { name: /General/ }).click();
  await dialog.getByRole("button", { name: "Next" }).click();

  // Reaching the last step must not submit anything by itself.
  await expect(dialog.getByRole("button", { name: "Submit for approval" })).toBeVisible();
  await expect(dialog.getByText("Title is required.")).toHaveCount(0);
  expect(writes).toEqual([]);

  await dialog.getByLabel(/^Title/).fill("Partner campaign");
  await dialog.getByLabel("Button label").fill("Visit partner");
  await dialog.getByLabel("Button destination").fill("http://partner.example/offer");
  await dialog.getByRole("button", { name: "Submit for approval" }).click();
  await expect(dialog.getByText("Use a page path like /loans or a full https:// link.")).toBeVisible();
  expect(writes).toEqual([]);

  await dialog.getByLabel("Button destination").fill("https://partner.example/offer");
  await dialog.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Submitted for approval")).toBeVisible();
  expect(writes).toEqual([
    "create https://partner.example/offer",
    "submit /api/v1/banners/20000000-0000-4000-8000-000000000001/submit",
  ]);
});

const offerPlacement: AuthenticatedPlacement = {
  banners: [],
  offers: [
    {
      id: FIXTURE_ID,
      title: "Synthetic horizontal offer",
      partner_name: "Example partner",
      description: "A short description that keeps the card readable at every width.",
      code: "SYNTHETIC10",
      discount_type: "percentage",
      discount_value: "10",
      image_url: "/banner-templates/properties/villas.webp",
      redemption_url: "https://example.com/checkout",
      terms_url: "https://example.com/terms",
      terms_summary: "Synthetic browser fixture.",
    },
  ],
};

for (const { width, horizontal } of [
  { width: 390, horizontal: false },
  { width: 768, horizontal: true },
  { width: 1280, horizontal: true },
]) {
  test(`dashboard offer is ${horizontal ? "a horizontal banner" : "stacked"} at ${width}px`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockMobileApi(page, "agent");
    await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
    await page.route("**/api/v1/personalization/placements?**", (route) =>
      route.fulfill({ json: offerPlacement }),
    );
    await page.goto("/dashboard", { waitUntil: "networkidle" });

    const card = page.locator('[data-layout="offer-banner"]');
    await expect(card).toHaveCount(1);
    const artwork = card.locator("img");
    await expect(artwork).toBeVisible();
    await expect(artwork).toHaveCSS("object-fit", "cover");
    const heading = card.getByRole("heading", { name: "Synthetic horizontal offer" });
    await expect(heading).toBeVisible();

    const image = (await artwork.boundingBox())!;
    const title = (await heading.boundingBox())!;
    if (horizontal) {
      expect(title.x).toBeGreaterThanOrEqual(image.x + image.width - 1);
      expect(Math.abs(title.y - image.y)).toBeLessThan(image.height);
    } else {
      expect(title.y).toBeGreaterThanOrEqual(image.y + image.height - 1);
    }

    // Copy, focus and the new-tab links survive the new layout.
    const copy = card.getByRole("button", { name: "Copy" });
    await copy.focus();
    expect(await copy.evaluate((node) => node.matches(":focus-visible"))).toBe(true);
    await expect(card.getByRole("link", { name: /Use offer/ })).toHaveAttribute("target", "_blank");
    await expect(card.getByRole("link", { name: /Full terms/ })).toHaveAttribute("rel", "noopener noreferrer");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
