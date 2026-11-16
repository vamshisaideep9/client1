import { CheckIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Public service bands share the same pale sky section surface.
// Status colors remain independent of these decorative section backgrounds.
type Line = {
  id: string;
  name: string;
  title: string;
  paragraph: string;
  benefits: string[];
  image: string;
  /** Visual balancing knob: the two illustrations share the same 500x500
   *  canvas and container, but their hand-drawn content fills different
   *  amounts of it, so one can visually read smaller. Defaults to 1. */
  imageScale?: number;
  imageSide: "left" | "right";
  ctaLabel: string;
  ctaHref: string;
};

const LINES: Line[] = [
  {
    id: "loans",
    name: "Loans",
    title: "Loans for salaried and self-employed people",
    paragraph:
      "Choose from 11 loan types, including home, personal, business, car and education loans and loan against property. You can enquire if you earn ₹15,000 a month or more. The lender decides approval, interest rate and tenure. We find the lenders that fit your profile and stay with you until the money reaches your account.",
    benefits: [
      "Banks, housing finance companies and NBFCs",
      "Loans from ₹1 lakh, free for customers",
      "Your details go to a lender only with your consent",
    ],
    image: "/illustrations/loans.svg",
    imageSide: "left",
    ctaLabel: "Compare loans",
    ctaHref: "/loans",
  },
  {
    id: "real-estate",
    name: "Real Estate",
    title: "Verified property in Hyderabad",
    paragraph:
      "Flats, villas, plots, resale homes, rentals and commercial space across the city. Before a listing goes live, we check its RERA registration and title documents, visit the site, and complete KYC on the builder or seller. You pay the seller or builder directly; no property money passes through Dhanadhara. Before you pay a token amount, we still recommend a title check by your own lawyer.",
    benefits: [
      "Flats, villas, plots, resale, rentals and commercial",
      "RERA, title documents and site checked before listing",
      "You pay the seller or builder directly",
    ],
    image: "/illustrations/real-estate.svg",
    imageScale: 1.18,
    imageSide: "right",
    ctaLabel: "Browse properties",
    ctaHref: "/real-estate",
  },
];

function Band({ line, paddingClassName }: { line: Line; paddingClassName: string }) {
  const imageOnRight = line.imageSide === "right";

  return (
    <section
      id={line.id}
      aria-labelledby={`${line.id}-heading`}
      className={cn(
        "w-full scroll-mt-[var(--site-header-h)] overflow-x-clip bg-surface-sky",
        paddingClassName
      )}
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
          {/* Illustration */}
          <div
            className={cn(
              "mx-auto hidden w-full max-w-[560px] lg:block",
              imageOnRight ? "lg:order-2" : "lg:order-1"
            )}
          >
            {/* Illustration is decorative (alt=""); the band heading carries the
                line name, so no separate DOM label here. imageScale corrects for
                the two illustrations filling their shared 500x500 canvas at
                different visual densities (see Line type comment). */}
            <Image
              src={line.image}
              alt=""
              width={500}
              height={500}
              sizes="560px"
              className="h-auto w-full"
              style={line.imageScale ? { transform: `scale(${line.imageScale})` } : undefined}
              priority={false}
            />
          </div>

          {/* Copy */}
          <div
            className={cn(
              "text-center lg:text-left",
              imageOnRight ? "lg:order-1" : "lg:order-2"
            )}
          >
            <h2
              id={`${line.id}-heading`}
              className="font-heading text-3xl font-semibold leading-tight tracking-tight text-brand-heading sm:text-4xl lg:text-5xl"
            >
              {line.title}
            </h2>
            <p className="mt-5 text-lg leading-relaxed text-text-secondary sm:text-xl">
              {line.paragraph}
            </p>
            <ul className="mt-7 space-y-4 text-left">
              {line.benefits.map((benefit) => (
                <li key={benefit} className="flex items-start gap-3">
                  <CheckIcon
                    className="mt-0.5 h-6 w-6 shrink-0 text-brand-link"
                    aria-hidden
                  />
                  <span className="text-base text-foreground sm:text-lg">
                    {benefit}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-6 flex justify-center lg:justify-start">
              <Button
                asChild
                className="w-full bg-[var(--nav-primary)] text-white hover:bg-[var(--nav-primary-hover)] focus-visible:ring-ring sm:w-auto"
              >
                <Link href={line.ctaHref}>{line.ctaLabel}</Link>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function LineSplit() {
  return (
    <>
      <Band
        line={LINES[0]}
        paddingClassName="py-16 sm:py-20 lg:py-24"
      />
      <Band line={LINES[1]} paddingClassName="py-16 sm:py-20 lg:py-24" />
    </>
  );
}
