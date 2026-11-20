import * as React from "react";
import Link from "next/link";

import type { BannerCta } from "@/lib/banner-cta";

type Props = Omit<React.ComponentProps<"a">, "href" | "target" | "rel"> & {
  cta: Pick<BannerCta, "href" | "external">;
};

/**
 * The anchor behind every public banner button. Same-site paths stay on
 * next/link; external links (already validated by lib/banner-cta.ts) open in
 * a new tab without an opener or referrer, and say so to assistive tech.
 * Works as a `Button asChild` child: Slot's merged props land on the anchor.
 */
export function BannerCtaLink({ cta, children, ...props }: Props) {
  if (cta.external) {
    return (
      <a {...props} href={cta.href} target="_blank" rel="noopener noreferrer">
        {children}
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    );
  }
  return (
    <Link {...props} href={cta.href}>
      {children}
    </Link>
  );
}
