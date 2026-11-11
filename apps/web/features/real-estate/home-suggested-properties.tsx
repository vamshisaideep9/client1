"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";

import { PropertyCard } from "@/components/property-card";
import { readBookmarkedIds } from "@/lib/bookmark-cache";
import type { PropertyListing } from "@/lib/properties";
import { rankSimilarProperties } from "@/lib/similar-properties";

const SUGGESTION_LIMIT = 6;

/**
 * Rank the public catalog against every bookmarked listing and keep each
 * candidate's best score. Bookmarked listings themselves are never suggested.
 * Pure so it can be unit tested without a browser.
 */
export function suggestFromBookmarks(
  listings: readonly PropertyListing[],
  bookmarkedIds: readonly string[],
  limit = SUGGESTION_LIMIT,
): PropertyListing[] {
  const bookmarked = new Set(bookmarkedIds);
  const subjects = listings.filter((listing) => bookmarked.has(listing.id));
  if (subjects.length === 0) return [];
  const candidates = listings.filter((listing) => !bookmarked.has(listing.id));

  const best = new Map<string, { listing: PropertyListing; score: number; order: number }>();
  subjects.forEach((subject, subjectIndex) => {
    for (const match of rankSimilarProperties(subject, candidates, { limit: candidates.length })) {
      const current = best.get(match.listing.id);
      if (!current || match.score > current.score) {
        best.set(match.listing.id, { listing: match.listing, score: match.score, order: subjectIndex });
      }
    }
  });

  return Array.from(best.values())
    .sort((a, b) => b.score - a.score || a.order - b.order)
    .slice(0, limit)
    .map((entry) => entry.listing);
}

// Home "Suggested for you": shown only to a signed-in visitor who has bookmarked
// at least one property that is still published. Everything is computed in the
// browser from the public catalog and the locally cached bookmark ids, so the
// ISR Home page stays identical (and cacheable) for every visitor and no
// personal data is rendered on the server.
export function HomeSuggestedProperties({ listings }: { listings: PropertyListing[] }) {
  const [suggestions, setSuggestions] = React.useState<PropertyListing[]>([]);

  React.useEffect(() => {
    setSuggestions(suggestFromBookmarks(listings, readBookmarkedIds()));
  }, [listings]);

  if (suggestions.length === 0) return null;

  return (
    <section
      aria-labelledby="home-suggested-heading"
      className="glass-backdrop border-b border-[var(--nav-border)] px-4 py-12 sm:px-6 sm:py-14 lg:px-8"
    >
      <div className="mx-auto max-w-7xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="flex items-center gap-1.5 text-sm font-semibold text-brand-link">
              <Sparkles className="h-4 w-4" aria-hidden />
              Based on your bookmarks
            </p>
            <h2
              id="home-suggested-heading"
              className="mt-1 font-heading text-2xl font-semibold text-foreground sm:text-3xl"
            >
              Suggested for you
            </h2>
          </div>
          <Link
            href="/real-estate"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm font-semibold text-brand-link hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            See all properties
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
        <ul className="mt-6 flex gap-5 overflow-x-auto pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label="Suggested properties">
          {suggestions.map((listing) => (
            <li key={listing.id} className="shrink-0">
              <PropertyCard listing={listing} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
