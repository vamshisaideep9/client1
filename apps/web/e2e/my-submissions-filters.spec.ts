import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: the author workspace filters on Property listings
// (/dashboard/my-submissions) for a Sub Admin. No request reaches a backend.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

type Row = Record<string, unknown>;

function listing(index: number, overrides: Row): Row {
  return {
    id: `50000000-0000-4000-8000-00000000000${index}`,
    title: `Listing ${index}`,
    type: "Apartment",
    location: "Kondapur, Hyderabad",
    locality: "Kondapur",
    city: "Hyderabad",
    state: "Telangana",
    pincode: "500084",
    developer_name: null,
    meta: null,
    image: null,
    category: "apartments",
    property_subtype: "standalone_apartment",
    listing_intent: "sale",
    price_paise: 1_20_00_00_000,
    security_deposit_paise: null,
    minimum_lease_months: null,
    available_from: null,
    bhk: 3,
    area_sqft: 1750,
    furnishing: "semi",
    construction_status: "ready",
    amenities: [],
    age_years: 3,
    rera_number: "RERA/TS/DEMO/SUB01",
    rera_applicability: "applicable",
    rera_verification_status: "not_reviewed",
    rera_verified_at: null,
    status: "pending",
    review_note: null,
    reviewed_at: null,
    reviewed_by_uuid: null,
    approved_property_id: null,
    submitter_uuid: "10000000-0000-4000-8000-000000000001",
    details: {},
    details_version: null,
    structured_details: null,
    listing_links: null,
    media: [],
    created_at: `2026-11-1${index}T09:00:00Z`,
    updated_at: `2026-11-1${index}T09:00:00Z`,
    ...overrides,
  };
}

const LISTINGS = [
  listing(1, { title: "Kondapur Sale Flat" }),
  listing(2, {
    title: "Hanamkonda House for Rent",
    city: "Warangal",
    locality: "Hanamkonda",
    location: "Hanamkonda, Warangal",
    category: "houses",
    property_subtype: "individual_house",
    listing_intent: "rent",
    price_paise: 25_000_00,
    furnishing: "furnished",
  }),
  listing(3, {
    title: "HITEC Office for Lease",
    category: "commercial",
    property_subtype: "locked_space",
    listing_intent: "rent",
    price_paise: 1_20_000_00,
    bhk: 0,
  }),
  listing(4, {
    title: "Lakeview Villa",
    category: "villas",
    property_subtype: "villa",
    status: "approved",
    rera_verification_status: "verified",
    rera_verified_at: "2026-11-14T09:00:00Z",
  }),
  listing(5, { title: "Gachibowli Flat for Rent", listing_intent: "rent", price_paise: 32_000_00, status: "rejected" }),
  listing(6, { title: "Mokila Plot", category: "plots", property_subtype: "plot", bhk: 0, status: "withdrawn" }),
];

async function openListings(page: Page, baseURL: string | undefined, path = "/dashboard/my-submissions") {
  await mockMobileApi(page, "sub_admin");
  await page.route("**/api/v1/property-submissions**", (route) =>
    route.fulfill({ json: { submissions: LISTINGS } }),
  );
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "My listings" })).toBeVisible();
}

async function choose(page: Page, label: string, option: string) {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

const rows = (page: Page) => page.locator("tbody tr");

test("a sub admin narrows listings by status, sale or rent and price, and the URL keeps them", async ({ page, baseURL }) => {
  await openListings(page, baseURL);
  await expect(rows(page)).toHaveCount(6);
  await expect(page.getByText("Showing 6 of 6 listings.", { exact: false })).toBeVisible();

  await choose(page, "Filter by status", "Pending review");
  await expect(rows(page)).toHaveCount(3);

  const more = page.getByRole("button", { name: /More filters/ });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
  await choose(page, "Filter by sale or rent", "For rent / lease");
  await expect(rows(page)).toHaveCount(2);
  await page.getByRole("textbox", { name: "Maximum price (₹)" }).fill("50000");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Hanamkonda House for Rent");
  await page.keyboard.press("Escape");
  await expect(more).toContainText("(2)");
  await expect(page).toHaveURL(/status=pending/);
  await expect(page).toHaveURL(/intent=rent/);
  await expect(page).toHaveURL(/price_max=50000/);

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(rows(page)).toHaveCount(1);
  await expect(page.getByText("Showing 1 of 6 listings.", { exact: false })).toBeVisible();
  // Hidden filters stay visible as removable chips.
  const chips = page.getByRole("list", { name: "Active filters" });
  await expect(chips).toContainText("Sale or rent: For rent / lease");
  await expect(chips).toContainText("Price (₹): up to 50000");
  await expect(page.getByRole("combobox", { name: "Filter by status" })).toContainText("Pending review");
  await page.getByRole("button", { name: "Remove filter Price (₹): up to 50000" }).click();
  await expect(rows(page)).toHaveCount(2);
  await expect(page).not.toHaveURL(/price_max/);
});

test("status cards apply their filter and Clear filters resets everything", async ({ page, baseURL }) => {
  await openListings(page, baseURL);
  const approvedCard = page.getByRole("button", { name: /^Approved\s*1$/ });
  await approvedCard.click();
  await expect(approvedCard).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/status=approved/);
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Lakeview Villa");

  await page.getByRole("textbox", { name: "Search your listings" }).fill("no such listing");
  await expect(page.getByRole("heading", { name: "No listings match these filters" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).last().click();
  await expect(rows(page)).toHaveCount(6);
  await expect(page.getByRole("button", { name: /^All listings\s*6$/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page).not.toHaveURL(/\?/);
});

test("a shared link opens the filtered view and the page fits a phone", async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openListings(page, baseURL, "/dashboard/my-submissions?category=plots&subtype=villa&bhk=9&city=warangal");
  // The mismatched subtype and invalid BHK fall back to "all"; the city still applies.
  await expect(rows(page)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "No listings match these filters" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).last().click();
  await expect(rows(page)).toHaveCount(6);
  await page.getByRole("button", { name: /More filters/ }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
