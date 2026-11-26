import type { components } from "@contracts/generated/schema";
import type { FaqItem } from "@/lib/faq";

export type WebsiteContent = components["schemas"]["WebsiteContent"];
export type PublicWebsiteContent = components["schemas"]["PublicWebsiteContent"];

export const WEBSITE_PAGES = {
  "page/home": "Home",
  "page/home-closing": "Home closing section",
  "page/success-stories": "Success Stories",
  "page/milestones": "Journey and Milestones",
  "page/about": "About Dhanadhara",
  "page/contact": "Contact",
  "page/privacy": "Privacy Policy",
  "page/terms": "Terms and Conditions",
  "page/cookies": "Cookies",
  "page/knowledge": "Knowledge Sharing",
  "page/loans": "Financial Services",
  "page/real-estate": "Properties",
  "page/calculators": "Calculators",
  "page/get-started": "Get Started",
  "page/earn-with-us": "Earn With Us",
  "page/apply-as-agent": "Apply as Agent",
  "page/help-center": "Help Center",
} as const;

export function websiteKeyPath(key: string): string {
  return key.split("/").map(encodeURIComponent).join("/");
}

export function resolveWebsiteFaq(items: WebsiteContent["faq"], defaults: FaqItem[] = []): FaqItem[] {
  return items?.map(({ question, answer }) => ({ q: question, a: answer })) ?? defaults;
}
