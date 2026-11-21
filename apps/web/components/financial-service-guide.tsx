import Link from "next/link";
import React from "react";

import type { GuideBlock, GuideSection } from "@/lib/financial-service-content";

function Block({ block }: { block: GuideBlock }) {
  switch (block.kind) {
    case "paragraph":
      return (
        <p className="mt-4 leading-7 text-text-secondary">
          {block.text}
          {block.link ? (
            <>
              {" "}
              <Link href={block.link.href} className="font-medium text-brand-link underline underline-offset-4">
                {block.link.label}
              </Link>
              .
            </>
          ) : null}
        </p>
      );
    case "list":
      return (
        <ul className="mt-4 list-inside list-disc space-y-2 leading-7 text-text-secondary marker:text-brand-link">
          {block.items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      );
    case "steps":
      return (
        <ol className="mt-4 list-inside list-decimal space-y-2 leading-7 text-text-secondary marker:font-semibold marker:text-brand-link">
          {block.items.map((item) => <li key={item}>{item}</li>)}
        </ol>
      );
    case "table":
      return (
        <div className="mt-4 overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[20rem] border-collapse text-left text-sm">
            <caption className="sr-only">{block.caption}</caption>
            <thead className="bg-surface-sky text-text-primary">
              <tr>
                {block.head.map((cell) => <th key={cell} scope="col" className="px-4 py-3 font-semibold">{cell}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-border text-text-secondary">
              {block.rows.map(([amount, share]) => (
                <tr key={amount}>
                  <th scope="row" className="px-4 py-3 font-medium text-text-primary">{amount}</th>
                  <td className="px-4 py-3 tabular-nums">{share}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

// Long-form, server-rendered guide sections for a published financial
// service. Renders nothing for services without drafted sections.
export function FinancialServiceGuide({ sections }: { sections: readonly GuideSection[] | undefined }) {
  if (!sections?.length) return null;
  return (
    <section aria-label="Guide" className="border-t border-border bg-surface px-4 py-14 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-3xl">
        {sections.map((section, index) => (
          <section key={section.id} aria-labelledby={`guide-${section.id}`} className={index > 0 ? "mt-12" : undefined}>
            <h2 id={`guide-${section.id}`} className="font-heading text-2xl font-semibold text-foreground sm:text-3xl">
              {section.heading}
            </h2>
            {section.blocks.map((block, blockIndex) => <Block key={blockIndex} block={block} />)}
          </section>
        ))}
      </div>
    </section>
  );
}
