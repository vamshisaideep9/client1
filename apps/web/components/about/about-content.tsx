import * as React from "react";

import {
  ABOUT_HOW_WE_WORK,
  ABOUT_INTRO,
  ABOUT_WHAT_WE_DO,
  ABOUT_WHO,
  aboutBusinessDetails,
} from "@/lib/about";

function SectionHeading({ id, children }: { id: string; children: string }) {
  return (
    <h2 id={id} className="mt-10 font-heading text-xl font-semibold text-[var(--nav-text)] sm:text-2xl">
      {children}
    </h2>
  );
}

// Server-rendered About page body. Copy lives in lib/about.ts; every business
// fact resolves from the same source as the footer and Organization schema.
export function AboutContent() {
  return (
    <div className="w-full bg-surface-sky px-4 py-10 sm:px-6 sm:py-14">
      <article className="mx-auto max-w-3xl rounded-2xl border border-border bg-surface px-5 py-10 leading-relaxed sm:px-10 sm:py-12">
        <h1 className="font-heading text-3xl font-semibold leading-tight tracking-tight text-[var(--nav-text)] sm:text-4xl">
          About Dhanadhara
        </h1>
        <p className="mt-6 text-lg text-[var(--nav-text)]">{ABOUT_INTRO}</p>

        <div className="mt-2 text-base text-text-secondary">
          <section aria-labelledby="about-who">
            <SectionHeading id="about-who">Who runs Dhanadhara</SectionHeading>
            <p className="mt-4">{ABOUT_WHO}</p>
          </section>

          <section aria-labelledby="about-what">
            <SectionHeading id="about-what">What we do</SectionHeading>
            <ul className="mt-4 list-inside list-disc space-y-2 marker:text-brand-link">
              {ABOUT_WHAT_WE_DO.map((item) => (
                <li key={item.label}>
                  <span className="font-semibold text-text-primary">{item.label}:</span> {item.text}
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="about-how">
            <SectionHeading id="about-how">How we work</SectionHeading>
            <ul className="mt-4 list-inside list-disc space-y-2 marker:text-brand-link">
              {ABOUT_HOW_WE_WORK.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="about-details">
            <SectionHeading id="about-details">Business details</SectionHeading>
            <dl className="mt-4 divide-y divide-border overflow-hidden rounded-xl border border-border">
              {aboutBusinessDetails().map((row) => (
                <div key={row.label} className="grid gap-1 px-4 py-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-4">
                  <dt className="font-medium text-text-primary">{row.label}</dt>
                  <dd className="min-w-0 break-words">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </article>
    </div>
  );
}
