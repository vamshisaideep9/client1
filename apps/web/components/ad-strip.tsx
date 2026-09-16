"use client";

// Namespace import (matching hero-carousel.tsx) so the classic JSX transform
// used by the vitest setup can render this component in tests.
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { HeroBanner } from "@/lib/banners";
import { cn } from "@/lib/utils";

// Sponsored ad band between the sticky header and the full-screen homepage
// hero, fed by the `homepage_ad` banner placement.
//
// One brief CSS curtain reveal is confined to the ad's interior. Its disclosure
// stays outside the animation, and its layout never moves.
//
// Exactly one sponsor shows at a time, so this is NOT a carousel: no Embla, no
// autoplay or navigation arrows. Reduced motion skips the reveal. The "one at a time"
// rule is enforced upstream by the database --
// uq_banners_live_placement_category permits a single LIVE banner per
// placement, regardless of its selected category/theme.
//
// The next sponsor is queued rather than rotated: a Sub Admin authors a
// replacement naming the incumbent, Admin approves it, and the cms_activation
// job archives the incumbent and promotes the successor at its starts_at.

// Document-lifetime memory only: client navigation must not replay a campaign.
// A reload creates a fresh module. No cookies, storage or server-side writes.
const revealedCampaigns = new Set<string>();

export function AdStrip({
  banner,
  animate = true,
}: {
  banner: HeroBanner;
  /** CMS previews show the final composition immediately. */
  animate?: boolean;
}) {
  const [revealSkipped, setRevealSkipped] = useState(() => revealedCampaigns.has(banner.id));
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!animate) return;
    revealedCampaigns.add(banner.id);
    let active = true;
    // CSS starts before hydration. Observe its existing timeline, including
    // an already-completed or reduced-motion entrance; never restart it.
    const animations = stageRef.current?.getAnimations({ subtree: true }) ?? [];
    void Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
      if (active) setRevealSkipped(true);
    });
    return () => { active = false; };
  }, [animate, banner.id]);

  return (
    <section
      aria-label="Sponsored"
      data-layout="ad-strip"
      data-presentation="curtain-sponsor-card"
      onFocusCapture={() => setRevealSkipped(true)}
      className="relative isolate w-full border-y border-brand-blue/10 bg-surface-sky p-2 sm:p-3"
    >
      <div className="overflow-hidden rounded-xl border border-brand-blue/15 bg-surface sm:rounded-2xl">
        <div className="flex min-h-9 items-center border-b border-brand-blue/10 px-3 sm:px-5">
          <span className="font-geist text-[10px] font-semibold uppercase tracking-[0.18em] text-brand-blue">
            Sponsored
          </span>
        </div>
        <div
          ref={stageRef}
          className={cn(
            "sponsor-stage relative grid min-h-40 overflow-hidden",
            banner.image && "grid-cols-[80px_minmax(0,1fr)] sm:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[minmax(240px,26%)_minmax(0,1fr)]",
          )}
          data-reveal={animate && !revealSkipped ? "curtain" : "none"}
        >
          {banner.image ? (
            <div className="relative flex items-center border-r border-brand-blue/10 bg-surface-sky p-2 sm:p-0">
              <div className="relative aspect-square w-full overflow-hidden rounded-md sm:absolute sm:inset-0 sm:aspect-auto sm:rounded-none">
                {failedImage !== banner.image ? (
                  <Image
                    src={banner.image}
                    alt=""
                    fill
                    priority
                    sizes="(min-width: 1024px) 26vw, (min-width: 640px) 240px, 64px"
                    className="object-cover"
                    onError={() => setFailedImage(banner.image!)}
                    // Same as the hero: uploaded artwork can use an asset host
                    // reachable only by the browser, not Next's image server.
                    unoptimized
                  />
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="flex min-w-0 flex-col justify-center gap-3 px-4 py-4 sm:gap-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:gap-8 lg:px-8 lg:py-6">
            <div className="min-w-0 max-w-2xl [overflow-wrap:anywhere]">
              {/* Keep paid copy out of the homepage's heading outline. */}
              <p className="font-heading text-base font-semibold leading-snug tracking-tight text-[var(--nav-text)] sm:text-xl lg:text-2xl">
                {banner.title}
              </p>
              {banner.subtitle ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-secondary sm:text-sm">
                  {banner.subtitle}
                </p>
              ) : null}
            </div>
            {banner.cta ? (
              <Button
                asChild
                size="sm"
                className="h-auto min-h-11 max-w-full shrink-0 self-start whitespace-normal bg-[var(--nav-primary)] px-4 py-2.5 text-xs text-white hover:bg-[var(--nav-primary-hover)] focus-visible:ring-ring sm:text-sm lg:max-w-52 lg:self-center"
              >
                <Link href={banner.cta.href}>
                  <span className="min-w-0 [overflow-wrap:anywhere]">{banner.cta.label}</span>
                  <ArrowUpRight className="size-4 shrink-0" aria-hidden />
                </Link>
              </Button>
            ) : null}
          </div>
          <div aria-hidden="true" className="sponsor-curtain sponsor-curtain-left" />
          <div aria-hidden="true" className="sponsor-curtain sponsor-curtain-right" />
        </div>
      </div>
    </section>
  );
}
