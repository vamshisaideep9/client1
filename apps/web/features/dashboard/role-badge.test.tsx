import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RoleBadge, roleProfileFor, type RoleProfile } from "./role-badge";

describe("role identifiers", () => {
  it("keeps platform staff metadata independent of the operational line selector", () => {
    const admin: RoleProfile = { profile_uuid: "10000000-0000-4000-8000-000000000001", role: "admin", code: "ADMIN-001", business_line: null };
    expect(roleProfileFor([admin], "admin", "both")?.code).toBe("ADMIN-001");
  });
  it("selects metadata for the current role and line", () => {
    const first: RoleProfile = { profile_uuid: "first", role: "agent", code: "AG-LOANS", business_line: "loans" };
    const second: RoleProfile = { profile_uuid: "second", role: "agent", code: "AG-ESTATE", business_line: "real_estate" };
    expect(roleProfileFor([first, second], "agent", "real_estate")?.code).toBe("AG-ESTATE");
    expect(roleProfileFor([first, second], "employee", "loans")).toBeUndefined();
  });
  it("shows the real code, specialty and both team names", () => {
    const profile: RoleProfile = {
      profile_uuid: "10000000-0000-4000-8000-000000000001", role: "telecaller",
      code: "TC-ASSIGNED-CODE", business_line: "both", loan_specialty_label: "Home Loan",
      teams: [{ business_line: "loans", name: "Loans East" }, { business_line: "real_estate", name: "Property West" }],
    };
    const html = renderToStaticMarkup(<RoleBadge role="telecaller" profile={profile} />);
    for (const text of ["Telecaller", "TC-ASSIGNED-CODE", "Specialty: Home Loan", "Loans team: Loans East", "Real Estate team: Property West"]) expect(html).toContain(text);
    expect(html).not.toContain(profile.profile_uuid);
  });

  it("keeps role and line useful when optional metadata is missing", () => {
    const html = renderToStaticMarkup(<RoleBadge role="employee" businessLine="real_estate" />);
    expect(html).toContain("Officer");
    expect(html).toContain("Real Estate");
    expect(html).not.toContain("Specialty:");
    expect(html).not.toContain("undefined");
  });

  it("shows the supplied Client code", () => {
    const html = renderToStaticMarkup(<RoleBadge role="client" businessLine="loans" code="CLIENT-CODE" />);
    expect(html).toContain("CLIENT-CODE");
  });
});
