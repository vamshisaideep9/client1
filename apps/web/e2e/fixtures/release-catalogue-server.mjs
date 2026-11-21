import { createServer } from "node:http";
import mobileProperty from "./mobile-property.json" with { type: "json" };

const HOST = "127.0.0.1";
const PORT = 4311;
const UPDATED_AT = "2026-08-30T00:00:00Z";
// Opt-in layout fixtures. Default remains the empty CMS/fallback scenario.
const publishedBanners = process.argv.includes("--published-banners");
const sponsor = process.argv.includes("--sponsor");
const fullCatalogue = process.argv.includes("--full-catalogue");
// banner-cta-and-offers.spec.ts: an https CTA on the hero and the sponsor
// strip, and a YouTube banner with no destination (its CTA defaults to the
// video). Opt-in so other suites keep their own banner scenarios.
const externalCta = process.argv.includes("--external-cta");
const externalCtaHero = [
  { id: "40000000-0000-4000-8000-000000000011", title: "Compare partner home loans", subtitle: "Synthetic external campaign.", image_url: "/banner-templates/homepage/loans.webp", cta_label: "Visit the partner", deep_link: "https://partner.example/home-loans", rera_verified: false },
  { id: "40000000-0000-4000-8000-000000000012", title: "Take the video tour", subtitle: "Synthetic YouTube campaign without a destination.", image_url: "/banner-templates/homepage/general.webp", cta_label: null, deep_link: null, rera_verified: false, youtube_video_id: "dQw4w9WgXcQ", video_url: null },
];
const externalCtaSponsor = {
  id: "40000000-0000-4000-8000-000000000013",
  title: "Plans from a verified partner",
  subtitle: "Synthetic external sponsor.",
  image_url: "/banner-templates/homepage_ad/personal-finance.webp",
  cta_label: "Compare plans",
  deep_link: "https://partner.example/plans",
  rera_verified: false,
};
const sponsorFixture = {
  id: "40000000-0000-4000-8000-000000000004",
  title: "A little planning. A bigger possibility.",
  subtitle: "A new home, higher education or the next step for your business. Explore loans, cards and insurance in one place, understand your options, and find the right starting point for your plans.",
  image_url: "/banner-templates/homepage_ad/personal-finance.webp",
  cta_label: "Explore options",
  deep_link: "/loans",
  rera_verified: false,
};
const bannerFixtures = [
  { id: "40000000-0000-4000-8000-000000000001", title: "Explore financial options", subtitle: "Synthetic published campaign with unchanged bundled artwork.", image_url: "/banner-templates/financial_services/personal-loan.webp", cta_label: "Explore loans", deep_link: "/loans", rera_verified: false },
  { id: "40000000-0000-4000-8000-000000000002", title: "Find a home that fits", subtitle: "Synthetic property campaign for responsive verification.", image_url: "/banner-templates/properties/villas.webp", cta_label: "Explore properties", deep_link: "/real-estate", rera_verified: true },
  { id: "40000000-0000-4000-8000-000000000003", title: "Guidance for your next step", subtitle: "A published campaign without artwork still has a complete text layout and a reachable action.", image_url: null, cta_label: "Contact us", deep_link: "/contact", rera_verified: false },
];

const PRODUCT_ROWS = [
  ["10000000-0000-4000-8000-000000000001", "personal-loan", "Personal Loan", "loan"],
  ["10000000-0000-4000-8000-000000000002", "business-loan", "Business Loan", "loan"],
  ["10000000-0000-4000-8000-000000000003", "home-loan", "Home Loan", "loan"],
  ["10000000-0000-4000-8000-000000000004", "credit-card", "Credit Card", "credit_card"],
  ["10000000-0000-4000-8000-000000000005", "health-insurance", "Health Insurance", "insurance"],
  ["10000000-0000-4000-8000-000000000006", "travel-insurance", "Travel Insurance", "insurance"],
];

// The default six-product release scenario stays deterministic. Visual review
// can opt into all 16 existing service types without changing live publication.
const completeRows = [
  ...PRODUCT_ROWS,
  ["10000000-0000-4000-8000-000000000007", "loan-against-property", "Loan Against Property", "loan"],
  ["10000000-0000-4000-8000-000000000008", "car-loan", "Car Loan", "loan"],
  ["10000000-0000-4000-8000-000000000009", "vehicle-loan", "Vehicle Loan", "loan"],
  ["10000000-0000-4000-8000-000000000010", "education-loan", "Education Loan", "loan"],
  ["10000000-0000-4000-8000-000000000011", "school-funding", "School Funding", "loan"],
  ["10000000-0000-4000-8000-000000000012", "secured-loans", "Secured Loans", "loan"],
  ["10000000-0000-4000-8000-000000000013", "od-and-dod", "OD and DOD", "loan"],
  ["10000000-0000-4000-8000-000000000014", "project-funding", "Project Funding", "loan"],
  ["10000000-0000-4000-8000-000000000015", "life-insurance", "Life Insurance", "insurance"],
  ["10000000-0000-4000-8000-000000000016", "property-insurance", "Property Insurance", "insurance"],
];

const products = (fullCatalogue ? completeRows : PRODUCT_ROWS).map(([id, slug, label, category]) => ({
  id,
  slug,
  label,
  category,
  summary: `${label} with guided Dhanadhara support.`,
  description: `Review ${label.toLowerCase()} options and continue inside Dhanadhara.`,
  highlights: ["Internal assisted journey", "Provider options in one place"],
  eligibility: ["Eligibility and approval are assessed by the selected provider"],
  documents: ["Documents are requested only during the secure application journey"],
  faq: [{ question: "Is approval guaranteed?", answer: "No. The provider makes the decision." }],
  homepage_featured: slug === "personal-loan",
  provider_count: slug === "personal-loan" ? 1 : 0,
  updated_at: UPDATED_AT,
}));

const providerOffer = {
  id: "20000000-0000-4000-8000-000000000001",
  offer_name: "Release Bank Personal Loan",
  summary: "A deterministic production-build browser fixture.",
  min_amount: null,
  max_amount: null,
  min_interest_rate: null,
  max_interest_rate: null,
  min_tenure_months: null,
  max_tenure_months: null,
  processing_fee_text: "Provider assessed",
  eligibility_summary: "Subject to provider review",
  last_verified_at: UPDATED_AT,
  provider: {
    id: "30000000-0000-4000-8000-000000000001",
    name: "Release Bank",
    legal_name: "Release Bank Limited",
    provider_type: "bank",
    logo_url: null,
  },
};

function json(response, status, body) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function listProducts(url) {
  const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
  const category = url.searchParams.get("category");
  const page = Math.max(Number(url.searchParams.get("page") ?? "1") || 1, 1);
  const pageSize = Math.max(Number(url.searchParams.get("page_size") ?? "12") || 12, 1);
  const filtered = products.filter(
    (product) =>
      (!category || product.category === category) &&
      (!q || `${product.label} ${product.summary} ${product.category}`.toLowerCase().includes(q)),
  );
  const offset = (page - 1) * pageSize;
  return {
    items: filtered.slice(offset, offset + pageSize),
    total: filtered.length,
    page,
    page_size: pageSize,
  };
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://${HOST}:${PORT}`);

  if (request.method !== "GET") {
    json(response, 405, { detail: "Method not allowed" });
    return;
  }
  if (url.pathname === "/health") {
    json(response, 200, { status: "ok" });
    return;
  }
  if (url.pathname === "/api/v1/public/banners") {
    const homepageAd = url.searchParams.get("placement") === "homepage_ad";
    const banners = externalCta
      ? (homepageAd ? [externalCtaSponsor] : url.searchParams.get("placement") === "homepage" ? externalCtaHero : [])
      : homepageAd
        ? (sponsor ? [sponsorFixture] : [])
        : (publishedBanners ? bannerFixtures : []);
    json(response, 200, { banners });
    return;
  }
  if (url.pathname === "/api/v1/public/properties") {
    json(response, 200, { properties: [mobileProperty] });
    return;
  }
  if (url.pathname === `/api/v1/public/properties/${mobileProperty.id}`) {
    json(response, 200, mobileProperty);
    return;
  }
  if (url.pathname === "/api/v1/public/financial-products") {
    json(response, 200, listProducts(url));
    return;
  }

  const providerMatch = url.pathname.match(
    /^\/api\/v1\/public\/financial-products\/([^/]+)\/providers$/,
  );
  if (providerMatch) {
    const slug = decodeURIComponent(providerMatch[1]);
    const items = slug === "personal-loan" ? [providerOffer] : [];
    json(response, 200, { items, total: items.length, page: 1, page_size: 9 });
    return;
  }

  const productMatch = url.pathname.match(/^\/api\/v1\/public\/financial-products\/([^/]+)$/);
  if (productMatch) {
    const product = products.find(({ slug }) => slug === decodeURIComponent(productMatch[1]));
    json(response, product ? 200 : 404, product ?? { detail: "Not found" });
    return;
  }

  json(response, 404, { detail: "Not found" });
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`Release catalogue fixture listening on http://${HOST}:${PORT}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
