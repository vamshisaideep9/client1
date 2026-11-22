import type { Metadata } from "next";
import Link from "next/link";

import { WebsiteBody, WebsiteFaq } from "@/components/website-content";
import { getWebsiteArticles, getWebsiteContent } from "@/lib/public-website-content";

const title = "Knowledge Sharing | Dhanadhara";
const description = "Read Dhanadhara guides on loans, financial products and property.";
export const metadata: Metadata = {
  title, description,
  alternates: { canonical: "/knowledge" },
  openGraph: { title, description, type: "website", url: "/knowledge", images: ["/brand/social.png"] },
};

export default async function KnowledgePage() {
  const [page, articles] = await Promise.all([getWebsiteContent("page/knowledge"), getWebsiteArticles()]);
  return (
    <>
      <WebsiteBody primary content={{ ...page?.content, title: page?.content.title || "Knowledge Sharing" }} />
      <section className="mx-auto grid max-w-4xl gap-4 px-4 pb-12 sm:px-6" aria-label="Articles">
        {articles.length === 0 ? <p className="text-text-secondary">No articles have been published yet.</p> : null}
        {articles.map(({ key, content }) => (
          <article key={key} className="rounded-xl border border-border bg-surface p-5">
            <h2 className="font-heading text-xl font-semibold">
              <Link href={`/knowledge/${key.slice("article/".length)}`} className="inline-flex min-h-11 items-center text-brand-link hover:underline">
                {content.title}
              </Link>
            </h2>
            {content.summary ? <p className="text-text-secondary">{content.summary}</p> : null}
          </article>
        ))}
      </section>
      <WebsiteFaq items={page?.content.faq} />
    </>
  );
}
