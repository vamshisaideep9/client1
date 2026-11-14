// Page-level SEO and long-form guide sections for published financial
// services (client drafts and titles sheet v2, 2026-11-12). Publication stays
// controlled by the API catalogue: an unpublished slug still 404s and is
// noindexed, and the product label, summary, highlights, eligibility, documents
// and FAQ remain Admin-editable data. Keys are catalogue slugs (`credit-cards`
// serves the public `/loans/credit-card`).

export type FinancialServiceSeo = { title: string; description: string; h1: string };

export const FINANCIAL_SERVICE_SEO: Readonly<Record<string, FinancialServiceSeo>> = {
  "home-loan": {
    title: "Home Loan in Hyderabad: Compare Banks & Rates | Dhanadhara",
    h1: "Home loans in Hyderabad from banks and housing finance companies",
    description: "Compare home loan offers from banks and HFCs for flats, villas and plots in Hyderabad and Telangana. Free for customers. Check eligibility online.",
  },
  "personal-loan": {
    title: "Personal Loan in Hyderabad: Compare Offers | Dhanadhara",
    h1: "Personal loans in Hyderabad and Telangana",
    description: "Compare personal loan offers from banks and NBFCs in Hyderabad and Telangana, from ₹1 lakh. Salaried or self-employed, free for customers.",
  },
  "business-loan": {
    title: "Business Loan in Hyderabad for MSMEs | Dhanadhara",
    h1: "Business loans for Hyderabad MSMEs and traders",
    description: "Working capital and term loans for MSMEs, traders and self-employed owners in Hyderabad and Telangana. Compare lenders and get a callback.",
  },
  "loan-against-property": {
    title: "Loan Against Property in Hyderabad (Mortgage Loan)",
    h1: "Loan against property in Hyderabad",
    description: "Borrow against your house, flat, plot or commercial property in Hyderabad. Compare loan against property offers from banks and NBFCs.",
  },
  "car-loan": {
    title: "Car Loan in Hyderabad: New & Used Cars | Dhanadhara",
    h1: "New and used car loans in Hyderabad",
    description: "Compare new and second-hand car loan offers in Hyderabad and Telangana. Check your EMI online and get a callback from an advisor, free of charge.",
  },
  "education-loan": {
    title: "Education Loan in Hyderabad: India & Abroad",
    h1: "Education loans for study in India and abroad",
    description: "Education loans for courses in India and abroad, with or without collateral. Compare banks and NBFCs online, free of charge, from Telangana.",
  },
  "vehicle-loan": {
    title: "Commercial Vehicle & Two-Wheeler Loans | Hyderabad",
    h1: "Commercial vehicle and two-wheeler loans",
    description: "Finance for two-wheelers, autos, trucks and commercial vehicles in Hyderabad and Telangana. Compare lender offers and get a callback from our team.",
  },
  "equipment-financing": {
    title: "Equipment & Machinery Finance in Hyderabad",
    h1: "Equipment and machinery financing",
    description: "Loans for machinery, medical, construction and office equipment for businesses in Hyderabad and Telangana. Compare offers from lenders.",
  },
  "school-funding": {
    title: "Loans for Schools & Colleges in Telangana | Dhanadhara",
    h1: "Funding for schools and educational institutions",
    description: "Funding for school and college buildings, buses, labs and working capital in Hyderabad and Telangana. Compare offers from banks and NBFCs.",
  },
  "secured-loans": {
    title: "Loan Against Mutual Funds, Shares & FDs | Dhanadhara",
    h1: "Loans against your investments",
    description: "Borrow against mutual funds, shares, fixed deposits or insurance policies without selling them. Compare loan against securities offers.",
  },
  "project-funding": {
    title: "Real Estate Project Finance for Builders | Hyderabad",
    h1: "Project finance for Hyderabad builders and developers",
    description: "Construction and project finance for residential and commercial developers in Hyderabad and Telangana. Share your project for a lender match.",
  },
  "credit-cards": {
    title: "Compare Credit Cards & Apply | Dhanadhara",
    h1: "Compare credit cards and apply",
    description: "Compare credit cards by fees, rewards and eligibility, then apply with help from our team. Check card EMI and payoff costs with free calculators.",
  },
  // Insurance stays unpublished until an IRDAI licence or a licensed tie-up is
  // confirmed; these only apply if Admin republishes a product.
  "life-insurance": {
    title: "Term & Life Insurance: Compare Plans | Dhanadhara",
    h1: "Compare term and life insurance plans",
    description: "Compare term and life insurance plans and work out how much cover your family needs with our free calculator. Get help choosing and applying.",
  },
  "health-insurance": {
    title: "Health Insurance in Hyderabad: Compare Plans",
    h1: "Health insurance plans for Hyderabad families",
    description: "Compare individual and family floater health insurance plans for Hyderabad. Size your cover with our calculator and get help with the application.",
  },
  "property-insurance": {
    title: "Home & Property Insurance | Dhanadhara",
    h1: "Home and property insurance",
    description: "Insure your house, flat or commercial property against fire, flood and theft. Compare home insurance plans, including cover for home loan borrowers.",
  },
  "travel-insurance": {
    title: "Travel Insurance: Compare Plans | Dhanadhara",
    h1: "Travel insurance for trips abroad",
    description: "Compare international and student travel insurance for medical cover, trip cancellation and lost baggage. Get help choosing a plan before you fly.",
  },
};

export type GuideLink = { label: string; href: string };
export type GuideBlock =
  | { kind: "paragraph"; text: string; link?: GuideLink }
  | { kind: "list"; items: readonly string[] }
  | { kind: "steps"; items: readonly string[] }
  | { kind: "table"; caption: string; head: readonly [string, string]; rows: readonly (readonly [string, string])[] };
export type GuideSection = { id: string; heading: string; blocks: readonly GuideBlock[] };

export const FINANCIAL_SERVICE_SECTIONS: Readonly<Record<string, readonly GuideSection[]>> = {
  "home-loan": [
    {
      id: "property-types",
      heading: "Property types we help finance",
      blocks: [
        { kind: "paragraph", text: "Flats, villas, open plots, under-construction projects and resale homes, in GHMC, HMDA, DTCP and gram panchayat limits. Each lender decides which property types and approvals it accepts, so we send your application only to lenders that fund your kind of property." },
      ],
    },
    {
      id: "loan-to-value",
      heading: "How much of the property a lender can fund",
      blocks: [
        { kind: "paragraph", text: "RBI caps the loan-to-value (LTV) ratio for housing loans by loan size:" },
        {
          kind: "table",
          caption: "Maximum home loan as a share of the property value (RBI LTV limits)",
          head: ["Loan amount", "Maximum loan as % of property value"],
          rows: [["Up to ₹30 lakh", "90%"], ["₹30 lakh to ₹75 lakh", "80%"], ["Above ₹75 lakh", "75%"]],
        },
        {
          kind: "paragraph",
          text: "You pay the rest as a down payment. Stamp duty and registration charges come on top and are not counted in the property value for LTV.",
          link: { label: "Estimate them with the stamp duty calculator", href: "/calculators/stamp-duty" },
        },
      ],
    },
    {
      id: "interest-rate",
      heading: "What decides your interest rate",
      blocks: [
        { kind: "paragraph", text: "Lenders set the rate; Dhanadhara does not. These factors usually move it:" },
        { kind: "list", items: [
          "your CIBIL score",
          "your income, and whether you are salaried or self-employed",
          "the loan amount compared with the property value",
          "the property type and its approval (HMDA, DTCP, GHMC or gram panchayat)",
          "the lender type: bank, housing finance company or NBFC",
        ] },
        {
          kind: "paragraph",
          text: "A small rate change adds up over a long tenure. A ₹30 lakh loan at 9% for 20 years costs about ₹26,992 a month.",
          link: { label: "Try your own numbers in the EMI calculator", href: "/calculators/emi" },
        },
      ],
    },
    {
      id: "how-it-works",
      heading: "How it works",
      blocks: [
        { kind: "steps", items: [
          "Fill in the online form with your income, the property and the amount you need.",
          "We match you with lenders that fund your profile and property.",
          "An advisor calls you during working hours to confirm eligibility and the document list.",
          "You upload documents online. The lender values the property, runs legal checks and decides.",
          "Once approved and the paperwork is signed, the lender pays the seller or builder.",
        ] },
        { kind: "paragraph", text: "Check what you could borrow before you apply.", link: { label: "Home loan eligibility calculator", href: "/calculators/loan-eligibility" } },
      ],
    },
  ],
  "personal-loan": [
    {
      id: "how-much",
      heading: "How much you can borrow",
      blocks: [
        { kind: "paragraph", text: "From ₹1 lakh upward. Your lender sets the maximum from your monthly income and the EMIs you already pay. Most lenders cap total EMIs at a share of your take-home pay, called FOIR (fixed obligations to income ratio). Closing a small loan or a card balance before applying can raise the amount you qualify for." },
        { kind: "paragraph", text: "See an estimate before you apply.", link: { label: "Loan eligibility calculator", href: "/calculators/loan-eligibility" } },
      ],
    },
    {
      id: "interest-rate",
      heading: "What decides your interest rate",
      blocks: [
        { kind: "paragraph", text: "Lenders set the rate; Dhanadhara does not. The usual factors:" },
        { kind: "list", items: [
          "your CIBIL score and repayment history",
          "your monthly income and employer, or business income if self-employed",
          "the EMIs you already pay",
          "the lender type: bank or NBFC",
        ] },
        { kind: "paragraph", text: "Compare what a rate change does to your EMI.", link: { label: "EMI calculator", href: "/calculators/emi" } },
        { kind: "paragraph", text: "If a dealer or lender quotes a flat rate, convert it before you compare.", link: { label: "Flat vs reducing rate calculator", href: "/calculators/flat-vs-reducing" } },
      ],
    },
    {
      id: "how-it-works",
      heading: "How it works",
      blocks: [
        { kind: "steps", items: [
          "Fill in the online form with your income, existing EMIs and the amount you need.",
          "We match you with banks and NBFCs that lend to your profile.",
          "An advisor calls you during working hours to confirm eligibility and documents.",
          "You upload documents online, and the lender reviews them.",
          "After approval, the lender pays the loan into your bank account.",
        ] },
      ],
    },
  ],
};
