"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A lead's read-only reference (`LD-00000123`) as the API formats it. Staff
 * and Agent screens only; the public site and client screens never show it.
 */
export function LeadRefText({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  if (!value) return null;
  return (
    <span className={cn("whitespace-nowrap font-mono text-xs tabular-nums text-text-secondary", className)}>
      {value}
    </span>
  );
}

/** Several references (a grouped payout), comma separated. */
export function LeadRefList({
  values,
  className,
}: {
  values: readonly string[] | null | undefined;
  className?: string;
}) {
  if (!values?.length) return null;
  return (
    <span className={cn("font-mono text-xs tabular-nums text-text-secondary [overflow-wrap:anywhere]", className)}>
      {values.join(", ")}
    </span>
  );
}

/** The reference with a copy button, for a lead's detail header. */
export function LeadRefBadge({ value }: { value: string | null | undefined }) {
  const [copied, setCopied] = React.useState(false);
  const resetTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (resetTimer.current) clearTimeout(resetTimer.current);
    },
    [],
  );

  if (!value) return null;

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (resetTimer.current) clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      /* Clipboard unavailable: the reference stays visible and selectable. */
    }
  }

  return (
    <span className="inline-flex w-fit max-w-full items-center gap-1 self-start rounded-lg border border-border bg-card py-0.5 pl-2.5 pr-0.5">
      <span className="text-xs text-text-secondary">Lead ref</span>
      <span className="select-all font-mono text-sm font-medium tabular-nums text-text-primary">{value}</span>
      <button
        type="button"
        onClick={() => void copy(value)}
        aria-label={copied ? `Lead reference ${value} copied` : `Copy lead reference ${value}`}
        className="grid h-11 w-11 place-items-center rounded-md text-text-secondary transition-colors hover:text-brand-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {copied ? (
          <Check className="h-4 w-4 text-success" aria-hidden="true" />
        ) : (
          <Copy className="h-4 w-4" aria-hidden="true" />
        )}
      </button>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied" : ""}
      </span>
    </span>
  );
}
