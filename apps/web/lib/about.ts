import type { FaqItem } from "@/lib/faq";
import { BUSINESS_FACTS, SITE_CONTACT } from "@/lib/site";

// About page copy (client drafts, 2026-11-12). Facts come from BUSINESS_FACTS
// and SITE_CONTACT so the page, footer and Organization schema always agree.

export const ABOUT_INTRO = `Dhanadhara is a loans and real estate platform based in ${BUSINESS_FACTS.officeLocality}, ${BUSINESS_FACTS.region}. Started in ${BUSINESS_FACTS.founded} by ${BUSINESS_FACTS.proprietor}, it matches borrowers in Hyderabad and Telangana with banks, housing finance companies and NBFCs, lists verified property in Hyderabad, and pays partners commission on the deals they bring.`;

export const ABOUT_WHO = `${BUSINESS_FACTS.proprietor} is the proprietor. The management team brings ${BUSINESS_FACTS.experience}. Five advisors handle customer calls in ${BUSINESS_FACTS.languages.slice(0, -1).join(", ")} and ${BUSINESS_FACTS.languages.at(-1)}.`;

export const ABOUT_WHAT_WE_DO: readonly { label: string; text: string }[] = [
  { label: "Loans", text: "11 loan types, from ₹1 lakh upward, for salaried and self-employed customers in Hyderabad and Telangana." },
  { label: "Property", text: "flats, villas, plots, resale homes, rentals and commercial space in Hyderabad." },
  { label: "Partners", text: "loan DSA and real estate partners from anywhere in India, paid within 45 days of a closed deal." },
  { label: "Calculators", text: "free tools for EMI, eligibility, stamp duty and more." },
];

export const ABOUT_HOW_WE_WORK: readonly string[] = [
  "We are not a bank and we don't lend. The lender approves the loan and sets the rate, tenure and document list.",
  "Customers pay Dhanadhara nothing.",
  "We never promise guaranteed approval.",
  "Everything happens online. We don't collect documents in person.",
  "We share your details with a lender only with your consent.",
  "Every property listing is RERA-checked and its title documents reviewed, the site is visited, and the builder or seller completes KYC before it goes live. We still recommend a title check by your own lawyer before you pay.",
];

export function aboutBusinessDetails(): readonly { label: string; value: string }[] {
  return [
    { label: "Business name", value: BUSINESS_FACTS.legalName },
    { label: "Business type", value: BUSINESS_FACTS.businessType },
    { label: "Proprietor", value: BUSINESS_FACTS.proprietor },
    { label: "Udyam Registration No.", value: BUSINESS_FACTS.udyamNumber },
    { label: "Started", value: BUSINESS_FACTS.founded },
    { label: "Office", value: SITE_CONTACT.address.join(", ") },
    { label: "Phone", value: SITE_CONTACT.phone },
    { label: "Email", value: SITE_CONTACT.email },
    { label: "Hours", value: SITE_CONTACT.hours.join(", ") },
    { label: "Languages", value: BUSINESS_FACTS.languages.join(", ") },
  ];
}

export const ABOUT_FAQ_ITEMS: FaqItem[] = [
  {
    q: "Is Dhanadhara a registered business?",
    a: `Yes. Dhanadhara is a proprietorship owned by ${BUSINESS_FACTS.proprietor} and registered as an MSME under Udyam Registration No. ${BUSINESS_FACTS.udyamNumber}. The office is in ${BUSINESS_FACTS.officeStreet}, ${BUSINESS_FACTS.officeLocality}, ${BUSINESS_FACTS.region}.`,
  },
  {
    q: "Where does Dhanadhara work?",
    a: "We arrange loans across Hyderabad and Telangana and list property in Hyderabad. Partners can join from anywhere in India. All customer work happens online and by phone from our Vikarabad office.",
  },
];
