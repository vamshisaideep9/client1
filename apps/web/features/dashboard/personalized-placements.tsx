"use client";

import * as React from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check, Copy, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LoadingRegion } from "@/components/ui/loading-region";
import { Skeleton } from "@/components/ui/skeleton";
import { isAllowedAssetUrl } from "@/lib/allowed-asset-url";
import { resolveBannerCta } from "@/lib/banner-cta";
import {
  listAuthenticatedPlacements,
  type AuthenticatedBanner,
  type AuthenticatedOffer,
  type AuthenticatedPlacement,
} from "@/lib/personalization-api";
import { cn } from "@/lib/utils";

import { DASHBOARD_ICONS } from "./dashboard-icons";

type BusinessLine = "loans" | "real_estate";

// Shared by the dashboard list and the CMS offer preview so the two cannot
// drift: offers stack in one column, each a horizontal banner from md up.
export const OFFER_LIST_CLASS = "grid gap-3";

// Dashboard workspaces show eligible offer cards without promotional banners.
// The banner renderer below remains available to the campaign editing preview.
export function PersonalizedPlacements({ businessLine }: { businessLine: BusinessLine }) {
  const [placement, setPlacement] = React.useState<AuthenticatedPlacement | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    setPlacement(null);
    void (async () => {
      const result = await listAuthenticatedPlacements(businessLine);
      if (!active) return;
      setPlacement(result.ok ? result.data : null);
      setLoading(false);
    })();
    return () => { active = false; };
  }, [businessLine]);

  if (loading) {
    return (
      <LoadingRegion label="Loading offers" className={cn("mx-auto mb-6 w-full max-w-[1440px] px-4 sm:px-6 lg:px-8", OFFER_LIST_CLASS)}>
        {/* Two rows near the real card height: tall stacked cards on phones,
            shorter horizontal banners from md. */}
        {Array.from({ length: 2 }, (_, index) => <Skeleton key={index} className="h-80 rounded-2xl md:h-72" />)}
      </LoadingRegion>
    );
  }

  const offers = placement?.offers ?? [];
  if (!offers.length) return null;

  return (
    <section aria-label="Dashboard highlights" className="mx-auto mb-6 w-full max-w-[1440px] space-y-3 px-4 sm:px-6 lg:px-8">
      <ul className={OFFER_LIST_CLASS} aria-label="Offers for you">
        {offers.map((offer) => <li key={offer.id}><DashboardOfferCard offer={offer} /></li>)}
      </ul>
    </section>
  );
}

function discountLabel(offer: AuthenticatedOffer): string {
  if (offer.discount_type === "percentage") return `${offer.discount_value}% off`;
  if (offer.discount_type === "cashback-tie") return "Cashback";
  return `₹${offer.discount_value} off`;
}

// A horizontal banner from md up (artwork left, terms right), stacked on
// phones -- the same composition as the public sponsor strip (AdStrip).
export function DashboardOfferCard({ offer, interactive = true }: { offer: AuthenticatedOffer; interactive?: boolean }) {
  const [copied, setCopied] = React.useState(false);
  const imageUrl = isAllowedAssetUrl(offer.image_url) ? offer.image_url : null;

  async function copyCode() {
    if (!offer.code) return;
    try {
      await navigator.clipboard.writeText(offer.code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article
      data-layout="offer-banner"
      className={cn(
        "grid overflow-hidden rounded-2xl border border-border bg-card shadow-sm",
        imageUrl && "md:grid-cols-[minmax(0,40%)_minmax(0,1fr)]",
      )}
    >
      {imageUrl ? (
        // Phones keep the 16:7 strip above the copy. From md the artwork
        // column stretches to the copy's height and crops (object-cover),
        // never stretching the image itself.
        <div className="relative aspect-[16/7] bg-[var(--nav-tint)] md:aspect-auto md:min-h-56">
          <Image src={imageUrl} alt="" fill sizes="(min-width: 1440px) 560px, (min-width: 768px) 40vw, 100vw" className="object-cover" />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-col gap-3 p-4 sm:p-5 lg:px-7">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-link"><DASHBOARD_ICONS.offers className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="truncate">{offer.partner_name}</span></span>
          <Badge variant="secondary">{discountLabel(offer)}</Badge>
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold leading-snug text-text-primary [overflow-wrap:anywhere]">{offer.title}</h2>
          {offer.description ? <p className="text-sm text-text-secondary">{offer.description}</p> : null}
        </div>
        <div className="flex max-w-md items-center justify-between gap-3 rounded-lg border border-dashed border-border px-3 py-2">
          <div className="min-w-0"><p className="text-[11px] uppercase tracking-wide text-text-secondary">Coupon code</p><code className="block truncate text-sm font-semibold text-text-primary">{offer.code}</code></div>
          <Button type="button" variant="ghost" size="sm" disabled={!interactive} onClick={() => void copyCode()} aria-live="polite">{copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}{copied ? "Copied" : "Copy"}</Button>
        </div>
        <p className="text-xs leading-5 text-text-secondary">Copy the code, open the partner checkout, and enter it before payment. Dhanadhara does not apply or track redemption.</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button asChild={interactive} disabled={!interactive} size="sm">{interactive ? <a href={offer.redemption_url} target="_blank" rel="noopener noreferrer">Use offer<ExternalLink className="h-4 w-4" aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a> : <>Use offer<ExternalLink className="h-4 w-4" aria-hidden="true" /></>}</Button>
          {offer.terms_url ? interactive ? <a href={offer.terms_url} target="_blank" rel="noopener noreferrer" className="rounded-sm text-xs font-medium text-brand-link underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Full terms<span className="sr-only"> (opens in a new tab)</span></a> : <span className="text-xs font-medium text-brand-link">Full terms</span> : null}
        </div>
        <p className="text-xs text-text-secondary">{offer.terms_summary}</p>
      </div>
    </article>
  );
}

const DASHBOARD_CTA_CLASS = "mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:bg-surface-sky";

export function DashboardBannerCard({ banner, interactive = true }: { banner: AuthenticatedBanner; interactive?: boolean }) {
  const hasImage = Boolean(banner.image_url && isAllowedAssetUrl(banner.image_url));
  const cta = resolveBannerCta({ deepLink: banner.deep_link, ctaLabel: banner.cta_label });
  const icon = cta?.external ? <ExternalLink className="h-4 w-4" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" aria-hidden="true" />;
  return (
    <article className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-brand-navy to-blue-700 p-6 text-white shadow-sm" style={hasImage ? { backgroundImage: `linear-gradient(90deg, rgba(14,35,70,.94), rgba(29,78,216,.72)), url(${JSON.stringify(banner.image_url)})`, backgroundPosition: "center", backgroundSize: "cover" } : undefined}>
      {banner.banner_type === "action" ? <Badge className="mb-3 bg-white/15 text-white hover:bg-white/15">Next step</Badge> : null}
      <h2 className="max-w-2xl text-xl font-semibold sm:text-2xl">{banner.title}</h2>
      {banner.subtitle ? <p className="mt-2 max-w-2xl text-sm text-blue-100">{banner.subtitle}</p> : null}
      {cta ? interactive ? cta.external
        ? <a href={cta.href} target="_blank" rel="noopener noreferrer" className={DASHBOARD_CTA_CLASS}>{cta.label}{icon}<span className="sr-only"> (opens in a new tab)</span></a>
        : <Link href={cta.href} className={DASHBOARD_CTA_CLASS}>{cta.label}{icon}</Link>
        : <span className={DASHBOARD_CTA_CLASS}>{cta.label}{icon}</span> : null}
    </article>
  );
}
