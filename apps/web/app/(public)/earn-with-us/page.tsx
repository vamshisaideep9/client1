import type { Metadata } from "next";

import { ClosingCta } from "@/components/closing-cta";
import { EarnAgentTracks } from "@/components/earn-with-us/agent-tracks";
import { EarnEligibility } from "@/components/earn-with-us/eligibility";
import { EarnHero } from "@/components/earn-with-us/hero";
import { EarnHowItWorks } from "@/components/earn-with-us/how-earning-works";
import { ReferAndEarn } from "@/components/earn-with-us/refer-and-earn";
import { WebsiteBody, WebsiteFaq } from "@/components/website-content";
import { AGENT_FAQ_ITEMS } from "@/lib/faq";
import { getWebsiteContent } from "@/lib/public-website-content";
import { SITE_NAME, SITE_URL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Become a Loan DSA Partner or Refer & Earn | Dhanadhara",
  description:
    "Join from anywhere in India as a loan DSA or real estate partner. Earn commission on closed deals, paid within 45 days. Free to join, KYC verified.",
  keywords: [
    "become a loan agent",
    "loan DSA registration",
    "real estate agent registration India",
    "RERA agent code",
    "real estate referral agent",
    "loan agent commission",
    "agent partner program",
    "refer and earn",
    "referral bonus",
  ],
  alternates: { canonical: "/earn-with-us" },
  openGraph: {
    title: "Become a Loan DSA Partner or Refer & Earn | Dhanadhara",
    description:
      "Join from anywhere in India as a loan DSA or real estate partner. Earn commission on closed deals, paid within 45 days. Free to join, KYC verified.",
    type: "website",
    url: "/earn-with-us",
  },
};

const earnWithUsJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: `${SITE_URL}/` },
        {
          "@type": "ListItem",
          position: 2,
          name: "Earn with Us",
          item: `${SITE_URL}/earn-with-us`,
        },
      ],
    },
  ],
  publisher: { "@type": "Organization", name: SITE_NAME, url: SITE_URL },
};

export default async function EarnWithUsPage() {
  const website = await getWebsiteContent("page/earn-with-us");
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(earnWithUsJsonLd) }}
      />
      <EarnHero title={website?.content.title} summary={website?.content.summary} />
      <ReferAndEarn />
      <EarnEligibility />
      <EarnHowItWorks />
      <EarnAgentTracks />
      <WebsiteBody content={website && { body: website.content.body, sections: website.content.sections }} />
      <WebsiteFaq
        id="agent-faq"
        heading="Questions, answered"
        subheading="Partners and referrals, everything people usually ask."
        items={website?.content.faq}
        defaults={AGENT_FAQ_ITEMS}
        columns={2}
        size="lg"
      />
      <ClosingCta
        heading="Ready to start earning?"
        text="Apply as a partner in a few minutes, or sign in to use your referral code."
        ctaLabel="Apply to become a partner"
        href="/apply-as-agent"
        id="apply"
      />
    </>
  );
}
