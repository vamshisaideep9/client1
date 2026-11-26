import type { Metadata } from "next";
import { WebsiteBody, WebsiteFaq } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";
import { HelpCenter } from "@/components/help/help-center";

export const metadata: Metadata = {
  title: "Help Center | Dhanadhara",
  description: "Guides for your Dhanadhara account: sign-in and OTP issues, password and mobile recovery, documents, property visits, referrals and support tickets.",
  alternates: { canonical: "/help-center" },
  openGraph: { title: "Help Center | Dhanadhara", description: "Guides for your Dhanadhara account: sign-in and OTP issues, password and mobile recovery, documents, property visits, referrals and support tickets.", url: "/help-center", images: ["/brand/social.png"] },
};

export default async function Page() {
  const published = await getWebsiteContent("page/help-center");
  return <><HelpCenter started={false} /><WebsiteBody content={published?.content} /><WebsiteFaq items={published?.content.faq} /></>;
}
