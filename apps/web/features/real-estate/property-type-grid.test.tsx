import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PropertyTypeGrid, propertyTypeHref } from "@/features/real-estate/property-type-grid";
import { PROPERTY_SUBTYPE_OPTIONS } from "@/lib/property-taxonomy";

describe("PropertyTypeGrid", () => {
  it("links all nine subtypes into signed-in Explore for their category", () => {
    const markup = renderToStaticMarkup(<PropertyTypeGrid />);
    expect(PROPERTY_SUBTYPE_OPTIONS).toHaveLength(9);
    for (const option of PROPERTY_SUBTYPE_OPTIONS) {
      expect(markup).toContain(
        `href="/dashboard/explore/${option.category}?subtypes=${option.value}"`,
      );
      expect(markup).toContain(option.label);
    }
    expect(markup).toContain("Residential");
    expect(markup).toContain("Plots &amp; land");
    expect(markup).toContain("Commercial");
  });

  it("builds the category explore href with the subtype filter", () => {
    expect(propertyTypeHref({ value: "farmland", category: "plots" })).toBe(
      "/dashboard/explore/plots?subtypes=farmland",
    );
  });
});
