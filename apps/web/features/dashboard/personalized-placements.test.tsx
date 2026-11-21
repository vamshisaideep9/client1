import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AuthenticatedBanner, AuthenticatedOffer } from "@/lib/personalization-api";

import { DashboardBannerCard, DashboardOfferCard } from "./personalized-placements";

const OFFER: AuthenticatedOffer = {
  id: "offer-1",
  title: "Processing fee waiver",
  description: "Save on your next home loan.",
  discount_type: "percentage",
  discount_value: "10",
  code: "SAVE10",
  partner_name: "Example Bank",
  image_url: "/banner-templates/homepage/loans.webp",
  redemption_url: "https://partner.example/checkout",
  terms_summary: "Valid for new applications.",
  terms_url: "https://partner.example/terms",
};

describe("DashboardOfferCard", () => {
  it("is a horizontal banner from md up with the artwork on the left", () => {
    const markup = renderToStaticMarkup(<DashboardOfferCard offer={OFFER} />);
    expect(markup).toContain('data-layout="offer-banner"');
    // Stacked by default; artwork column then copy from md.
    expect(markup).toContain("md:grid-cols-[minmax(0,40%)_minmax(0,1fr)]");
    expect(markup).toContain("aspect-[16/7]");
    expect(markup).toContain("md:aspect-auto");
    // The artwork fills its column by cropping, never by stretching.
    expect(markup).toContain("object-cover");
    expect(markup.indexOf("<img")).toBeLessThan(markup.indexOf("Processing fee waiver"));
  });

  it("drops the artwork column when there is no allowed image", () => {
    const markup = renderToStaticMarkup(
      <DashboardOfferCard offer={{ ...OFFER, image_url: "https://untrusted.example/x.png" }} />,
    );
    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("md:grid-cols-[minmax(0,40%)_minmax(0,1fr)]");
  });

  it("keeps the coupon copy and opens partner links in a new tab, announced", () => {
    const markup = renderToStaticMarkup(<DashboardOfferCard offer={OFFER} />);
    expect(markup).toContain("Coupon code");
    expect(markup).toContain("SAVE10");
    expect(markup).toContain("10% off");
    expect(markup).toContain("Copy the code, open the partner checkout");
    expect(markup).toContain('href="https://partner.example/checkout" target="_blank" rel="noopener noreferrer"');
    expect(markup).toContain('href="https://partner.example/terms" target="_blank" rel="noopener noreferrer"');
    expect(markup.match(/\(opens in a new tab\)/g)).toHaveLength(2);
    expect(markup).toContain("focus-visible:ring-2");
  });

  it("renders inert controls in the CMS preview", () => {
    const markup = renderToStaticMarkup(<DashboardOfferCard offer={OFFER} interactive={false} />);
    expect(markup).not.toContain("<a ");
    expect(markup).toContain("disabled");
  });
});

const BANNER: AuthenticatedBanner = {
  id: "banner-1",
  banner_type: "action",
  title: "Finish your KYC",
  subtitle: null,
  cta_label: "Continue",
  deep_link: "/dashboard/settings",
  image_url: null,
};

describe("DashboardBannerCard", () => {
  it("keeps internal destinations in the same tab", () => {
    const markup = renderToStaticMarkup(<DashboardBannerCard banner={BANNER} />);
    expect(markup).toContain('href="/dashboard/settings"');
    expect(markup).not.toContain("target=");
  });

  it("opens an https destination in a new tab and says so", () => {
    const markup = renderToStaticMarkup(
      <DashboardBannerCard banner={{ ...BANNER, deep_link: "https://partner.example/kyc" }} />,
    );
    expect(markup).toContain('href="https://partner.example/kyc"');
    expect(markup).toContain('target="_blank"');
    expect(markup).toContain('rel="noopener noreferrer"');
    expect(markup).toContain("(opens in a new tab)");
  });

  it("renders no button for an unsafe destination", () => {
    for (const deepLink of ["javascript:alert(1)", "//evil.example", "http://partner.example"]) {
      const markup = renderToStaticMarkup(
        <DashboardBannerCard banner={{ ...BANNER, deep_link: deepLink }} />,
      );
      expect(markup).not.toContain("Continue");
    }
  });
});
