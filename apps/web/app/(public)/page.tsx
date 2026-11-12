import type { Metadata } from "next";

import { AdStrip } from "@/components/ad-strip";
import { ClosingCta } from "@/components/closing-cta";
import { ContentBlockSection } from "@/components/content-block-section";
import { FaqSection } from "@/components/faq-section";
import { FloatingDoodles } from "@/components/floating-doodles";
import { HeroCarousel } from "@/components/hero-carousel";
import { HomeCalculators } from "@/components/home-calculators";
import { HomeIntro } from "@/components/home-intro";
import { HowItWorks } from "@/components/how-it-works";
import { LineSplit } from "@/components/line-split";
import { PartnerCta } from "@/components/partner-cta";
import { WhyChooseUs } from "@/components/why-choose-us";
import { HomeSuggestedProperties } from "@/features/real-estate/home-suggested-properties";
import { FALLBACK_HERO_BANNERS } from "@/lib/banners";
import { faqPageJsonLd, HOME_FAQ_ITEMS } from "@/lib/faq";
import { getHeroBanners } from "@/lib/public-banners";
import { getPublicContentBlockBySlug } from "@/lib/public-content-blocks";
import { jsonLdScript, organizationJsonLd } from "@/lib/organization-jsonld";
import { getPublicListings } from "@/lib/public-properties";

// The hero is the one CMS surface with an explicit starts_at/ends_at contract
// (docs/specs/public-banner-serving.md), so visitor-visible publish latency is
// scheduler interval + this window: at 60s that's ~6 minutes past a banner's
// stated go-live time. /real-estate uses 300 because properties have no
// timestamp promise and a human-paced approval loop; this page's traffic is
// higher but the per-request cost is identical (one fetch either way), so the
// shorter window costs nothing extra per visitor.
export const revalidate = 60;

// Landing-scoped SEO metadata. Overrides the generic root-layout default
// (which stays as the internal fallback for authenticated dashboard routes).
export const metadata: Metadata = {
  title: "Dhanadhara: Loans & Verified Property in Hyderabad",
  description:
    "Compare home, personal and business loans from banks and NBFCs, free of charge, plus verified property in Hyderabad. Serving Hyderabad and Telangana.",
  keywords: [
    "personal loan",
    "business loan",
    "property loan",
    "vehicle loan",
    "education loan",
    "credit cards",
    "real estate",
    "compare loans",
    "financial calculators",
    "EMI calculator",
    "stamp duty calculator",
  ],
  alternates: { canonical: "/" },
  openGraph: {
    title: "Dhanadhara: Loans & Verified Property in Hyderabad",
    description:
      "Compare home, personal and business loans from banks and NBFCs, free of charge, plus verified property in Hyderabad. Serving Hyderabad and Telangana.",
    type: "website",
  },
};

const homeFaqJsonLd = {
  "@context": "https://schema.org",
  "@graph": [organizationJsonLd(), faqPageJsonLd(HOME_FAQ_ITEMS)],
};

export default async function Home() {
  // Empty table or a failed fetch both collapse to []: getHeroBanners()
  // never throws (see lib/public-banners.ts), and we deliberately don't
  // distinguish the two here either -- FALLBACK_HERO_BANNERS is what renders
  // in either case, so the homepage is never blank.
  const [liveBanners, adBanners, closingBlock, publicListings] = await Promise.all([
    getHeroBanners(),
    getHeroBanners("homepage_ad"),
    getPublicContentBlockBySlug("homepage-closing"),
    // Same ISR-cached catalog read as /real-estate. Suggestions are computed in
    // the browser from locally cached bookmark ids, so this HTML stays the same
    // for every visitor.
    getPublicListings(),
  ]);
  const banners = liveBanners.length > 0 ? liveBanners : FALLBACK_HERO_BANNERS;

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdScript(homeFaqJsonLd) }}
      />
      {/* Sponsored strip above the hero. One sponsor at a time (the server
          serves at most one for this placement), and unlike the hero it has NO
          fallback: with no live campaign it renders nothing at all, so the
          hero stays flush against the sticky header. */}
      {adBanners.length > 0 ? <AdStrip banner={adBanners[0]} /> : null}
      <HeroCarousel banners={banners} />
      {/* The page's single visible H1; carousel and section headings are H2s. */}
      <HomeIntro />
      <HomeSuggestedProperties listings={publicListings} />
      {/* Floating natural-color finance doodles overlay the real-estate band and the
          WhyChooseUs bento (lg+, pointer-events-none), hugging the outer gutters. */}
      <div className="relative">
        <LineSplit />
        <FloatingDoodles />
      </div>
      <HomeCalculators />
      <HowItWorks />
      <div className="relative">
        <WhyChooseUs />
        <FloatingDoodles subset={[0, 1, 3]} />
      </div>
      <PartnerCta />
      <FaqSection
        heading="Frequently asked questions"
        subheading="Answers to what people usually ask before they get started."
        items={HOME_FAQ_ITEMS}
      />
      <ContentBlockSection block={closingBlock} />
      <ClosingCta href="/contact" />
    </>
  );
}
