"use client";

import type { ReactNode } from "react";

/**
 * A same-page `#id` link that also moves keyboard focus to its target.
 *
 * Browsers scroll to a fragment but leave focus on the link, so a keyboard or
 * screen-reader user would still be at the top of the page. The target needs
 * `tabIndex={-1}` to accept focus; the browser's own fragment navigation
 * handles the scroll and the URL.
 */
export function InPageAnchor({
  href,
  className,
  children,
}: {
  href: `#${string}`;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      className={className}
      onClick={() => {
        document.getElementById(href.slice(1))?.focus({ preventScroll: true });
      }}
    >
      {children}
    </a>
  );
}
