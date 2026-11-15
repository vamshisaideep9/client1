import type { Metadata } from "next";
import { describe, expect, it } from "vitest";

import { metadata as about } from "@/app/(public)/about/page";
import { metadata as applyAsAgent } from "@/app/(public)/apply-as-agent/page";
import { metadata as calculators } from "@/app/(public)/calculators/page";
import { metadata as contact } from "@/app/(public)/contact/page";
import { metadata as cookies } from "@/app/(public)/cookies/page";
import { metadata as earnWithUs } from "@/app/(public)/earn-with-us/page";
import { metadata as getStarted } from "@/app/(public)/get-started/page";
import { metadata as helpCenter } from "@/app/(public)/help-center/page";
import { metadata as loans } from "@/app/(public)/loans/page";
import { metadata as home } from "@/app/(public)/page";
import { metadata as privacy } from "@/app/(public)/privacy/page";
import { metadata as realEstate } from "@/app/(public)/real-estate/page";
import { metadata as terms } from "@/app/(public)/terms/page";
import { CALCULATORS } from "@/lib/calculators/registry";
import { SITE_NAME } from "@/lib/site";

const PAGES: Record<string, Metadata> = {
  "/": home, "/about": about, "/loans": loans, "/real-estate": realEstate, "/calculators": calculators,
  "/earn-with-us": earnWithUs, "/apply-as-agent": applyAsAgent, "/contact": contact,
  "/get-started": getStarted, "/help-center": helpCenter, "/privacy": privacy, "/terms": terms, "/cookies": cookies,
};

// Rendered titles: static pages print theirs verbatim; calculator pages append the brand.
const titles = [
  ...Object.values(PAGES).map((page) => String(page.title)),
  ...CALCULATORS.map((calculator) => `${calculator.title} | ${SITE_NAME}`),
];

describe("public page metadata (titles sheet v2, 2026-11-12)", () => {
  it("keeps every title unique and within 60 characters", () => {
    expect(new Set(titles).size).toBe(titles.length);
    for (const title of titles) expect(title.length, title).toBeLessThanOrEqual(60);
  });

  it.each(Object.entries(PAGES))("%s has a search-length description mirrored in Open Graph", (_path, page) => {
    const description = String(page.description);
    expect(description.length, description).toBeGreaterThanOrEqual(110);
    expect(description.length, description).toBeLessThanOrEqual(160);
    expect(page.openGraph?.title).toBe(page.title);
    expect(page.openGraph?.description).toBe(page.description);
  });

  it("does not market insurance on the homepage or the financial-services hub", () => {
    for (const page of [home, loans]) {
      expect(JSON.stringify([page.title, page.description, page.keywords, page.openGraph])).not.toMatch(/insurance/i);
    }
  });

  it("keeps calculator meta descriptions within search length", () => {
    for (const calculator of CALCULATORS) {
      expect(calculator.metaDescription.length, calculator.slug).toBeLessThanOrEqual(160);
    }
  });
});
