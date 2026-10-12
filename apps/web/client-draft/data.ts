// Explicitly illustrative content for the offline client draft only. This
// module is never imported by the Next application or a production API client.
import type { components } from "@contracts/generated/schema";
import { LOAN_PRODUCTS } from "@/lib/products";
import mobileProperty from "@/e2e/fixtures/mobile-property.json";

type Schemas = components["schemas"];
const updated = "2026-10-12T00:00:00Z";

export const products: Schemas["PublicFinancialProductRead"][] = LOAN_PRODUCTS.map((product, index) => ({
  id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  slug: product.id === "credit-cards" ? "credit-card" : product.id,
  label: product.label,
  category: product.group === "loans" ? "loan" : product.group === "insurance" ? "insurance" : "credit_card",
  summary: product.description,
  description: `Explore ${product.label.toLowerCase()} options with guidance at each step. Compare the information you need, prepare your documents and discuss the next step with our team.`,
  highlights: ["Guidance from enquiry to the next step", "Compare options in one place", "Understand the documents and process before applying"],
  eligibility: ["Requirements vary by provider and selected product", "Approval, pricing and terms are subject to provider assessment"],
  documents: ["Identity and address documents", "Income or business documents where applicable", "Product-specific documents requested through the secure application"],
  faq: [{ question: "Is approval guaranteed?", answer: "No. Eligibility, pricing and approval are assessed by the selected provider." }, { question: "How do I get started?", answer: "Explore the options and send an enquiry when the live service is available. This client review draft does not submit applications." }],
  homepage_featured: index < 3, provider_count: 1, updated_at: updated,
}));

export const sponsor: Schemas["PublicBannerRead"] = {
  id: "40000000-0000-4000-8000-000000000004",
  title: "A little planning. A bigger possibility.",
  subtitle: "A new home, higher education or the next step for your business. Explore loans, cards and insurance in one place, understand your options, and find the right starting point for your plans.",
  image_url: "/banner-templates/homepage_ad/personal-finance.webp",
  cta_label: "Explore options", deep_link: "/loans", rera_verified: false,
};

export const banners: Schemas["PublicBannerRead"][] = [
  { ...sponsor, id: "draft-finance", title: "Loans, cards, and insurance that fit you", subtitle: "Bring your plans closer. Explore financial options and find your next step with Dhanadhara.", image_url: "/banner-templates/financial_services/personal-loan.webp", cta_label: "Explore financial services", deep_link: "/loans" },
  { ...sponsor, id: "draft-property", title: "Find room for your next chapter", subtitle: "Explore homes, plots and commercial spaces. Start with what matters to you.", image_url: "/banner-templates/properties/villas.webp", cta_label: "Explore properties", deep_link: "/real-estate" },
];

const propertyRows = [
  ["apartments", "Apartment", "Two bedroom apartment with a spacious balcony", "/illustrations/properties/apartment-1.svg", "₹78 L", "sale"],
  ["apartments", "Apartment", "A bright apartment ready for your next move", "/illustrations/properties/apartment-1.svg", "₹28,000/month", "rent"],
  ["houses", "Independent House", "An independent home with room to grow", "/banner-templates/properties/individual-house.webp", "₹1.2 Cr", "sale"],
  ["villas", "Villa", "A family villa with garden space", "/banner-templates/properties/villas.webp", "₹1.8 Cr", "sale"],
  ["plots", "Plot", "A residential plot for your future home", "/banner-templates/properties/plots-land.webp", "₹45 L", "sale"],
  ["commercial", "Office", "A flexible workspace for your business", "/banner-templates/properties/commercial.webp", "₹55,000/month", "rent"],
] as const;

export const properties: Schemas["PublicPropertyDetailRead"][] = propertyRows.map(([category, type, title, image, price, intent], index) => ({
  ...mobileProperty,
  id: `50000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  title: `${title} · Illustrative listing`, category, type, image,
  listing_intent: intent, price_display: price,
  property_subtype: null, structured_details: null,
  construction_status: "ready", furnishing: "semi",
  rera_applicability: "unsure", rera_verification_status: "not_reviewed",
  listing_links: null, media: [], media_urls: [],
  security_deposit_display: intent === "rent" ? "Illustrative terms; confirm before applying" : null,
}));

export const previewNotice = "Client review draft. Listings and provider options are illustrative. Forms do not submit.";

function pageOf<T>(items: T[], url: URL) {
  const page = Math.max(1, Number(url.searchParams.get("page")) || 1);
  const page_size = Math.min(100, Math.max(1, Number(url.searchParams.get("page_size")) || 12));
  return { items: items.slice((page - 1) * page_size, page * page_size), total: items.length, page, page_size };
}

export function draftResponse(path: string): { status: number; data: unknown } {
  const url = new URL(path, "https://draft.invalid");
  const pathname = url.pathname;
  if (pathname === "/api/v1/public/banners") {
    const placement = url.searchParams.get("placement");
    return { status: 200, data: { banners: placement === "homepage_ad" ? [sponsor] : placement === "properties" ? [banners[1]] : placement === "financial_services" ? [banners[0]] : banners } };
  }
  if (pathname === "/api/v1/public/financial-products") {
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const category = url.searchParams.get("category");
    return { status: 200, data: pageOf(products.filter(p => (!category || p.category === category) && `${p.label} ${p.summary}`.toLowerCase().includes(q)), url) };
  }
  const match = pathname.match(/^\/api\/v1\/public\/financial-products\/([^/]+)(\/providers)?$/);
  if (match) {
    const product = products.find(p => p.slug === decodeURIComponent(match[1]));
    if (!product) return { status: 404, data: null };
    if (!match[2]) return { status: 200, data: product };
    const offer: Schemas["PublicProviderOfferRead"] = {
      id: product.id, offer_name: `${product.label} · Illustrative option`,
      summary: "Example provider card for design review. This is not a live offer or a commitment to lend or insure.",
      min_amount: null, max_amount: null, min_interest_rate: null, max_interest_rate: null,
      min_tenure_months: null, max_tenure_months: null,
      processing_fee_text: "Confirmed by the provider", eligibility_summary: "Subject to provider assessment",
      last_verified_at: updated,
      provider: { id: product.id, name: "Example provider", legal_name: "Illustrative provider", provider_type: product.category === "insurance" ? "other" : "bank", logo_url: null },
    };
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const type = url.searchParams.get("provider_type");
    return { status: 200, data: pageOf((!q || `${offer.offer_name} ${offer.provider.name}`.toLowerCase().includes(q)) && (!type || type === offer.provider.provider_type) ? [offer] : [], url) };
  }
  if (pathname === "/api/v1/public/properties") return { status: 200, data: { properties } };
  if (pathname.startsWith("/api/v1/public/properties/")) {
    const property = properties.find(p => p.id === pathname.split("/").pop());
    return { status: property ? 200 : 404, data: property ?? null };
  }
  if (pathname === "/api/v1/public/content-blocks/homepage-closing") return { status: 200, data: { slug: "homepage-closing", section: "homepage-closing", title: "Your plans. Our guidance.", body: "From finding the right financial option to exploring your next property, Dhanadhara brings the information and support together so you can take the next step with clarity.", business_line: null } };
  return { status: 404, data: null };
}
