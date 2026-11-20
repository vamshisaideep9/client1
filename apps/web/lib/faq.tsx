import type { ReactNode } from "react";

// Single source of truth for public-page FAQ copy (home, loans, real estate,
// earn-with-us). `a` is always plain text so every page can build FAQPage
// JSON-LD from the same array without the visible copy and the structured
// data drifting apart. `aRich`, when present, is what actually renders (e.g.
// an inline link); `a` still feeds the JSON-LD in that case.
export type FaqItem = { q: string; a: string; aRich?: ReactNode };

export function faqPageJsonLd(items: FaqItem[]) {
  return {
    "@type": "FAQPage",
    mainEntity: items.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
}

// Homepage FAQ (client drafts, 2026-11-12). The same array feeds the
// visible FAQ and the FAQPage JSON-LD.
export const HOME_FAQ_ITEMS: FaqItem[] = [
  {
    q: "Is Dhanadhara a bank?",
    a: "No. Dhanadhara does not lend money. We connect you with banks, housing finance companies and NBFCs, and the lender you choose approves the loan, sets the interest rate and pays out the money.",
  },
  {
    q: "Do I pay Dhanadhara any fee?",
    a: "No. Our service is free for customers at every stage, from enquiry to disbursal. The lender may charge its own processing fee, which appears in its loan offer before you accept.",
  },
  {
    q: "Which areas do you serve?",
    a: "We arrange loans for customers in Hyderabad and across Telangana, and list property in Hyderabad only. Our office is in Vikarabad, and the whole process runs online, so you never need to visit.",
  },
  {
    q: "Can I apply with a low CIBIL score?",
    a: "Yes, you can enquire. Each lender sets its own minimum credit score, and whether it approves you, and at what rate, is its decision. A lower score usually means fewer offers and a higher interest rate.",
  },
  {
    q: "Do I need to visit your office?",
    a: "No. You submit your details, upload documents and track progress online through your Dhanadhara account. An advisor calls you during working hours to guide each step until disbursal.",
  },
];

export const AGENT_FAQ_ITEMS: FaqItem[] = [
  {
    q: "Who can apply to become a partner?",
    a: "Anyone who can bring loan or real estate leads and pass our KYC check. No prior experience needed.",
  },
  {
    q: "Can I be a partner for both loans and real estate?",
    a: "No, every partner account is tied to one line only. You pick loans or real estate when you apply.",
  },
  {
    q: "Do real estate partners need to be RERA registered?",
    a: "Yes. A valid RERA agent code is required as part of your KYC for the real estate track.",
  },
  {
    q: "I am already a client. Can I convert to a partner?",
    a: "Yes. Existing clients can apply to convert to a partner account through the same KYC process.",
  },
  {
    q: "How is my commission decided?",
    a: "No fixed slab. It's set per deal once it closes, based on that loan or property.",
  },
  {
    q: "How and when do I get paid?",
    a: "Once a deal is approved, payout is made through Razorpay or by cheque.",
  },
  {
    q: "Is there any cost to apply?",
    a: "No, applying is free. We only need your details and KYC documents to verify you.",
  },
  {
    q: "What happens after I apply?",
    a: "We review your KYC. Once verified, your partner account is activated and you can start referring clients.",
  },
  {
    q: "Do I need to become a partner to refer someone?",
    a: "No. Any registered user gets a referral code and earns a referral bonus. Partners earn commission on the deals they work.",
  },
  {
    q: "How does the referral bonus work?",
    a: "Share your referral code. When your referral's purchase or loan goes through, you get a referral bonus via Razorpay or cheque.",
  },
];

export const LOAN_FAQ_ITEMS: FaqItem[] = [
  {
    q: "How do I know if I'm eligible?",
    a: "Each lender has its own criteria, usually based on your income, credit history, and the loan type. Leave your number and our team checks your profile against multiple lenders before suggesting one.",
  },
  {
    q: "What documents will I need?",
    a: "Typically PAN, Aadhaar, proof of income like salary slips or ITR, and recent bank statements. The exact list depends on the loan. Our team tells you upfront so there are no surprises.",
  },
  {
    q: "How long until the money reaches my account?",
    a: "It depends on the lender and loan type. Personal loans can disburse within a few days once approved. Property loans take longer because of valuation and legal checks. We stay with you until disbursal.",
  },
  {
    q: "Does the platform charge me anything?",
    a: "No. Comparing offers, getting matched, and the support from our team are all free for you. We earn from our lender partners, not from borrowers.",
  },
  {
    q: "Will comparing offers here affect my credit score?",
    a: "No. Enquiring with us does not touch your score. A credit check happens only when you actually apply with a lender, and we tell you before that step.",
  },
  {
    q: "Can I compare offers from more than one lender?",
    a: "Yes. That's the point. We put the options side by side so you can pick on rate, tenure, and processing fee instead of taking the first offer.",
  },
  {
    q: "Can I repay my loan early?",
    a: "Most lenders allow prepayment. Charges vary by lender and loan type, and floating rate loans often have none. We flag the prepayment terms before you sign so you know what early closure costs.",
  },
];

export const REAL_ESTATE_FAQ_ITEMS: FaqItem[] = [
  {
    q: "Are the listings really verified?",
    a: "Yes. Every listing and every partner goes through verification before it reaches you, including RERA checks where they apply. You never deal with an unverified party.",
  },
  {
    q: "How do site visits work?",
    a: "Once you enquire, our team calls to understand what you're looking for and schedules visits at times that suit you. A verified partner accompanies you on every visit.",
  },
  {
    q: "Do I pay for the property through the platform?",
    a: "No, never. Token, booking, and purchase payments go directly between you and the seller or builder. The only money that moves through us is referral bonuses or partner payouts.",
  },
  {
    q: "How does the booking and token process work?",
    a: "Your partner walks you through it. Once you pick a property, the token and booking amounts are paid directly to the seller or builder, and we help you track the paperwork from there.",
  },
  {
    q: "Do you check the legal side of a property?",
    a: "Before a listing goes live, we check its RERA registration, review its title documents, visit the site and complete KYC on the builder or seller. We still recommend a title check by your own lawyer before you pay a token amount.",
  },
  {
    q: "Can you also arrange the home loan?",
    a: "Yes. Our loans team works alongside your property purchase, so you can compare home loan offers and get the finance moving while the paperwork progresses.",
  },
  {
    q: "What happens after I leave my number?",
    a: "One of our team calls you back, understands your budget and preferences, and lines up matching verified properties. No spam, and your number is never sold or shared.",
  },
];
