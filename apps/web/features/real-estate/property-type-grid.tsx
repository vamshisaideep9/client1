import React from "react";

import { ExploreArtCard } from "@/features/dashboard/explore-cards";
import { PROPERTY_SUBTYPE_ARTWORK } from "@/lib/property-artwork";
import { PROPERTY_SUBTYPE_GROUPS, type PropertySubtypeOption } from "@/lib/property-taxonomy";
import { getRECategory } from "@/lib/real-estate";

// Every property subtype on the client's Real Estate dashboard home, grouped
// as in the public Properties menu. Each card keeps the illustrated
// ExploreArtCard treatment the category cards used (4:3 artwork from
// PROPERTY_SUBTYPE_ARTWORK, title, one-line description, Explore footer) and
// opens the signed-in Explore page for the subtype's category, pre-filtered to
// that subtype, so bookmarks, compare and enquiry stay in reach.

export function propertyTypeHref(item: Pick<PropertySubtypeOption, "value" | "category">): string {
  return `/dashboard/explore/${item.category}?subtypes=${item.value}`;
}

const GROUP_LABEL: Record<string, string> = { Plots: "Plots & land" };

const SUBTYPE_BLURB: Record<PropertySubtypeOption["value"], string> = {
  individual_house: "Independent homes on their own plot.",
  standalone_apartment: "Flats in a single building.",
  gated_community_apartment: "Flats with shared amenities and security.",
  villa: "Spacious homes in villa communities.",
  plot: "Open plots ready to build on.",
  farmland: "Farmland for cultivation or a weekend home.",
  agriland: "Agricultural land for long-term holding.",
  locked_space: "Lockable shops and offices.",
  unlocked_space: "Open-plan commercial floor space.",
};

export function PropertyTypeGrid() {
  return (
    <div className="space-y-6">
      {PROPERTY_SUBTYPE_GROUPS.map((group) => (
        <section key={group.heading} aria-label={GROUP_LABEL[group.heading] ?? group.heading}>
          <h3 className="text-sm font-semibold text-text-secondary">
            {GROUP_LABEL[group.heading] ?? group.heading}
          </h3>
          {/* One column template for every group, so cards line up in size
              across Residential (4), Plots & land (3) and Commercial (2). */}
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {group.items.map((item) => (
              <ExploreArtCard
                key={item.value}
                href={propertyTypeHref(item)}
                title={item.label}
                blurb={SUBTYPE_BLURB[item.value]}
                illustration={PROPERTY_SUBTYPE_ARTWORK[item.value]}
                fallbackIcon={getRECategory(item.category)!.icon}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
