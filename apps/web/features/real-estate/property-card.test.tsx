import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PropertyCard, propertyCardFacts } from "@/features/real-estate/property-card";
import { RealEstateProvider } from "@/features/real-estate/store";
import type { REListing } from "@/lib/real-estate";

const LISTING: REListing = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Baner Heights",
  location: "Baner, Pune",
  locality: "Baner",
  city: "Pune",
  pincode: "411045",
  listingIntent: "sale",
  category: "apartments",
  propertySubtype: "standalone_apartment",
  type: "Apartment",
  price: "₹75 L",
  priceLakhs: 75,
  areaSqft: 1100,
  bhk: 2,
  ageYears: 2,
  amenities: ["parking"],
  furnishing: "semi",
  status: "ready",
  constructionStatus: "ready",
  meta: "2 bed · 1,100 sqft",
  reraNumber: "P52100000001",
  reraVerificationStatus: "verified",
  media: [],
};

function renderCard(listing: REListing = LISTING) {
  return renderToStaticMarkup(
    <RealEstateProvider>
      <PropertyCard listing={listing} />
    </RealEstateProvider>,
  );
}

describe("dashboard PropertyCard", () => {
  it("labels resale homes and rentals, and keeps overlay layers inside the card", () => {
    const resale = renderCard({
      ...LISTING,
      structuredDetails: { sale_type: "resale" },
    } as unknown as REListing);
    expect(resale).toMatch(/>Resale</);
    // isolate contains the z-indexed Bookmark/Compare overlay (scroll overlap fix).
    expect(resale).toMatch(/class="relative isolate aspect-video/);

    const fresh = renderCard({
      ...LISTING,
      structuredDetails: { sale_type: "new_sale" },
    } as unknown as REListing);
    expect(fresh).not.toMatch(/>Resale</);

    const rental = renderCard({ ...LISTING, listingIntent: "rent" });
    expect(rental).toContain("For rent / lease");
    expect(rental).not.toMatch(/>Resale</);
  });

  it("keeps a compact summary, a preview action, and full-page links", () => {
    const markup = renderCard();

    expect(markup).toContain("Baner Heights");
    expect(markup).toContain("2 BHK");
    expect(markup).toContain("1,100 sq ft");
    expect(markup).toContain("Ready");
    expect(markup).toContain("View details");
    expect(markup).toContain('aria-haspopup="dialog"');
    expect(markup).toContain('/dashboard/properties/11111111-1111-4111-8111-111111111111');
    expect(markup).not.toContain("Property preview");
    expect(markup).not.toContain("Enquire");
    expect(markup).not.toContain("Book a site visit");
    expect(markup).not.toContain("P52100000001");
  });

  it("shows the RERA treatment only for verified listings", () => {
    expect(renderCard()).toContain("RERA verified");
    expect(
      renderCard({ ...LISTING, reraVerificationStatus: "not_reviewed" }),
    ).not.toContain("RERA verified");
  });

  it("omits unavailable highlights instead of reserving empty rows", () => {
    expect(
      propertyCardFacts({
        ...LISTING,
        bhk: 0,
        areaSqft: 0,
        status: null,
        constructionStatus: null,
      }),
    ).toEqual([]);
  });
});
