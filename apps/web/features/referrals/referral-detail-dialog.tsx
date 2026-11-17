"use client";

import Link from "next/link";
import { Building2, Check, Circle, Landmark } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { formatPaise } from "@/lib/format";
import type { Referral } from "@/lib/referrals-api";
import { cn } from "@/lib/utils";

const STEP_ORDER = ["pending", "converted", "accrued", "paid"] as const;

function stepReached(status: string, step: (typeof STEP_ORDER)[number]): boolean {
  const current = STEP_ORDER.indexOf(status as (typeof STEP_ORDER)[number]);
  return current >= 0 && current >= STEP_ORDER.indexOf(step);
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// Per-referral activity detail for the referrer: what converted (the property
// listing or loan product, catalogue facts only), where the referral is in its
// one-time lifecycle, and the referrer's own bonus. The referred person's deal
// value, loan amount and personal details are never shown (API contract:
// ReferralConvertedItem).
export function ReferralDetailDialog({ referral }: { referral: Referral }) {
  const item = referral.converted_item ?? null;
  const isVoid = referral.conversion_status === "void";
  const steps = [
    { key: "pending" as const, label: "Signed up with your code", date: formatDate(referral.created_at) },
    {
      key: "converted" as const,
      label: item?.kind === "loan" ? "Loan disbursed" : item?.kind === "property" ? "Property deal closed" : "First transaction completed",
      date: formatDate(referral.converted_at),
    },
    { key: "accrued" as const, label: "Referral bonus earned, referral closed", date: null },
    { key: "paid" as const, label: "Bonus paid to you", date: null },
  ];

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="min-h-9">
          Details
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Referral {referral.referred_mobile_masked}</DialogTitle>
          <DialogDescription>
            A referral earns a bonus once, on the referred person&apos;s first completed loan or
            property deal. After that the referral is closed.
          </DialogDescription>
        </DialogHeader>

        {item ? (
          <div className="flex gap-3 rounded-xl border border-border bg-surface p-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-cta-tint text-brand-link">
              {item.kind === "property" ? (
                <Building2 className="h-5 w-5" aria-hidden />
              ) : (
                <Landmark className="h-5 w-5" aria-hidden />
              )}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-text-secondary">
                {item.kind === "property" ? "Property" : "Loan product"}
              </p>
              <p className="font-semibold text-text-primary [overflow-wrap:anywhere]">{item.title}</p>
              {item.location ? (
                <p className="text-sm text-text-secondary">{item.location}</p>
              ) : null}
              {item.property_type ? (
                <p className="text-xs text-text-secondary">{item.property_type}</p>
              ) : null}
              {item.property_id ? (
                <Link
                  href={`/real-estate/properties/${item.property_id}`}
                  className="mt-1 inline-block text-sm font-medium text-brand-link hover:underline"
                >
                  View listing
                </Link>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-border p-4 text-sm text-text-secondary">
            {isVoid
              ? "This referral is not eligible for a bonus."
              : "Nothing has converted yet. You will see the property or loan here once their first transaction completes."}
          </p>
        )}

        {isVoid ? null : (
          <ol className="grid gap-3" aria-label="Referral progress">
            {steps.map((step) => {
              const done = stepReached(referral.conversion_status, step.key);
              return (
                <li key={step.key} className="flex items-start gap-3">
                  <span
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                      done ? "bg-success text-white" : "border border-border text-text-secondary",
                    )}
                  >
                    {done ? <Check className="h-3 w-3" aria-hidden /> : <Circle className="h-2 w-2" aria-hidden />}
                  </span>
                  <div className="text-sm">
                    <p className={cn(done ? "font-medium text-text-primary" : "text-text-secondary")}>
                      {step.label}
                      <span className="sr-only">{done ? " (done)" : " (not yet)"}</span>
                    </p>
                    {done && step.date ? <p className="text-xs text-text-secondary">{step.date}</p> : null}
                  </div>
                </li>
              );
            })}
          </ol>
        )}

        <div className="flex items-center justify-between rounded-xl bg-surface px-4 py-3 text-sm">
          <span className="text-text-secondary">Your referral bonus</span>
          <span className="font-semibold text-text-primary">
            {referral.bonus_amount_paise != null ? formatPaise(referral.bonus_amount_paise) : "Not earned yet"}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
