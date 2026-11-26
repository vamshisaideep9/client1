import { BRAND_ASSETS } from "@/lib/brand";
import { BUSINESS_FACTS, SITE_CONTACT, SITE_NAME, SITE_URL } from "@/lib/site";

export const ORGANIZATION_ID = `${SITE_URL}/#org`;

export const ORGANIZATION_DESCRIPTION =
  "Loans and real estate platform matching borrowers in Hyderabad and Telangana with banks, housing finance companies and NBFCs, and listing verified property in Hyderabad.";

/** Shared FinancialService node for the homepage and About page. Every value
 * comes from the client-confirmed facts the footer also renders, so the
 * structured data cannot drift from the visible page. */
export function organizationJsonLd() {
  return {
    "@type": "FinancialService",
    "@id": ORGANIZATION_ID,
    name: SITE_NAME,
    legalName: BUSINESS_FACTS.legalName,
    url: SITE_URL,
    logo: `${SITE_URL}${BRAND_ASSETS.horizontal.src}`,
    description: ORGANIZATION_DESCRIPTION,
    telephone: SITE_CONTACT.phoneHref.replace(/^tel:/, ""),
    email: SITE_CONTACT.email,
    foundingDate: BUSINESS_FACTS.founded,
    founder: { "@type": "Person", name: BUSINESS_FACTS.proprietor, jobTitle: "Proprietor" },
    identifier: {
      "@type": "PropertyValue",
      propertyID: "Udyam Registration Number",
      value: BUSINESS_FACTS.udyamNumber,
    },
    address: {
      "@type": "PostalAddress",
      streetAddress: BUSINESS_FACTS.officeStreet,
      addressLocality: BUSINESS_FACTS.officeLocality,
      addressRegion: BUSINESS_FACTS.region,
      addressCountry: "IN",
    },
    areaServed: [
      { "@type": "City", name: "Hyderabad" },
      { "@type": "State", name: "Telangana" },
    ],
    openingHoursSpecification: [
      {
        "@type": "OpeningHoursSpecification",
        dayOfWeek: [...BUSINESS_FACTS.openingDays],
        opens: BUSINESS_FACTS.opens,
        closes: BUSINESS_FACTS.closes,
      },
    ],
    knowsLanguage: [...BUSINESS_FACTS.languageCodes],
    numberOfEmployees: { "@type": "QuantitativeValue", value: BUSINESS_FACTS.advisors },
  };
}

/** Serialize JSON-LD for a <script> tag without allowing "</script>" breakout. */
export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
