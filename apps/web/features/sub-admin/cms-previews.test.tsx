import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BannerPreview, OfferPreview } from "./cms-previews";

describe("CMS previews", () => {
  it("renders banner actions only for safe destinations", () => {
    const local = renderToStaticMarkup(<BannerPreview context="dashboard" banner={{ banner_type: "action", title: "Finish KYC", subtitle: null, cta_label: "Continue", deep_link: "/dashboard/settings" }} />);
    const external = renderToStaticMarkup(<BannerPreview context="dashboard" banner={{ banner_type: "action", title: "Finish KYC", subtitle: null, cta_label: "Continue", deep_link: "https://partner.example" }} />);
    expect(local).toContain("Continue");
    expect(external).toContain("Continue");
    for (const deepLink of ["javascript:alert(1)", "//evil.example", "http://partner.example"]) {
      const unsafe = renderToStaticMarkup(<BannerPreview context="dashboard" banner={{ banner_type: "action", title: "Finish KYC", subtitle: null, cta_label: "Continue", deep_link: deepLink }} />);
      expect(unsafe).not.toContain("Continue");
    }
  });

  it("previews the YouTube fallback button for a public video banner", () => {
    const markup = renderToStaticMarkup(<BannerPreview context="public" placement="homepage" banner={{ banner_type: "default", title: "See the tour", subtitle: null, cta_label: null, deep_link: null, image_url: "/banner-templates/homepage/loans.webp", youtube_video_id: "dQw4w9WgXcQ" }} />);
    expect(markup).toContain("Watch on YouTube");
    const withoutVideo = renderToStaticMarkup(<BannerPreview context="public" placement="homepage" banner={{ banner_type: "default", title: "See the tour", subtitle: null, cta_label: null, deep_link: null, image_url: "/banner-templates/homepage/loans.webp" }} />);
    expect(withoutVideo).not.toContain("Watch on YouTube");
  });

  it("renders a dashboard-only partner coupon presentation", () => {
    const markup = renderToStaticMarkup(<OfferPreview offer={{ title: "Fee waiver", description: "Save on processing", discount_type: "percentage", discount_value: "10", code: "SAVE10", partner_name: "Example Bank", image_url: "/banner-templates/homepage/loans.webp" }} />);
    expect(markup).toContain("10% off");
    expect(markup).toContain("SAVE10");
    expect(markup).toContain("partner checkout");
  });

  it("previews the offer as the dashboard's single-column horizontal banner", () => {
    const markup = renderToStaticMarkup(<OfferPreview offer={{ title: "Fee waiver", description: null, discount_type: "flat", discount_value: "500", code: "SAVE500", partner_name: "Example Bank", image_url: "/banner-templates/homepage/loans.webp" }} />);
    expect(markup).toContain('<ul class="grid gap-3" aria-label="Offers for you">');
    expect(markup).not.toContain("lg:grid-cols-3");
    expect(markup).toContain('data-layout="offer-banner"');
    expect(markup).toContain("md:grid-cols-[minmax(0,40%)_minmax(0,1fr)]");
  });

  it("renders governed artwork and RERA state in the public banner preview", () => {
    const markup = renderToStaticMarkup(<BannerPreview context="public" placement="properties" banner={{ banner_type: "default", title: "Find your next home", subtitle: "Verified properties", cta_label: "Explore", deep_link: "/real-estate", image_url: "/banner-templates/properties/villas.webp", rera_verified: true }} />);
    expect(markup).toContain(encodeURIComponent("/banner-templates/properties/villas.webp"));
    expect(markup).toContain("RERA VERIFIED");
    expect(markup).toContain("Find your next home");
    expect(markup).toContain('data-layout="full-bleed"');
    expect(markup).toContain("h-[clamp(14rem,36vw,32.5rem)]");
  });

  it("uses the static sponsor card for homepage ad previews", () => {
    const markup = renderToStaticMarkup(<BannerPreview context="public" placement="homepage_ad" banner={{ banner_type: "default", title: "Plan your next move", subtitle: "Sponsored by a verified partner", cta_label: "Explore", deep_link: "/loans", image_url: "/banner-templates/homepage_ad/personal-finance.webp" }} />);
    expect(markup).toContain('data-presentation="static-sponsor-card"');
    expect(markup).not.toContain("data-reveal");
    expect(markup).toContain("personal-finance.webp");
    expect(markup).not.toContain('aria-label="Dismiss sponsored message"');
  });

  it("wraps public previews in real page chrome, not invented furniture", () => {
    const markup = renderToStaticMarkup(
      <BannerPreview
        context="public"
        placement="homepage"
        banner={{
          banner_type: "default",
          title: "Festive home loans",
          subtitle: null,
          cta_label: null,
          deep_link: null,
          image_url: "/banner-templates/homepage/loans.webp",
        }}
      />,
    );
    // Real navigation labels, taken from the same NAV_ITEMS the site header uses.
    expect(markup).toContain("Financial Services");
    expect(markup).toContain("Properties");
    expect(markup).toContain("Register");
    // The invented "Login" pill and the hardcoded cream that was never the real
    // page background are both gone.
    expect(markup).not.toContain("#f7f2e8");
    expect(markup).not.toContain(">Login<");
  });

  it("frames dashboard previews with the signed-in shell", () => {
    const markup = renderToStaticMarkup(
      <BannerPreview
        context="dashboard"
        banner={{
          banner_type: "default",
          title: "Continue your application",
          subtitle: null,
          cta_label: null,
          deep_link: null,
        }}
      />,
    );
    expect(markup).toContain("Dhanadhara");
    expect(markup).toContain("Continue your application");
    // The card sits inside the same wrapper the real dashboard uses for its
    // highlights band, not an invented content area.
    expect(markup).toContain('aria-label="Dashboard highlights"');
  });
});
