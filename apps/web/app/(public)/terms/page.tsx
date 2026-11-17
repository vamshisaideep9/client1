import type { Metadata } from "next";
import { TermsContent } from "@/components/help/terms-content";
export const metadata: Metadata = {
  title: "Terms of Use | Dhanadhara",
  description: "The terms that apply when you use Dhanadhara to compare loans, credit cards and property, or join as a partner or referrer, and how to raise a complaint.",
  alternates: { canonical: "/terms" },
  openGraph: {
    title: "Terms of Use | Dhanadhara",
    description: "The terms that apply when you use Dhanadhara to compare loans, credit cards and property, or join as a partner or referrer, and how to raise a complaint.",
    type: "website",
    url: "/terms",
  },
};
export default function Page() { return <TermsContent />; }
