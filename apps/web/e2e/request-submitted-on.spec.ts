import { expect, test, type Page } from "@playwright/test";

import { mockMobileApi } from "./helpers/mobile-fixtures";

// Synthetic fixtures only: one property enquiry and one site visit on a
// Real Estate lead. The assigned Telecaller must see when the client submitted
// each one, labelled separately from the visit's own date and slot.
test.use({ contextOptions: { reducedMotion: "reduce" } });
test.setTimeout(120_000);

const LEAD_ID = "65000000-0000-4000-8000-000000000001";
const ENQUIRY_ID = "66000000-0000-4000-8000-000000000001";
const VISIT_ID = "67000000-0000-4000-8000-000000000001";

async function mockLead(page: Page) {
  await mockMobileApi(page, "telecaller", "real_estate");
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}`, (route) =>
    route.fulfill({
      json: {
        id: LEAD_ID,
        name: "Meera Iyer",
        mobile: "+919876543210",
        business_line: "real_estate",
        status: "working",
        requirement: null,
        last_disposition: null,
        next_follow_up_at: null,
        created_at: "2026-11-12T04:00:00Z",
        updated_at: "2026-11-14T08:45:00Z",
        latest_request: {
          kind: "site_visit",
          id: VISIT_ID,
          title: "3BHK Villa",
          status: "requested",
          applied_at: "2026-11-14T08:45:00Z",
        },
        activities: [],
        loan_applications: [],
        financial_enquiries: [],
        property_enquiries: [
          {
            id: ENQUIRY_ID,
            property_ref: "68000000-0000-4000-8000-000000000001",
            title: "2BHK Apartment",
            locality: "Indiranagar",
            city: "Bengaluru",
            contact_name: "Meera Iyer",
            contact_mobile: "+919876543210",
            message: "Is parking included?",
            status: "new",
            created_at: "2026-11-13T05:30:00Z",
            updated_at: "2026-11-13T05:30:00Z",
          },
        ],
        site_visits: [
          {
            id: VISIT_ID,
            property_ref: "68000000-0000-4000-8000-000000000002",
            title: "3BHK Villa",
            locality: "Whitefield",
            city: "Bengaluru",
            contact_name: "Meera Iyer",
            contact_mobile: "+919876543210",
            preferred_date: "2026-11-20",
            preferred_time_slot: "morning",
            message: null,
            status: "requested",
            cancelled_at: null,
            created_at: "2026-11-14T08:45:00Z",
            updated_at: "2026-11-14T08:45:00Z",
            vehicle_arrangement: null,
          },
        ],
        property_deals: [],
        tasks: [],
      },
    }),
  );
  await page.route(`**/api/v1/telecaller/leads/${LEAD_ID}/client-history`, (route) =>
    route.fulfill({ json: { business_line: "real_estate", leads: [] } }),
  );
}

test("the telecaller sees when each enquiry and site visit was submitted", async ({
  page,
  baseURL,
}, testInfo) => {
  await mockLead(page);
  await page.context().addCookies([{ name: "session_hint", value: "1", url: baseURL! }]);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/dashboard/leads/${LEAD_ID}`, { waitUntil: "domcontentloaded" });

  // The newest request (the site visit) opens first.
  const submitted = page.locator("dt", { hasText: "Submitted on" });
  await expect(submitted).toHaveCount(1);
  const visitSubmitted = submitted.locator("xpath=following-sibling::dd[1]");
  await expect(visitSubmitted).toContainText("14 Nov 2026");
  await expect(visitSubmitted).toContainText(/\d{1,2}:\d{2}/);
  await expect(page.locator("dt", { hasText: "Visit on" })).toBeVisible();
  await expect(page.locator("dt", { hasText: "Scheduled" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("site-visit-submitted-on.png") });

  await page.getByRole("button", { name: /2BHK Apartment/ }).click();
  const enquirySubmitted = page
    .locator("dt", { hasText: "Submitted on" })
    .locator("xpath=following-sibling::dd[1]");
  await expect(enquirySubmitted).toContainText("13 Nov 2026");
  await expect(enquirySubmitted).toContainText(/\d{1,2}:\d{2}/);
  await expect(page.locator("dt", { hasText: "Enquired" })).toHaveCount(0);
});
