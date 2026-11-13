import type { Metadata } from "next";
import { HelpCenter } from "@/components/help/help-center";

export const metadata: Metadata = {
  title: "Help Center | Dhanadhara",
  description: "Guides for your Dhanadhara account: sign-in and OTP issues, password and mobile recovery, documents, property visits, referrals and support tickets.",
  alternates: { canonical: "/help-center" },
  openGraph: { title: "Help Center | Dhanadhara", description: "Guides for your Dhanadhara account: sign-in and OTP issues, password and mobile recovery, documents, property visits, referrals and support tickets.", url: "/help-center", images: ["/brand/social.png"] },
};

export default function Page() {
  return <HelpCenter started={false} />;
}
