import Image from "next/image";
import Link from "next/link";
import React from "react";

import { PROPERTY_SUBTYPE_GROUPS, type PropertySubtypeOption } from "@/lib/property-taxonomy";
import { cn } from "@/lib/utils";

// Every property subtype on the client's Real Estate dashboard home, grouped as
// in the public Properties menu and drawn with the same per-subtype miniatures
// (public/illustrations/menu/properties). Each tile opens the signed-in Explore
// page for the subtype's category, pre-filtered to that subtype, so bookmarks,
// compare and enquiry stay in reach.

export function propertyTypeHref(item: Pick<PropertySubtypeOption, "value" | "category">): string {
  return `/dashboard/explore/${item.category}?subtypes=${item.value}`;
}

const GROUP_LABEL: Record<string, string> = { Plots: "Plots & land" };

export function PropertyTypeGrid() {
  return (
    <div className="grid gap-6 lg:grid-cols-[4fr_3fr_2fr]">
      {PROPERTY_SUBTYPE_GROUPS.map((group) => (
        <div key={group.heading} className="min-w-0">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
            {GROUP_LABEL[group.heading] ?? group.heading}
          </h3>
          <ul
            className={cn(
              "mt-3 grid grid-cols-2 gap-3",
              group.items.length === 4 && "sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4",
              group.items.length === 3 && "sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3",
              group.items.length === 2 && "sm:grid-cols-2",
            )}
          >
            {group.items.map((item) => (
              <li key={item.value} className="min-w-0">
                <Link
                  href={propertyTypeHref(item)}
                  className="group flex h-full flex-col items-center gap-2 rounded-2xl border border-border bg-card p-3 text-center transition duration-200 hover:-translate-y-0.5 hover:border-brand-cta hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0"
                >
                  <Image
                    src={`/illustrations/menu/properties/${item.value}.svg`}
                    alt=""
                    aria-hidden
                    width={96}
                    height={72}
                    unoptimized
                    className="h-[72px] w-24 transition-transform duration-200 group-hover:scale-105 motion-reduce:transition-none motion-reduce:group-hover:scale-100"
                  />
                  <span className="text-sm font-medium leading-snug text-text-primary group-hover:text-brand-link">
                    {item.label}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
