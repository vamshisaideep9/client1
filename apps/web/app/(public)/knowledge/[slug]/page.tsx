import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { WebsiteBody, WebsiteFaq } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";

type Props = { params: Promise<{ slug: string }> };

async function findArticle(slug: string) {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return null;
  return getWebsiteContent(`article/${slug}`);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const article = await findArticle(slug);
  if (!article) return {};
  const { title, summary } = article.content;
  const description = summary || article.content.body?.slice(0, 155);
  const url = `/knowledge/${slug}`;
  return {
    title, description, alternates: { canonical: url },
    openGraph: { title, description, url, type: "article", images: ["/brand/social.png"] },
  };
}

export default async function KnowledgeArticlePage({ params }: Props) {
  const article = await findArticle((await params).slug);
  if (!article) notFound();
  return (
    <>
      <div className="mx-auto max-w-4xl px-4 pt-8 sm:px-6">
        <Link href="/knowledge" className="inline-flex min-h-11 items-center text-brand-link hover:underline">Knowledge Sharing</Link>
      </div>
      <WebsiteBody content={article.content} primary />
      <WebsiteFaq items={article.content.faq} />
    </>
  );
}
