import type { ReactNode } from "react";

import { FaqSection } from "@/components/faq-section";
import { faqPageJsonLd, type FaqItem } from "@/lib/faq";
import { jsonLdScript } from "@/lib/organization-jsonld";
import { resolveWebsiteFaq, type WebsiteContent } from "@/lib/website-content";

export function WebsiteBody({ content, label, primary = false }: {
  content?: Partial<WebsiteContent> | null;
  label?: string;
  primary?: boolean;
}) {
  if (!content?.title && !content?.summary && !content?.body && !content?.sections?.length) return null;
  const Title = primary ? "h1" : "h2";
  const SectionTitle = primary || !(content.title || label) ? "h2" : "h3";
  return (
    <section className="mx-auto max-w-4xl space-y-5 px-4 py-12 sm:px-6">
      {content.title || label ? (
        <Title className="font-heading text-3xl font-semibold text-brand-heading sm:text-4xl">
          {content.title || label}
        </Title>
      ) : null}
      {content.summary ? <p className="text-lg text-text-secondary">{content.summary}</p> : null}
      {content.body ? <p className="whitespace-pre-wrap break-words leading-7">{content.body}</p> : null}
      {content.sections?.map((section, index) => (
        <div key={index} className="space-y-2 rounded-xl border border-border bg-surface p-5">
          <SectionTitle className="font-heading text-xl font-semibold">{section.title}</SectionTitle>
          <p className="whitespace-pre-wrap break-words leading-7">{section.body}</p>
        </div>
      ))}
    </section>
  );
}

export function WebsiteFaq({ items, defaults, heading = "Frequently asked questions", ...options }: {
  items: WebsiteContent["faq"];
  defaults?: FaqItem[];
  heading?: string;
} & Pick<React.ComponentProps<typeof FaqSection>, "id" | "columns" | "size" | "subheading">) {
  const faq = resolveWebsiteFaq(items, defaults);
  if (!faq.length) return null;
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{
        __html: jsonLdScript({ "@context": "https://schema.org", ...faqPageJsonLd(faq) }),
      }} />
      <FaqSection heading={heading} items={faq} {...options} />
    </>
  );
}

export function WebsitePageContent({ content, fallback, title }: {
  content?: WebsiteContent | null;
  fallback: ReactNode;
  title: string;
}) {
  return (
    <>
      {content?.body?.trim()
        ? <WebsiteBody content={content} label={title} primary />
        : fallback}
      <WebsiteFaq items={content?.faq} />
    </>
  );
}
