import type { Metadata } from "next";
import { WebsitePageContent } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";
import { PrivacyContent } from "@/components/help/privacy-content";
export const metadata: Metadata = {
  title: "Privacy Policy | Dhanadhara",
  description: "How Dhanadhara collects, uses and protects your personal and KYC data, who it is shared with (only with your consent) and how to contact us.",
  alternates: { canonical: "/privacy" },
  openGraph: {
    title: "Privacy Policy | Dhanadhara",
    description: "How Dhanadhara collects, uses and protects your personal and KYC data, who it is shared with (only with your consent) and how to contact us.",
    type: "website",
    url: "/privacy",
  },
};
export default async function Page() {
  const published = await getWebsiteContent("page/privacy");
  return <WebsitePageContent content={published?.content} title="Privacy Policy" fallback={<PrivacyContent />} />;
}
