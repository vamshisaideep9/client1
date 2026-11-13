"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { TriangleAlertIcon, X } from "lucide-react";

import { CLOSE_BUTTON_CLASS } from "@/components/ui/close-button";
import { trustLinesForPath, type TrustLine } from "@/lib/brand";
import { cn } from "@/lib/utils";

// Seconds the ticker takes per trust line, so one or two lines scroll at the
// same reading speed.
const SECONDS_PER_LINE = 22;

// The announcement copy — icon + text as one unit — rendered twice inside the
// marquee track so the loop is seamless. `inline-flex` keeps the icon vertically
// aligned with the text; `whitespace-nowrap` keeps it on one line; the trailing
// padding creates the visible gap between marquee repeats. Both copies must be
// IDENTICAL flex items (same tag + classes) so they sit on the same vertical
// baseline — otherwise the visible copy appears to drift up/down as the track
// scrolls. The duplicate carries `aria-hidden` on its own root span.
function MessageContent({ lines, ariaHidden = false }: { lines: readonly TrustLine[]; ariaHidden?: boolean }) {
  return (
    <span
      aria-hidden={ariaHidden || undefined}
      className="inline-flex items-center gap-2 whitespace-nowrap pr-12 text-xs sm:text-sm"
    >
      <TriangleAlertIcon className="h-4 w-4 shrink-0" />
      <span>
        {lines.map((line, index) => (
          <React.Fragment key={line.lead}>
            {index > 0 && <span aria-hidden="true" className="px-3 opacity-60">·</span>}
            <span className="font-medium">{line.lead}</span> <span>{line.rest}</span>
          </React.Fragment>
        ))}
      </span>
    </span>
  );
}

// Thin info bar that sits ABOVE the sticky NavBar. Financial-service pages show
// the lender line, property pages the property line, and every other page both.
// At every width the copy runs as a single-line left-to-right ticker (paused on
// hover; static and wrapped under reduced motion). The dismiss (X) stays fixed on
// the right and hides the banner for the current session (no persistence).
export function AnnouncementBanner() {
  const [dismissed, setDismissed] = React.useState(false);
  const lines = trustLinesForPath(usePathname());

  if (dismissed) return null;

  return (
    <div role="region" aria-label="Site announcement" className="bg-notice text-notice-foreground">
      <div className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2 sm:px-6 lg:px-8">
        <div className="relative min-w-0 flex-1 overflow-hidden">
          <div
            className="announcement-track flex w-max items-center whitespace-nowrap"
            style={{ "--marquee-duration": `${lines.length * SECONDS_PER_LINE}s` } as React.CSSProperties}
          >
            <MessageContent lines={lines} />
            <MessageContent lines={lines} ariaHidden />
          </div>
        </div>

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
