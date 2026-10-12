import React, { useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster, toast } from "sonner";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { AnnouncementBanner } from "@/components/announcement-banner";
import Home from "@/app/(public)/page";
import Loans from "@/app/(public)/loans/page";
import Service from "@/app/(public)/loans/[slug]/page";
import Properties from "@/app/(public)/real-estate/page";
import Property from "@/app/(public)/real-estate/properties/[propertyId]/page";
import Calculators from "@/app/(public)/calculators/page";
import Calculator from "@/app/(public)/calculators/[slug]/page";
import Contact from "@/app/(public)/contact/page";
import Agent from "@/app/(public)/apply-as-agent/page";
import Earn from "@/app/(public)/earn-with-us/page";
import Help from "@/app/(public)/help-center/page";
import Started from "@/app/(public)/get-started/page";
import Terms from "@/app/(public)/terms/page";
import Privacy from "@/app/(public)/privacy/page";
import Cookies from "@/app/(public)/cookies/page";
import { CALCULATOR_SLUGS } from "@/lib/calculators/registry";
import { navigate, NuqsAdapter, routeUrl, useLocation } from "./navigation";
import { products, properties, previewNotice } from "./data";
import { assetUrl } from "./image";

const staticPages = { "/": Home, "/calculators": Calculators, "/earn-with-us": Earn, "/help-center": Help, "/get-started": Started, "/terms": Terms, "/privacy": Privacy, "/cookies": Cookies };
export const routes = [...Object.keys(staticPages), "/loans", "/real-estate", "/contact", "/apply-as-agent", "/sitemap.xml", ...products.map(p => `/loans/${p.slug}`), ...properties.map(p => `/real-estate/properties/${p.id}`), ...CALCULATOR_SLUGS.map(s => `/calculators/${s}`)];
declare global { interface Window { __DRAFT_ROUTES__: string[]; } }
window.__DRAFT_ROUTES__ = routes;

// Only embedded resources may be fetched (Excel export loads its embedded logo).
// No live API, analytics or submission code can make an HTTP request.
const browserFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const value = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (value.startsWith("data:")) return browserFetch(value, init);
  if (window.__DRAFT_ASSETS__[value]) return browserFetch(assetUrl(value), init);
  throw new Error("Network requests are disabled in the offline client draft.");
};

async function resolvePage(url: URL): Promise<ReactNode> {
  const pathname = url.pathname.replace(/\/$/, "") || "/";
  const searchParams = Promise.resolve(Object.fromEntries(url.searchParams));
  if (pathname === "/sitemap.xml") return <section className="mx-auto max-w-5xl px-6 py-16"><h1 className="font-heading text-4xl font-semibold text-brand-heading">Explore the full website</h1><p className="my-5 text-text-secondary">Every page in this client review draft.</p><ul className="grid gap-3 sm:grid-cols-2">{routes.filter(route => route !== "/sitemap.xml").map(route => <li key={route}><a className="inline-flex min-h-11 items-center text-brand-link underline" href={`#${route}`}>{route === "/" ? "Home" : route}</a></li>)}</ul></section>;
  if (pathname in staticPages) { const Page = staticPages[pathname as keyof typeof staticPages]; return Page(); }
  if (pathname === "/loans") return Loans({ searchParams });
  if (pathname === "/real-estate") return Properties({ searchParams });
  if (pathname === "/contact") return Contact({ searchParams });
  if (pathname === "/apply-as-agent") return Agent({ searchParams });
  if (pathname.startsWith("/loans/")) return Service({ params: Promise.resolve({ slug: pathname.slice(7) }), searchParams });
  if (pathname.startsWith("/calculators/")) return Calculator({ params: Promise.resolve({ slug: pathname.slice(13) }) });
  if (pathname.startsWith("/real-estate/properties/")) return Property({ params: Promise.resolve({ propertyId: pathname.split("/").pop()! }) });
  throw new Error("This page is not included in the public client draft.");
}

function Draft() {
  const location = useLocation();
  const url = routeUrl(location);
  const [page, setPage] = useState<ReactNode>(null);
  const [error, setError] = useState("");
  const [loadedRoute, setLoadedRoute] = useState("");
  const previousDestination = useRef("");
  const pageKey = `${url.pathname}${url.search}`;
  useEffect(() => {
    let current = true;
    resolvePage(routeUrl(pageKey)).then(result => { if (current) { setPage(result); setError(""); setLoadedRoute(pageKey); } }, reason => { if (current) { setError(String(reason.message ?? reason)); setLoadedRoute(pageKey); } });
    return () => { current = false; };
  }, [pageKey]);
  useEffect(() => {
    if (!page) return;
    const destination = routeUrl();
    if (loadedRoute !== `${destination.pathname}${destination.search}`) return;
    document.title = `${document.querySelector("main h1")?.textContent ?? "Dhanadhara"} | Client draft`;
    const nextDestination = `${destination.pathname}${destination.hash}`;
    // Typing a calculator value or filtering must retain keyboard focus.
    if (previousDestination.current === nextDestination) return;
    previousDestination.current = nextDestination;
    if (destination.hash) document.getElementById(decodeURIComponent(destination.hash.slice(1)))?.scrollIntoView();
    else { window.scrollTo(0, 0); document.getElementById("main-content")?.focus({ preventScroll: true }); }
  }, [page, location, loadedRoute]);
  const links = products.map(({ slug, label, category }) => ({ slug, label, category }));
  return <NuqsAdapter>
    <a href="#main-content" className="sr-only focus:not-sr-only">Skip to main content</a>
    <AnnouncementBanner />
    <SiteHeader products={links} />
    <aside aria-label="Client draft notice" className="border-b border-border bg-surface-sky px-4 py-2 text-center text-xs text-text-secondary">{previewNotice}</aside>
    <main id="main-content" tabIndex={-1} key={url.pathname} data-draft-route={loadedRoute} aria-busy={loadedRoute !== pageKey}>
      {error ? <section className="mx-auto max-w-3xl px-6 py-20"><h1 className="text-3xl font-semibold">Page unavailable</h1><p className="my-4">{error}</p><a href="#/">Return home</a></section> : page ?? <p role="status" className="p-10">Opening the client draft…</p>}
    </main>
    <SiteFooter products={links} />
    <Toaster richColors position="bottom-right" />
  </NuqsAdapter>;
}

document.addEventListener("click", event => {
  if (!(event.target instanceof Element)) return;
  if (event.target.closest('input[type="file"]')) { event.preventDefault(); event.stopPropagation(); toast.info("Document uploads are disabled in this client draft."); return; }
  const link = event.target.closest<HTMLAnchorElement>("a[href]");
  if (!link || link.hasAttribute("download")) return;
  const href = link.getAttribute("href")!;
  if (href.startsWith("blob:") || href.startsWith("data:")) return;
  event.preventDefault();
  if (href.startsWith("#/")) navigate(href.slice(1));
  else if (href.startsWith("/") || href.startsWith("#")) navigate(href);
  else toast.info("Contact and external links are inactive in this client draft.");
});
document.addEventListener("submit", event => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault(); event.stopPropagation();
  if (form.getAttribute("method")?.toLowerCase() === "get") {
    const url = new URL(form.getAttribute("action") ?? routeUrl().pathname, routeUrl());
    url.search = new URLSearchParams([...new FormData(form)].filter((entry): entry is [string, string] => typeof entry[1] === "string")).toString();
    navigate(`${url.pathname}${url.search}${url.hash}`);
  } else toast.info("Preview only. Nothing was submitted.", { description: "This file does not save enquiries, send OTPs or upload documents. Please use fictional details while reviewing the form." });
}, true);

createRoot(document.getElementById("draft-root")!).render(<Draft />);
