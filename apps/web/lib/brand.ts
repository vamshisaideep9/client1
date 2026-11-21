export const SITE_NAME = "Dhanadhara";

export const BRAND_ASSETS = {
  horizontal: { src: "/brand/logo-horizontal.png", width: 960, height: 232 },
  stacked: { src: "/brand/logo-stacked.png", width: 960, height: 930 },
  symbol: { src: "/brand/symbol.png", width: 783, height: 538 },
} as const;

export function brandedFilename(filename: string): string {
  return filename.startsWith("dhanadhara-") ? filename : `dhanadhara-${filename}`;
}

export type TrustLineKind = "finance" | "property";

export type TrustLine = {
  readonly kind: TrustLineKind;
  /** Short business-line name shown as the line's chip in the announcement bar. */
  readonly label: string;
  readonly lead: string;
  readonly rest: string;
};

// Single-sourced trust sentences, one per business line. The announcement bar
// shows the line(s) that match the current page, and the footer repeats both
// permanently (the banner is dismissible, so the footer keeps the message on
// the page even after a visitor dismisses the banner).
export const TRUST_LINES = {
  finance: {
    kind: "finance",
    label: "Loans",
    lead: "We connect you with the right banks.",
    rest: "We're the bridge between customers and lenders, not a bank ourselves.",
  },
  property: {
    kind: "property",
    label: "Real estate",
    lead: "We connect you with verified sellers and builders.",
    rest: "We're the bridge between buyers and sellers, not the seller ourselves.",
  },
} as const satisfies Record<string, TrustLine>;

function underPath(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

/** Financial-service pages show the lender line, property pages the property
 * line, and every other page (home included) shows both. */
export function trustLinesForPath(pathname: string | null | undefined): readonly TrustLine[] {
  const path = pathname ?? "/";
  if (underPath(path, "/loans")) return [TRUST_LINES.finance];
  if (underPath(path, "/real-estate")) return [TRUST_LINES.property];
  return [TRUST_LINES.finance, TRUST_LINES.property];
}
