import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AboutContent } from "@/components/about/about-content";
import { SiteFooter } from "@/components/site-footer";
import { ABOUT_FAQ_ITEMS } from "@/lib/about";
import { jsonLdScript, organizationJsonLd } from "@/lib/organization-jsonld";
import { BUSINESS_FACTS, SITE_CONTACT } from "@/lib/site";

describe("organizationJsonLd", () => {
  it("matches the facts the footer renders", () => {
    const org = organizationJsonLd();
    const footer = renderToStaticMarkup(<SiteFooter />);
    expect(org["@type"]).toBe("FinancialService");
    expect(org.telephone).toBe("+919010053010");
    expect(org.email).toBe(SITE_CONTACT.email);
    expect(org.identifier.value).toBe(BUSINESS_FACTS.udyamNumber);
    expect(org.founder.name).toBe("R Rohini");
    expect(org.openingHoursSpecification[0]).toMatchObject({ opens: "10:00", closes: "18:00" });
    expect(org.openingHoursSpecification[0].dayOfWeek).not.toContain("Sunday");
    for (const fact of [SITE_CONTACT.phone, SITE_CONTACT.email, BUSINESS_FACTS.udyamNumber, BUSINESS_FACTS.proprietor]) {
      expect(footer).toContain(fact);
    }
  });

  it("never states figures the client asked to keep off the site", () => {
    const text = JSON.stringify(organizationJsonLd()) + renderToStaticMarkup(<AboutContent />) + JSON.stringify(ABOUT_FAQ_ITEMS);
    expect(text).not.toMatch(/1,?000 crore|CIBIL|550|insurance/i);
    // "Guaranteed approval" may appear only as the explicit denial.
    expect(text.match(/guaranteed approval/gi) ?? []).toHaveLength(1);
    expect(text).toContain("We never promise guaranteed approval.");
    expect(text).not.toMatch(/Sample Towers|98765 43210|hello@example\.com|7:00 PM/);
  });

  it("escapes markup so JSON-LD cannot close its script tag", () => {
    expect(jsonLdScript({ name: "</script><b>" })).not.toContain("</script>");
  });
});

describe("About page content", () => {
  it("renders one H1 and the business details table", () => {
    const html = renderToStaticMarkup(<AboutContent />);
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain("About Dhanadhara");
    expect(html).toContain("UDYAM-TS-28-0042986");
    expect(html).toContain("APHB Colony, Vikarabad, Telangana");
    expect(html).toContain("Monday to Saturday, 10 AM to 6 PM, Sunday closed");
  });
});
