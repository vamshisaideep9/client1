import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AssignedStaff, assignedStaffText } from "./assigned-staff";

const telecaller = { name: "Tara Caller", role_label: "Telecaller", staff_code: "TC-0012" };

describe("assigned staff", () => {
  it("joins name, role and staff code", () => {
    expect(assignedStaffText(telecaller)).toBe("Tara Caller · Telecaller · TC-0012");
    expect(assignedStaffText({ ...telecaller, name: null })).toBe("Telecaller · TC-0012");
    expect(assignedStaffText(null)).toBeNull();
  });

  it("shows the person, falling back to the staff code without a name", () => {
    const markup = renderToStaticMarkup(<AssignedStaff staff={telecaller} />);
    expect(markup).toContain("Tara Caller");
    expect(markup).toContain("Telecaller");
    expect(markup).toContain("TC-0012");
    expect(renderToStaticMarkup(<AssignedStaff staff={{ ...telecaller, name: null }} />)).toContain("TC-0012");
  });

  it("shows the empty text when nobody is assigned", () => {
    expect(renderToStaticMarkup(<AssignedStaff staff={null} />)).toContain("Not assigned yet");
    expect(renderToStaticMarkup(<AssignedStaff staff={undefined} empty="No field visit assigned yet" />)).toContain(
      "No field visit assigned yet",
    );
  });
});
