import { WebsiteContentEditor } from "@/features/admin/website-content-editor";
import { CALCULATORS } from "@/lib/calculators/registry";
import { getPublishedServiceProducts } from "@/lib/financial-catalog";
import { getPublicPropertyTypes } from "@/lib/public-properties";

export default async function WebsiteContentPage({ searchParams }: {
  searchParams: Promise<{ key?: string }>;
}) {
  const [{ key }, products, types] = await Promise.all([
    searchParams, getPublishedServiceProducts(), getPublicPropertyTypes(),
  ]);
  const initialKey = typeof key === "string" && /^[a-z0-9/-]{1,160}$/.test(key) ? key : undefined;
  const destinations = Object.fromEntries([
    ...products.map(({ slug, label }) => [`page/loans/${slug}`, label]),
    ...CALCULATORS.map(({ slug, navLabel }) => [`page/calculators/${slug}`, `${navLabel} calculator`]),
    ...types.map(({ code, label }) => [`property-type/${code.replaceAll("_", "-")}`, `${label} FAQs`]),
  ]);
  return <WebsiteContentEditor key={initialKey} initialKey={initialKey} destinations={destinations} />;
}
