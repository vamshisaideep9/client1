import type { Metadata } from "next";
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
export default function Page() { return <PrivacyContent />; }
