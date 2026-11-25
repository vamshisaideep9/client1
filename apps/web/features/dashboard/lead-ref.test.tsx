import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LeadRefBadge, LeadRefList, LeadRefText } from "./lead-ref";

describe("lead reference display", () => {
  it("shows the API-formatted reference as tabular monospace text", () => {
    const markup = renderToStaticMarkup(<LeadRefText value="LD-00000123" />);
    expect(markup).toContain("LD-00000123");
    expect(markup).toContain("font-mono");
  });

  it("renders nothing without a reference", () => {
    expect(renderToStaticMarkup(<LeadRefText value={null} />)).toBe("");
    expect(renderToStaticMarkup(<LeadRefList values={[]} />)).toBe("");
    expect(renderToStaticMarkup(<LeadRefBadge value={undefined} />)).toBe("");
  });

  it("lists a grouped payout's references", () => {
    expect(renderToStaticMarkup(<LeadRefList values={["LD-00000003", "LD-00000007"]} />)).toContain(
      "LD-00000003, LD-00000007",
    );
  });

  it("gives the detail-header badge a labelled, full-size copy button", () => {
    const markup = renderToStaticMarkup(<LeadRefBadge value="LD-00000123" />);
    expect(markup).toContain("Lead ref");
    expect(markup).toContain('aria-label="Copy lead reference LD-00000123"');
    expect(markup).toContain('type="button"');
    expect(markup).toContain("h-11 w-11");
    expect(markup).toContain('aria-live="polite"');
  });
});
