import type { components } from "@contracts/generated/schema";
import { expect, test, type Page } from "@playwright/test";

test.setTimeout(120_000);

type Flow = components["schemas"]["ChatFlow"];

const HOME: Flow = {
  id: "home-loan", section: "loans", label: "Home Loan", browse_href: "/loans/home-loan",
  questions: [
    { prompt: "What are you planning?", options: ["Buy a home", "Buy a plot"] },
    { prompt: "What is your property budget?", options: ["Under ₹60 lakh"] },
    { prompt: "When do you need it?", options: ["This month"] },
  ],
  actions: [{ id: "advisor", label: "Talk to a loan advisor" }],
};
const RESIDENTIAL: Flow = {
  id: "residential", section: "real_estate", label: "Residential Properties",
  browse_href: "/real-estate#property-results",
  questions: [
    { prompt: "Are you looking to buy or rent?", options: ["Buy property", "Rent / Lease"] },
    { prompt: "What type of home do you prefer?", options: ["Independent villa"] },
    { prompt: "What is your property budget?", options: ["Under ₹60 lakh"] },
  ],
  actions: [{ id: "visit", label: "Request a site visit" }],
};

async function openChat(page: Page) {
  await page.route("**/api/v1/leads/chat-inquiries/flows", (route) =>
    route.fulfill({ json: [HOME, RESIDENTIAL] }),
  );
  await page.goto("/contact", { waitUntil: "domcontentloaded" });
  const launcher = page.getByRole("button", { name: "Open Dhanadhara chat" });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(launcher).toBeEnabled({ timeout: 30_000 });
  await launcher.focus();
  await launcher.press("Enter");
  return page.getByRole("dialog");
}

test("desktop chat preserves progress and shows only published financial services", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const chat = await openChat(page);
  await chat.getByRole("button", { name: /Financial Services/ }).click();
  await expect(chat.getByRole("button", { name: "Insurance", exact: true })).toHaveCount(0);
  await chat.getByRole("button", { name: "Loans", exact: true }).click();
  await chat.getByRole("button", { name: "Home Loan", exact: true }).click();
  await chat.getByRole("button", { name: "Buy a home" }).click();
  await expect(chat.getByRole("heading", { name: "What is your property budget?" })).toBeFocused();
  await page.keyboard.press("Escape");
  const launcher = page.getByRole("button", { name: "Open Dhanadhara chat" });
  await expect(launcher).toBeFocused();
  await launcher.press("Enter");
  await expect(chat.getByRole("heading", { name: "What is your property budget?" })).toBeFocused();
  const bounds = await chat.boundingBox();
  expect(bounds!.width).toBeLessThan(430);
  await chat.getByRole("button", { name: "Back", exact: true }).click();
  await expect(chat.getByRole("heading", { name: "What are you planning?" })).toBeVisible();
});

test("mobile inquiry retries safely and offers a separate loan conversation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const submissions: components["schemas"]["ChatInquiryCreate"][] = [];
  const reference = "10000000-0000-4000-8000-000000000021";
  await page.route("**/api/v1/leads/chat-inquiries", async (route) => {
    submissions.push(route.request().postDataJSON());
    if (submissions.length === 1) {
      await route.fulfill({ status: 503, json: { detail: "Try again." } });
    } else {
      await route.fulfill({ status: 201, json: { reference } });
    }
  });

  const chat = await openChat(page);
  await chat.getByRole("button", { name: /Real Estate Services/ }).click();
  await expect(chat).toHaveCSS("animation-name", "none");
  const bounds = await chat.boundingBox();
  expect(bounds?.width).toBe(390);
  expect(bounds?.height).toBe(844);
  await chat.getByRole("button", { name: "Residential Properties" }).click();
  await chat.getByRole("button", { name: "Buy property" }).click();
  await chat.getByRole("button", { name: "Independent villa" }).click();
  await chat.getByRole("button", { name: "Under ₹60 lakh" }).click();
  await expect(chat.getByRole("link", { name: "Browse properties" })).toHaveAttribute(
    "href", "/real-estate?mode=sale&property_type=villa&budget_max=6000000#property-results",
  );
  await chat.getByRole("button", { name: "Request a site visit" }).click();
  await chat.getByRole("button", { name: "Send inquiry" }).click();
  await expect(chat.getByLabel("Full name")).toBeFocused();
  await chat.getByLabel("Full name").fill("Test Visitor");
  await chat.getByLabel("Preferred city or area").fill("Sample locality");
  await chat.getByLabel("Mobile number").fill("9876500123");
  await chat.getByRole("button", { name: "Send inquiry" }).click();
  await expect(chat.getByRole("alert")).toBeVisible();
  await expect(chat.getByLabel("Full name")).toHaveValue("Test Visitor");
  await chat.getByRole("button", { name: "Send inquiry" }).click();
  await expect(chat.getByText(reference)).toBeVisible();
  expect(submissions).toHaveLength(2);
  expect(submissions[0]).toEqual(submissions[1]);
  await chat.getByRole("button", { name: "Need a home or plot loan?" }).click();
  await expect(chat.getByRole("heading", { name: "What are you planning?" })).toBeVisible();
  await expect(chat.getByText(reference)).toHaveCount(0);
});
