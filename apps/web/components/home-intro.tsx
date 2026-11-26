import { CheckIcon } from "lucide-react";
import React from "react";

import { BUSINESS_FACTS } from "@/lib/site";

export const HOME_H1 = "Loans, cards and property in Hyderabad, matched to the right bank";

export const HOME_INTRO =
  "Dhanadhara is a loans and real estate platform for Hyderabad and Telangana. We match salaried and self-employed borrowers with banks, housing finance companies and NBFCs for loans from ₹1 lakh upward, and we list verified property in Hyderabad. You pay Dhanadhara nothing: the service is free for customers.";

export const HOME_FACTS: readonly string[] = [
  "11 loan types, plus credit cards",
  "No fee to Dhanadhara at any stage",
  "Apply online, with no office visit or document pickup",
  `${BUSINESS_FACTS.advisors} advisors who speak ${BUSINESS_FACTS.languages.slice(0, -1).join(", ")} and ${BUSINESS_FACTS.languages.at(-1)}`,
];

// The page's single, visible H1 with the answer-first summary and the four
// facts a borrower checks first. Sits directly under the campaign carousel.
export function HomeIntro({ title = HOME_H1, summary = HOME_INTRO }: {
  title?: string;
  summary?: string;
} = {}) {
  return (
    <section aria-labelledby="home-intro-heading" className="w-full border-t border-[var(--nav-border)] bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
        <h1
          id="home-intro-heading"
          className="max-w-4xl text-balance font-heading text-3xl font-semibold leading-tight tracking-tight text-brand-heading sm:text-4xl lg:text-5xl"
        >
          {title}
        </h1>
        <p className="mt-5 max-w-3xl text-lg leading-relaxed text-text-secondary">{summary}</p>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {HOME_FACTS.map((fact) => (
            <li key={fact} className="flex items-start gap-3 rounded-xl border border-border bg-surface-sky p-4 text-base text-text-primary">
              <CheckIcon className="mt-0.5 h-5 w-5 shrink-0 text-brand-link" aria-hidden />
              <span>{fact}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
