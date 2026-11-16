import React from "react";

import { AdStrip } from "@/components/ad-strip";
import { HeroCarousel } from "@/components/hero-carousel";
import {
  DashboardBannerCard,
  DashboardOfferCard,
  OFFER_LIST_CLASS,
} from "@/features/dashboard/personalized-placements";
import { resolveBannerCta } from "@/lib/banner-cta";
import type { HeroBanner } from "@/lib/banners";
import type { Banner } from "@/lib/banners-api";
import type { Offer } from "@/lib/offers-api";
import type { AuthenticatedBanner, AuthenticatedOffer } from "@/lib/personalization-api";

import { DashboardPreviewChrome, PublicPreviewChrome } from "./preview-chrome";

/**
 * Campaign previews render the production components themselves -- the same
 * `HeroCarousel`, `AdStrip` and dashboard placement cards a visitor gets --
 * with interaction disabled. A second, approximate implementation was
 * explicitly rejected (DECISIONS.md DEC-20260828-04): it would drift, and a
 * preview that drifts is worse than none.
 *
 * The surrounding page furniture comes from `preview-chrome`, and the caller
 * wraps the whole thing in `ViewportFrame` so it lays out at a real device
 * width.
 */

export type BannerPreviewValue = Pick<
  Banner,
  "banner_type" | "title" | "subtitle" | "cta_label" | "deep_link"
> & {
  image_url?: string | null;
  rera_verified?: boolean;
  /** Attached YouTube video; with no destination it becomes the CTA. */
  youtube_video_id?: string | null;
};
export type OfferPreviewValue = Pick<
  Offer,
  "title" | "description" | "discount_type" | "discount_value" | "code"
> &
  Partial<Pick<Offer, "partner_name" | "image_url" | "redemption_url" | "terms_summary">>;

export function BannerPreview({
  banner,
  context,
  placement,
}: {
  banner: BannerPreviewValue;
  context: "public" | "dashboard";
  placement?: Banner["placement"];
}) {
  // The same resolution visitors get (lib/banner-cta.ts), so the preview shows
  // exactly the button -- or no button -- the published banner will have.
  const cta = resolveBannerCta({
    deepLink: banner.deep_link,
    ctaLabel: banner.cta_label,
    youtubeVideoId: context === "public" ? banner.youtube_video_id : null,
  });
  if (context === "dashboard") {
    const value: AuthenticatedBanner = {
      id: "campaign-preview",
      banner_type: banner.banner_type,
      title: banner.title || "Banner title",
      subtitle: banner.subtitle ?? null,
      cta_label: cta?.label ?? null,
      deep_link: cta?.href ?? null,
      image_url: banner.image_url ?? null,
    };
    return (
      <DashboardPreviewChrome>
        <DashboardBannerCard banner={value} interactive={false} />
      </DashboardPreviewChrome>
    );
  }

  const value: HeroBanner = {
    id: "campaign-preview",
    title: banner.title || "Banner title",
    subtitle: banner.subtitle || undefined,
    image: banner.image_url || undefined,
    reraVerified: banner.rera_verified,
    cta: cta ?? undefined,
  };
  if (placement === "homepage_ad") {
    return (
      <PublicPreviewChrome>
        <AdStrip banner={value} dismissible={false} />
      </PublicPreviewChrome>
    );
  }
  return (
    <PublicPreviewChrome>
      <HeroCarousel
        banners={[value]}
        variant={placement === "homepage" || placement === undefined ? "hero" : "section"}
        label="Campaign preview"
        interactive={false}
      />
    </PublicPreviewChrome>
  );
}

export function OfferPreview({ offer }: { offer: OfferPreviewValue }) {
  const value: AuthenticatedOffer = {
    id: "offer-preview",
    title: offer.title || "Offer title",
    description: offer.description ?? null,
    discount_type: offer.discount_type,
    discount_value: offer.discount_value,
    code: offer.code ?? "OFFER",
    partner_name: offer.partner_name ?? "Partner",
    image_url: offer.image_url ?? "",
    redemption_url: offer.redemption_url ?? "https://partner.example",
    terms_summary: offer.terms_summary ?? "Offer terms appear here before a customer proceeds.",
    terms_url: null,
  };
  return (
    <DashboardPreviewChrome>
      {/* The real dashboard stacks offers in this single-column list
          (personalized-placements.tsx), each a horizontal banner from md up. */}
      <ul className={OFFER_LIST_CLASS} aria-label="Offers for you">
        <li>
          <DashboardOfferCard offer={value} interactive={false} />
        </li>
      </ul>
    </DashboardPreviewChrome>
  );
}

export function placementLabel(placement?: Banner["placement"]): string {
  if (placement === "financial_services") return "Financial Services page";
  if (placement === "properties") return "Properties page";
  if (placement === "homepage_ad") return "Homepage sponsor strip";
  if (placement === "dashboard") return "Authenticated dashboard";
  return "Homepage hero";
}
