"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Building2, Landmark, X, type LucideIcon } from "lucide-react";

import { CLOSE_BUTTON_CLASS } from "@/components/ui/close-button";
import { trustLinesForPath, type TrustLine, type TrustLineKind } from "@/lib/brand";
import { cn } from "@/lib/utils";

// Seconds the ticker takes per trust line, so the scroll keeps one reading speed.
const SECONDS_PER_LINE = 22;

// Each business line is told apart by its own icon, chip label and chip fill,
// so the difference never rests on colour alone.
const LINE_STYLE: Record<TrustLineKind, { Icon: LucideIcon; chip: string }> = {
  finance: { Icon: Landmark, chip: "bg-notice-foreground text-notice" },
  property: {
    Icon: Building2,
    chip: "bg-white text-notice-foreground ring-1 ring-inset ring-notice-foreground/50",
  },
};

function TrustSegment({ line }: { line: TrustLine }) {
  const { Icon, chip } = LINE_STYLE[line.kind];
  return (
    <span data-trust-line={line.kind} className="inline-flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold uppercase leading-4 tracking-wide",
          chip,
        )}
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        {line.label}
        <span className="sr-only">:</span>
      </span>
      <span>
        <span className="font-medium">{line.lead}</span> <span>{line.rest}</span>
      </span>
    </span>
  );
}

// One copy of the scrolling message. A divider follows every segment, including
// the last, so the seam between the two loop copies looks like any other gap.
// Both copies must be IDENTICAL flex items so they share a baseline; the
// duplicate carries `aria-hidden` on its own root span.
function TickerCopy({ lines, ariaHidden = false }: { lines: readonly TrustLine[]; ariaHidden?: boolean }) {
  return (
    <span aria-hidden={ariaHidden || undefined} className="inline-flex items-center whitespace-nowrap text-xs sm:text-sm">
      {lines.map((line) => (
        <React.Fragment key={line.kind}>
          <TrustSegment line={line} />
          <span aria-hidden="true" className="mx-6 h-4 w-px shrink-0 bg-notice-foreground/40" />
        </React.Fragment>
      ))}
    </span>
  );
}

// Thin info bar that sits ABOVE the sticky NavBar. Financial-service pages show
// the lender line and property pages the property line, each as a static
// message. Every other page shows both lines as a right-to-left ticker (paused
// on hover; static and wrapped under reduced motion). The dismiss (X) stays
// fixed on the right and hides the banner for the current session only.
export function AnnouncementBanner() {
  const [dismissed, setDismissed] = React.useState(false);
  const lines = trustLinesForPath(usePathname());

  if (dismissed) return null;

  return (
    <div role="region" aria-label="Site announcement" className="bg-notice text-notice-foreground">
      <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2 sm:px-6 lg:px-8">
        {lines.length === 1 ? (
          <p className="min-w-0 flex-1 text-center text-xs sm:text-sm">
            <TrustSegment line={lines[0]} />
          </p>
        ) : (
          <div className="relative min-w-0 flex-1 overflow-hidden">
            <div
              className="announcement-track flex w-max items-center whitespace-nowrap"
              style={{ "--marquee-duration": `${lines.length * SECONDS_PER_LINE}s` } as React.CSSProperties}
            >
              <TickerCopy lines={lines} />
              <TickerCopy lines={lines} ariaHidden />
            </div>
          </div>
        )}

        {/* Dismiss — fixed on the right, does not scroll with the marquee */}
        <button
          type="button"
          aria-label="Dismiss announcement"
          onClick={() => setDismissed(true)}
          className={cn(CLOSE_BUTTON_CLASS, "shrink-0 text-notice-foreground hover:text-notice-foreground focus-visible:ring-notice-foreground focus-visible:ring-offset-notice")}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
