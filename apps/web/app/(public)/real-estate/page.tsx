import type { Metadata } from "next";

import { HeroCarousel } from "@/components/hero-carousel";
import { PropertyCatalogEmpty } from "@/components/property-catalog-empty";
import { ProductPage, PropertyDoodles } from "@/components/product-page";
import { PropertyRow } from "@/components/property-row";
import { PublicPropertySearch, PropertySearchPagination, propertySearchParams } from "@/components/public-property-search";
import { TrustStrip } from "@/components/trust-strip";
import { WebsiteBody } from "@/components/website-content";
import { faqPageJsonLd, REAL_ESTATE_FAQ_ITEMS } from "@/lib/faq";
import { RE_TRUST, REAL_ESTATE_JOURNEY } from "@/lib/products";
import { getHeroBanners } from "@/lib/public-banners";
import { getPublicPropertyTypes, searchPublicListings } from "@/lib/public-properties";
import { getWebsiteContent } from "@/lib/public-website-content";
import { jsonLdScript } from "@/lib/organization-jsonld";
import { resolveWebsiteFaq } from "@/lib/website-content";
import { groupByCategory, PROPERTY_CATEGORIES } from "@/lib/properties";
import { propertySubtypeOption } from "@/lib/property-taxonomy";
import { SITE_NAME, SITE_URL } from "@/lib/site";

// First server-side data fetch on the public site. Regenerated at most every
// 5 minutes (ISR): the properties table can ship empty on day one and the
// admin-approval workflow that populates it is human-paced, so this is not
// real-time data, but it should not need a redeploy to appear either.
export const revalidate = 300;

export const metadata: Metadata = {
  title: "Flats, Villas & Plots for Sale in Hyderabad | Dhanadhara",
  description:
    "Flats, villas, plots, resale, rentals and commercial property in Hyderabad. Every listing is RERA-checked and site-visited before it goes live.",
  keywords: [
    "buy property",
    "rent property",
    "property for rent",
    "buy home",
    "buy flat",
    "buy plot",
    "real estate",
    "verified property",
    "property agents",
  ],
  alternates: { canonical: "/real-estate" },
  openGraph: {
    title: "Flats, Villas & Plots for Sale in Hyderabad | Dhanadhara",
    description:
      "Flats, villas, plots, resale, rentals and commercial property in Hyderabad. Every listing is RERA-checked and site-visited before it goes live.",
    type: "website",
  },
};

const realEstateJsonLd = (faq: typeof REAL_ESTATE_FAQ_ITEMS) => ({
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: `${SITE_URL}/` },
        {
          "@type": "ListItem",
          position: 2,
          name: "Properties",
          item: `${SITE_URL}/real-estate`,
        },
      ],
    },
    ...(faq.length ? [faqPageJsonLd(faq)] : []),
  ],
  publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
});

export default async function RealEstatePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = propertySearchParams(await searchParams);
  const [results, banners, types, published] = await Promise.all([
    searchPublicListings(params),
    getHeroBanners("properties"),
    getPublicPropertyTypes(),
    getWebsiteContent("page/real-estate"),
  ]);
  const requestedType = params.get("property_type");
  const selectedType = types.find(({ code }) => code === requestedType)?.label
    ?? propertySubtypeOption(requestedType)?.label;
  const visibleListings = results.ok ? results.data.properties : [];
  const faq = resolveWebsiteFaq(published?.content.faq, REAL_ESTATE_FAQ_ITEMS);
  const grouped = groupByCategory(visibleListings);
  // Only render category rows that actually have listings (empty-state guard,
  // so a category with nothing to show does not render an empty scroller).
  const populatedCategories = PROPERTY_CATEGORIES.filter(
    (category) => (grouped.get(category.key)?.length ?? 0) > 0,
  );

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdScript(realEstateJsonLd(faq)) }}
      />
      <ProductPage
        title={published?.content.title || "Properties for sale, resale and rent in Hyderabad"}
        intro={published?.content.summary || "Explore flats, villas, plots and commercial space in Hyderabad. Before you pay a token amount, have your own lawyer check the title."}
        heroDoodles
        heroPlant="/illustrations/heroes/real-estate.svg"
        beforeHero={
          banners.length > 0 ? (
            <HeroCarousel banners={banners} variant="section" label="Property campaigns" compact />
          ) : null
        }
        beforeJourney={
          <>
            <div className="relative w-full border-t border-[var(--nav-border)] bg-[var(--nav-bg)] py-20 sm:py-24 lg:py-28">
              <PropertyDoodles />
              <div className="relative z-10 space-y-10 sm:space-y-16">
                <PublicPropertySearch params={params} types={types} />
                <div id="property-results" className="scroll-mt-[var(--site-header-h)]" />
                {results.ok && params.size ? (
                  <p className="mx-auto max-w-7xl px-4 text-sm text-text-secondary sm:px-6 lg:px-8">
                    {results.data.total} {results.data.total === 1 ? "property" : "properties"} found
                  </p>
                ) : null}
                {!results.ok ? (
                  <p role="status" className="mx-auto max-w-7xl px-4 text-text-secondary sm:px-6 lg:px-8">
                    {results.status === 422 ? "Check your search filters and try again." : "Property results are temporarily unavailable. Please try again shortly."}
                  </p>
                ) : selectedType && visibleListings.length > 0 ? (
                  <PropertyRow
                    id={requestedType ?? "matched-properties"}
                    heading={selectedType}
                    types={`Browse ${selectedType.toLowerCase()} available now.`}
                    listings={visibleListings}
                  />
                ) : populatedCategories.length > 0 ? (
                  populatedCategories.map((category) => (
                    <PropertyRow
                      key={category.key}
                      id={category.key}
                      heading={category.label}
                      types={category.blurb}
                      listings={grouped.get(category.key) ?? []}
                    />
                  ))
                ) : (
                  <PropertyCatalogEmpty />
                )}
                {results.ok ? <PropertySearchPagination params={params} page={results.data.page}
                  pageSize={results.data.page_size} total={results.data.total} /> : null}
                <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
                  <TrustStrip points={RE_TRUST} />
                </div>
              </div>
            </div>
            <WebsiteBody content={published && { body: published.content.body, sections: published.content.sections }} />
          </>
        }
        journeyHeading="What happens when you reach out"
        journey={REAL_ESTATE_JOURNEY}
        journeyTimeline
        faq={faq.length ? {
          heading: "Property questions, answered",
          subheading: "What buyers usually ask before their first visit.",
          items: faq,
        } : undefined}
        ctaHeading="Ready to find your place?"
        ctaText="Leave your number and our real estate team will call you back about buying, renting or leasing a property."
        ctaLabel="Get a callback"
        ctaBanner
        businessLine="real_estate"
      />
    </>
  );
}
