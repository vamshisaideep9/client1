import type { Metadata } from "next";

import { AboutContent } from "@/components/about/about-content";
import { WebsiteBody, WebsiteFaq } from "@/components/website-content";
import { ABOUT_FAQ_ITEMS } from "@/lib/about";
import { jsonLdScript, organizationJsonLd } from "@/lib/organization-jsonld";
import { getWebsiteContent } from "@/lib/public-website-content";
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
  ],
};

export default async function AboutPage() {
  const [about, stories, milestones] = await Promise.all([
    getWebsiteContent("page/about"),
    getWebsiteContent("page/success-stories"),
    getWebsiteContent("page/milestones"),
  ]);
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(aboutJsonLd) }} />
      {about?.content.body?.trim()
        ? <WebsiteBody content={about.content} label="About Dhanadhara" primary />
        : <><AboutContent /><WebsiteBody content={about?.content} /></>}
      <WebsiteBody content={stories?.content} label="Success Stories" />
      <WebsiteBody content={milestones?.content} label="Our Journey and Milestones" />
      <WebsiteFaq id="about-faq" heading="Questions about Dhanadhara" items={about?.content.faq} defaults={ABOUT_FAQ_ITEMS} />
    </>
  );
}
