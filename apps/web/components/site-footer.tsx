import * as React from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";

import { FOOTER_COLUMNS, LEGAL_LINKS } from "@/components/footer-links";
import { Logo } from "@/components/logo";
import { BUSINESS_FACTS, SITE_CONTACT, SITE_NAME, SITE_WHATSAPP_HREF, TRUST_LINES } from "@/lib/site";
import type { PublicServiceLink } from "@/components/navbars/financial-services-menu";

// Server-rendered navigation with native office disclosure on small screens.
// Public product details remain publication-controlled in their catalogue.
export function SiteFooter({ products = [] }: { products?: readonly PublicServiceLink[] }) {
  const year = new Date().getFullYear();
  const columns = FOOTER_COLUMNS.map((column) => ({
    ...column,
    links: column.links.filter((link) => link.href !== "/loans" || products.length > 0),
  }));

  const officeDetails = (
    <div className="space-y-3 text-sm leading-6 text-text-secondary">
      <address className="not-italic">{SITE_CONTACT.address.join(", ")}</address>
      <p>{SITE_CONTACT.hours.join(" · ")}</p>
    </div>
  );

  return (
    <footer className="w-full border-t border-border bg-surface text-text-primary dark:bg-surface-sky">
      <div className="mx-auto max-w-7xl px-4 pb-6 pt-10 sm:px-6 sm:pb-8 sm:pt-14 lg:px-8">
        <div className="flex flex-col items-start justify-between gap-5 border-b border-border pb-8 sm:flex-row sm:items-center sm:gap-12 sm:pb-10">
          <Logo className="w-52 sm:w-52" sizes="208px" />
          <div className="max-w-xl space-y-1.5 text-sm leading-6 text-text-secondary">
            {[TRUST_LINES.finance, TRUST_LINES.property].map((line) => (
              <p key={line.lead}>
                <span className="font-medium text-brand-heading">{line.lead}</span> {line.rest}
              </p>
            ))}
          </div>
        </div>

        <div className="grid gap-8 py-8 sm:gap-12 sm:py-10 md:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:gap-24">
          <nav aria-label="Footer" className="grid grid-cols-2 gap-6 sm:gap-12">
            {columns.map((column) => (
              <div key={column.heading}>
                <h2 className="font-heading text-sm font-semibold text-brand-heading">{column.heading}</h2>
                <ul className="mt-3">
                  {column.links.map((link) => (
                    <li key={link.href}>
                      <Link href={link.href} className="inline-flex min-h-11 items-center rounded-sm py-2 text-sm leading-6 text-text-secondary transition-colors hover:text-brand-link focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <div className="min-w-0 border-t border-border pt-7 md:border-l md:border-t-0 md:pl-10 md:pt-0 lg:pl-12">
            <h2 className="font-heading text-sm font-semibold text-brand-heading">Get in touch</h2>
            <div className="mt-3 flex flex-col items-start">
              <a href={SITE_CONTACT.phoneHref} className="pressable inline-flex min-h-11 items-center rounded-sm py-2 text-base font-medium text-brand-heading transition-colors hover:text-brand-link focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                Call {SITE_CONTACT.phone}
              </a>
              <a href={SITE_WHATSAPP_HREF} className="inline-flex min-h-11 items-center rounded-sm py-2 text-sm font-medium text-brand-link hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                WhatsApp
              </a>
              <a href={SITE_CONTACT.emailHref} className="pressable inline-flex min-h-11 max-w-full items-center break-all rounded-sm py-2 text-sm text-text-secondary transition-colors hover:text-brand-link focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                {SITE_CONTACT.email}
              </a>
            </div>
            <div className="mt-4 hidden md:block">{officeDetails}</div>
            <details className="faq-details group mt-2 md:hidden">
              <summary className="flex min-h-11 w-fit cursor-pointer list-none items-center gap-3 rounded-sm py-2 text-sm text-text-secondary marker:content-none hover:text-brand-link focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                Office &amp; opening hours
                <ChevronDown aria-hidden className="h-4 w-4 shrink-0 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none" />
              </summary>
              <div className="pb-2 pt-3">{officeDetails}</div>
            </details>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t border-border pt-5 text-xs text-text-secondary sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="space-y-1">
            <p>&copy; {year} {SITE_NAME}. All rights reserved.</p>
            <p>
              {BUSINESS_FACTS.businessType} of {BUSINESS_FACTS.proprietor} · Udyam {BUSINESS_FACTS.udyamNumber}
            </p>
          </div>
          <nav aria-label="Legal" className="flex flex-wrap items-center gap-x-5">
            {LEGAL_LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="inline-flex min-h-11 items-center rounded-sm py-2 hover:text-brand-link focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </footer>
  );
}
