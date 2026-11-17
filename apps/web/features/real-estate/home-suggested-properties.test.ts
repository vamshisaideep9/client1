import { describe, expect, it } from "vitest";

import { suggestFromBookmarks } from "@/features/real-estate/home-suggested-properties";
import type { PropertyListing } from "@/lib/properties";

function listing(id: string, overrides: Partial<PropertyListing> = {}): PropertyListing {
  return {
    id,
    title: `Listing ${id}`,
    location: "Gachibowli, Hyderabad",
    price: "₹90 L",
    listingIntent: "sale",
    type: "Apartment",
    category: "apartments",
    propertySubtype: "standalone_apartment",
    ...overrides,
  };
}

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

describe("suggestFromBookmarks", () => {
  it("returns nothing without a published bookmarked listing", () => {
    expect(suggestFromBookmarks([listing(ID(1)), listing(ID(2))], [])).toEqual([]);
    expect(suggestFromBookmarks([listing(ID(1))], [ID(9)])).toEqual([]);
  });

  it("never suggests a property the user already bookmarked", () => {
    const listings = [listing(ID(1)), listing(ID(2)), listing(ID(3))];
    const ids = suggestFromBookmarks(listings, [ID(1), ID(2)]).map((item) => item.id);
    expect(ids).not.toContain(ID(1));
    expect(ids).not.toContain(ID(2));
    expect(ids).toContain(ID(3));
  });

  it("ranks a same-subtype, same-area listing above an unrelated one", () => {
    const bookmarked = listing(ID(1));
    const close = listing(ID(2));
    const unrelated = listing(ID(3), {
      category: "commercial",
      propertySubtype: undefined,
      location: "Whitefield, Bengaluru",
      price: "₹9 Cr",
    });
    const result = suggestFromBookmarks([bookmarked, unrelated, close], [ID(1)]);
    expect(result[0]?.id).toBe(ID(2));
  });

  it("respects the limit", () => {
    const listings = Array.from({ length: 10 }, (_, i) => listing(ID(i + 1)));
    expect(suggestFromBookmarks(listings, [ID(1)], 3)).toHaveLength(3);
  });
});
