"use client";

import * as React from "react";
import Link from "next/link";
import { Copy, Gift, Mail, MessageCircle, Share2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  authHref,
  buildReferMessage,
  buildReferUrl,
  readOwnReferralCode,
  referReturnToFor,
} from "@/lib/referral-share";
import { cn } from "@/lib/utils";

type Variant = "share" | "refer";

function absoluteUrl(path: string): string {
  return new URL(path, window.location.origin).toString();
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// The share sheet behind both buttons. The native sheet is used when the
// browser has one (mobile); otherwise a small menu offers WhatsApp, copy and
// email.
//
// Share sends the plain public page, nothing else. Refer sends the client's
// own code to Register (with a Log in link for existing users) and then on to
// the referred page inside the dashboard.
function ShareMenuButton({
  variant,
  path,
  title,
  referReturnTo,
  className,
}: {
  variant: Variant;
  path: string;
  title: string;
  referReturnTo: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [payload, setPayload] = React.useState<{ url: string; text: string } | null>(null);

  function buildPayload() {
    const code = variant === "refer" ? readOwnReferralCode() : null;
    if (code) {
      const url = buildReferUrl(window.location.origin, code, referReturnTo);
      return { url, text: buildReferMessage(title, url, code) };
    }
    const url = absoluteUrl(path);
    return { url, text: `${title} on Dhanadhara: ${url}` };
  }

  async function onClick(event: React.MouseEvent) {
    const next = buildPayload();
    setPayload(next);
    if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
      event.preventDefault();
      try {
        await navigator.share({ title, text: next.text, url: next.url });
      } catch {
        // User cancelled the native sheet, or it failed: nothing to report.
      }
    }
  }

  const Icon = variant === "refer" ? Gift : Share2;
  const label = variant === "refer" ? "Refer" : "Share";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={(event) => void onClick(event)}
          aria-label={`${label} ${title}`}
          className={cn("min-h-10 flex-1", className)}
        >
          <Icon className="h-4 w-4" aria-hidden />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-60 p-1.5">
        {payload ? (
          <div className="grid gap-0.5" role="menu" aria-label={`${label} options`}>
            <a
              role="menuitem"
              href={`https://wa.me/?text=${encodeURIComponent(payload.text)}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              className="flex min-h-10 items-center gap-2 rounded-md px-3 text-sm hover:bg-[var(--nav-tint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <MessageCircle className="h-4 w-4 text-brand-link" aria-hidden />
              WhatsApp
            </a>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                void copyText(variant === "refer" ? payload.text : payload.url).then((ok) => {
                  if (ok) toast.success(variant === "refer" ? "Referral message copied" : "Link copied");
                  else toast.error("Couldn't copy. Please copy the link from the address bar.");
                });
                setOpen(false);
              }}
              className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-[var(--nav-tint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Copy className="h-4 w-4 text-brand-link" aria-hidden />
              {variant === "refer" ? "Copy referral message" : "Copy link"}
            </button>
            <a
              role="menuitem"
              href={`mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(payload.text)}`}
              onClick={() => setOpen(false)}
              className="flex min-h-10 items-center gap-2 rounded-md px-3 text-sm hover:bg-[var(--nav-tint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Mail className="h-4 w-4 text-brand-link" aria-hidden />
              Email
            </a>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

// Share + Refer pair for a loan or property. Refer needs the viewer's own
// referral code; a visitor without one is sent to sign up first.
export function ShareActions({
  path,
  title,
  referReturnTo,
  className,
}: {
  /** Site-relative path of the loan or property page, e.g. /loans/home-loan. */
  path: string;
  /** Human title used in the share text, e.g. "Sunny Homes, Gachibowli". */
  title: string;
  /** Dashboard page a referred visitor opens after signing up; derived from `path` when omitted. */
  referReturnTo?: string;
  className?: string;
}) {
  const [hasCode, setHasCode] = React.useState(false);
  const returnTo = referReturnTo ?? referReturnToFor(path);

  React.useEffect(() => {
    setHasCode(readOwnReferralCode() !== null);
  }, []);

  return (
    <div className={cn("flex w-full gap-2", className)} data-share-actions="">
      <ShareMenuButton variant="share" path={path} title={title} referReturnTo={returnTo} />
      {hasCode ? (
        <ShareMenuButton variant="refer" path={path} title={title} referReturnTo={returnTo} />
      ) : (
        <Button asChild variant="outline" size="sm" className="min-h-10 flex-1">
          <Link href={authHref("/register", { returnTo })} aria-label={`Sign up to refer ${title}`}>
            <Gift className="h-4 w-4" aria-hidden />
            Refer
          </Link>
        </Button>
      )}
    </div>
  );
}
