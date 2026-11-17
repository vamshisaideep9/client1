import type { Metadata } from "next";

import { AboutContent } from "@/components/about/about-content";
import { FaqSection } from "@/components/faq-section";
import { ABOUT_FAQ_ITEMS } from "@/lib/about";
import { faqPageJsonLd } from "@/lib/faq";
import { jsonLdScript, organizationJsonLd } from "@/lib/organization-jsonld";
import { SITE_URL } from "@/lib/site";

const TITLE = "About Dhanadhara: Loans & Property, Vikarabad, Telangana";
const DESCRIPTION =
  "Dhanadhara is a proprietorship run by R Rohini, registered under Udyam, matching Hyderabad and Telangana borrowers with banks and NBFCs since 2026.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/about" },
  openGraph: { title: TITLE, description: DESCRIPTION, type: "website", url: "/about" },
};

const aboutJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    organizationJsonLd(),
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: `${SITE_URL}/` },
        { "@type": "ListItem", position: 2, name: "About", item: `${SITE_URL}/about` },
      ],
    },
    faqPageJsonLd(ABOUT_FAQ_ITEMS),
  ],
};

export default function AboutPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(aboutJsonLd) }} />
      <AboutContent />
      <FaqSection
        id="about-faq"
        heading="Questions about Dhanadhara"
        items={ABOUT_FAQ_ITEMS}
      />
    </>
  );
}
