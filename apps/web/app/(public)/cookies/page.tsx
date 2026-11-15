import type { Metadata } from "next";
import { CookiesContent } from "@/components/help/cookies-content";
export const metadata: Metadata = {
  title: "Cookie Policy | Dhanadhara",
  description: "Which cookies Dhanadhara uses on its website and app, what each one does, how long it lasts, and how to change your cookie settings in your browser.",
  alternates: { canonical: "/cookies" },
  openGraph: {
    title: "Cookie Policy | Dhanadhara",
    description: "Which cookies Dhanadhara uses on its website and app, what each one does, how long it lasts, and how to change your cookie settings in your browser.",
    type: "website",
    url: "/cookies",
  },
};
export default function Page() { return <CookiesContent />; }
