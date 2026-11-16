import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/" }));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

import { AnnouncementBanner } from "@/components/announcement-banner";

function render(path: string): string {
  pathname.current = path;
  return renderToStaticMarkup(<AnnouncementBanner />);
}

function count(markup: string, needle: string): number {
  return markup.split(needle).length - 1;
}

describe("AnnouncementBanner", () => {
  it.each([
    ["/loans", "finance", "Loans"],
    ["/loans/home-loan", "finance", "Loans"],
    ["/real-estate", "property", "Real estate"],
    ["/real-estate/properties/abc", "property", "Real estate"],
  ])("shows one static, labelled line on %s", (path, kind, label) => {
    const markup = render(path);

    expect(markup).not.toContain("announcement-track");
    expect(count(markup, "data-trust-line=")).toBe(1);
    expect(markup).toContain(`data-trust-line="${kind}"`);
    expect(markup).toContain(label);
  });

  it("scrolls both lines on the home page as two distinctly labelled segments", () => {
    const markup = render("/");

    expect(markup).toContain("announcement-track");
    // Two copies (visible + loop duplicate), each with one segment per line.
    expect(count(markup, 'data-trust-line="finance"')).toBe(2);
    expect(count(markup, 'data-trust-line="property"')).toBe(2);
    expect(markup).toContain(">Loans<");
    expect(markup).toContain(">Real estate<");
    // Finance comes first in the visible copy.
    expect(markup.indexOf('data-trust-line="finance"')).toBeLessThan(markup.indexOf('data-trust-line="property"'));
  });

  it("hides only the loop duplicate from assistive technology", () => {
    const markup = render("/");
    const track = markup.slice(markup.indexOf("announcement-track"));
    const copies = track.match(/<span (aria-hidden="true" )?class="inline-flex items-center whitespace-nowrap/g) ?? [];

    expect(copies).toHaveLength(2);
    expect(copies[0]).not.toContain("aria-hidden");
    expect(copies[1]).toContain('aria-hidden="true"');
  });
});
