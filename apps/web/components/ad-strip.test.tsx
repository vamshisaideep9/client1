import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AdStrip } from "@/components/ad-strip";
import type { HeroBanner } from "@/lib/banners";

const SPONSOR: HeroBanner = {
  id: "sponsor-1",
  title: "Compare home loans from 12 lenders",
  subtitle: "Sponsored by a KYC-verified partner",
  image: "/banner-templates/homepage_ad/sponsor.webp",
  cta: { label: "Explore", href: "/loans#home-loan" },
};

describe("AdStrip", () => {
  it("labels itself as sponsored with no dismiss or playback controls", () => {
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} />);
    expect(markup).toContain('aria-label="Sponsored"');
    expect(markup).toContain('data-layout="ad-strip"');
    expect(markup).toContain('data-presentation="curtain-sponsor-card"');
    expect(markup).toContain("Sponsored");
    expect(markup).not.toContain("<button");
  });

  it("renders the sponsor's copy, artwork and internal CTA", () => {
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} />);
    expect(markup).toContain("Compare home loans from 12 lenders");
    expect(markup).toContain("/banner-templates/homepage_ad/sponsor.webp");
    expect(markup).toContain('href="/loans#home-loan"');
    expect(markup).toContain('alt=""');
  });

  it("keeps sponsored copy out of the document outline", () => {
    // The strip sits above the hero, so a heading here would put an ad at the
    // top of the homepage's heading structure.
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} />);
    expect(markup).not.toMatch(/<h[1-6][\s>]/);
  });

  it("server-renders readable copy and decorative curtains without hiding the ad", () => {
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} />);
    expect(markup).toContain('data-reveal="curtain"');
    expect(markup).toContain('aria-hidden="true" class="sponsor-curtain sponsor-curtain-left"');
    expect(markup).toContain('aria-hidden="true" class="sponsor-curtain sponsor-curtain-right"');
    expect(markup).not.toContain('aria-hidden="true" data-layout');
    expect(markup).toContain(SPONSOR.subtitle);
  });

  it("shows one sponsor with no carousel affordances", () => {
    // Only one sponsor runs at a time -- the successor waits in the CMS
    // replacement queue -- so there is nothing to rotate between and no
    // arrows, dots or autoplay to build.
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} />);
    expect(markup).not.toContain("Previous slide");
    expect(markup).not.toContain("Next slide");
    expect(markup).not.toContain('aria-roledescription="carousel"');
  });

  it("renders without a CTA or subtitle when the campaign omits them", () => {
    const bare: HeroBanner = { id: "sponsor-2", title: "A sponsor with no call to action" };
    const markup = renderToStaticMarkup(<AdStrip banner={bare} />);
    expect(markup).toContain("A sponsor with no call to action");
    expect(markup).not.toContain("<a ");
    expect(markup).not.toContain("<img ");
  });

  it("can render the exact CMS composition without an interactive dismiss control", () => {
    const markup = renderToStaticMarkup(<AdStrip banner={SPONSOR} animate={false} />);
    expect(markup).toContain('data-presentation="curtain-sponsor-card"');
    expect(markup).toContain('data-reveal="none"');
    expect(markup).not.toContain('aria-label="Dismiss sponsored message"');
  });
});
