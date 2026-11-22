import type { Metadata } from "next";

import { HeroCarousel } from "@/components/hero-carousel";
import { FinancialServicesCatalogue } from "@/components/financial-services-catalogue";
import { ProductPage } from "@/components/product-page";
import { TrustStrip } from "@/components/trust-strip";
import { faqPageJsonLd, LOAN_FAQ_ITEMS } from "@/lib/faq";
import { WebsiteBody } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";
import { jsonLdScript } from "@/lib/organization-jsonld";
import { resolveWebsiteFaq } from "@/lib/website-content";
import { getPublishedServiceProducts } from "@/lib/financial-catalog";
import { buildServiceDirectory } from "@/lib/service-directory";
import { parseCatalogueCategory } from "@/lib/financial-catalogue-url";
import { getHeroBanners } from "@/lib/public-banners";
import { LOAN_JOURNEY, LOAN_TRUST } from "@/lib/products";
import { SITE_NAME, SITE_URL } from "@/lib/site";

// Product visibility follows Admin changes on the next request. Banner fetches
// retain their own cache window independently of the live catalogue.
export const revalidate = 0;

export const metadata: Metadata = {
  title: "Compare Loans & Credit Cards in Hyderabad | Dhanadhara",
  description:
    "11 loan types and credit cards in one place, free for customers. Share your needs once, compare offers from banks and NBFCs and get a callback.",
  keywords: [
    "personal loan",
    "business loan",
    "home loan",
    "loan against property",
    "car loan",
    "vehicle loan",
    "education loan",
    "school funding",
    "secured loans",
    "overdraft loan",
    "project funding",
    "credit cards",
    "apply for loan",
  ],
  alternates: { canonical: "/loans" },
  openGraph: {
    title: "Compare Loans & Credit Cards in Hyderabad | Dhanadhara",
    description:
      "11 loan types and credit cards in one place, free for customers. Share your needs once, compare offers from banks and NBFCs and get a callback.",
    type: "website",
  },
};

const loansJsonLd = (faq: typeof LOAN_FAQ_ITEMS) => ({
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: `${SITE_URL}/` },
        {
          "@type": "ListItem",
          position: 2,
          name: "Loans",
          item: `${SITE_URL}/loans`,
        },
      ],
    },
    ...(faq.length ? [faqPageJsonLd(faq)] : []),
  ],
  publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
});

type LoansSearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function LoansPage({ searchParams }: { searchParams: LoansSearchParams }) {
  const params = await searchParams;
  const q = one(params.q)?.trim() || undefined;
  const category = parseCatalogueCategory(one(params.category));
  const requestedPage = Number(one(params.page) ?? "1");
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const [banners, published, website] = await Promise.all([
    getHeroBanners("financial_services"),
    getPublishedServiceProducts(),
    getWebsiteContent("page/loans"),
  ]);
  const faq = resolveWebsiteFaq(website?.content.faq, LOAN_FAQ_ITEMS);
  const { catalogue, facets } = buildServiceDirectory(published, { q, category, page });

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdScript(loansJsonLd(faq)) }}
      />
      <ProductPage
        title={website?.content.title || "Compare loans and credit cards in Hyderabad"}
        intro={website?.content.summary || "11 loan types and credit cards from banks, housing finance companies and NBFCs, free for customers in Hyderabad and Telangana. Share your needs once, and an advisor calls you back and stays with you until the money reaches your account."}
        heroDoodles
        beforeHero={
          banners.length > 0 ? (
            <HeroCarousel
              banners={banners}
              variant="section"
              label="Financial services campaigns"
            />
          ) : null
        }
        beforeJourney={
          <>
            <FinancialServicesCatalogue
              catalogue={catalogue}
              facets={facets}
              query={{ q, category, page }}
            />
            <TrustStrip points={LOAN_TRUST} />
            <WebsiteBody content={website && { body: website.content.body, sections: website.content.sections }} />
          </>
        }
        journeyHeading="What happens when you apply?"
        journey={LOAN_JOURNEY}
        journeyTimeline
        faq={faq.length ? {
          heading: "Loan questions, answered",
          subheading: "What borrowers usually ask before applying.",
          items: faq,
        } : undefined}
        ctaHeading="Ready to get started?"
        ctaText="Leave your number and our loans team will call you back to match you with the right lender."
        ctaLabel="Get a callback"
        ctaBanner
        businessLine="loans"
      />
    </>
  );
}
