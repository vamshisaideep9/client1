"use client";

// Namespace import (matching hero-carousel.tsx) so the classic JSX transform
// used by the vitest setup can render this component in tests.
import * as React from "react";
import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { HeroBanner } from "@/lib/banners";
import { cn } from "@/lib/utils";

// One sponsored card above the homepage hero, fed by the homepage_ad placement.
// Public pages and CMS previews share this static presentation. Keep the ad
// visible immediately; only the artwork failure fallback needs client state.
export function AdStrip({ banner }: { banner: HeroBanner }) {
  const [failedImage, setFailedImage] = useState<string | null>(null);

  return (
    <section
      aria-label="Sponsored"
      data-layout="ad-strip"
      data-presentation="static-sponsor-card"
      className="w-full border-y border-brand-blue/10 bg-surface-sky p-2 sm:p-3"
    >
      <div
        className={cn(
          "grid overflow-hidden rounded-xl border border-[#761f3f]/35 bg-[linear-gradient(110deg,#ffffff_35%,#fcf2f5)] shadow-[0_4px_18px_rgb(118_31_63_/_0.1)] sm:rounded-2xl",
          banner.image && "sm:grid-cols-[minmax(0,38%)_minmax(0,1fr)] lg:grid-cols-[minmax(0,32%)_minmax(0,1fr)]",
        )}
      >
        {banner.image ? (
          <div className="flex items-center justify-center bg-[#761f3f]/[0.04] p-3 sm:p-4">
            <div className="relative aspect-video w-full overflow-hidden rounded-lg">
              {failedImage !== banner.image ? (
                <Image
                  src={banner.image}
                  alt=""
                  fill
                  priority
                  sizes="(min-width: 1024px) 32vw, (min-width: 640px) 38vw, 100vw"
                  className="object-contain"
                  onError={() => setFailedImage(banner.image!)}
                  // Same as the hero: uploaded artwork can use an asset host
                  // reachable only by the browser, not Next's image server.
                  unoptimized
                />
              ) : null}
            </div>
          </div>
        ) : null}
        <div className="flex min-w-0 flex-col items-start justify-center px-5 py-5 sm:px-6 sm:py-6 lg:px-9">
          <span className="mb-3 rounded-full bg-[#761f3f] px-3 py-1 font-geist text-[10px] font-semibold uppercase tracking-[0.16em] text-white">
            Sponsored
          </span>
          <div className="min-w-0 max-w-2xl [overflow-wrap:anywhere]">
            {/* Keep paid copy out of the homepage's heading outline. */}
            <p className="text-balance font-heading text-xl font-semibold leading-tight tracking-tight text-[#53182e] sm:text-2xl lg:text-3xl">
              {banner.title}
            </p>
            {banner.subtitle ? (
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-text-secondary lg:text-base">
                {banner.subtitle}
              </p>
            ) : null}
          </div>
          {banner.cta ? (
            <Button
              asChild
              size="sm"
              className="mt-4 h-auto min-h-11 max-w-full whitespace-normal bg-[#761f3f] px-5 py-2.5 text-sm text-white hover:bg-[#5c1831] focus-visible:ring-[#761f3f]"
            >
              <Link href={banner.cta.href}>
                <span className="min-w-0 [overflow-wrap:anywhere]">{banner.cta.label}</span>
                <ArrowUpRight className="size-4 shrink-0" aria-hidden />
              </Link>
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
