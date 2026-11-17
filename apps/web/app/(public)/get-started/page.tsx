import type { Metadata } from "next";
import { HelpCenter } from "@/components/help/help-center";

export const metadata: Metadata = {
  title: "How to Get Started with Dhanadhara",
  description: "Create a free account with your mobile number, tell us which loan, card or property you need, and an advisor calls you back to take it forward.",
  alternates: { canonical: "/get-started" },
  openGraph: { title: "How to Get Started with Dhanadhara", description: "Create a free account with your mobile number, tell us which loan, card or property you need, and an advisor calls you back to take it forward.", url: "/get-started", images: ["/brand/social.png"] },
};

export default function Page() {
  return <HelpCenter started={true} />;
}
