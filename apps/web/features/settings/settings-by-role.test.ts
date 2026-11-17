import { describe, expect, it } from "vitest";

import { settingsForRole } from "./settings-by-role";

describe("settingsForRole", () => {
  it("keeps everything for clients", () => {
    expect(settingsForRole("client")).toEqual({
      profileEditable: true,
      personalization: true,
      deleteAccount: true,
      contactChange: "self",
    });
  });

  it("drops only the personalization card for agents and admins", () => {
    for (const role of ["agent", "admin"]) {
      expect(settingsForRole(role)).toEqual({
        profileEditable: true,
        personalization: false,
        deleteAccount: true,
        contactChange: "self",
      });
    }
  });

  it("makes Admin-managed staff read-only and routes contact changes to an Admin", () => {
    for (const role of ["telecaller", "employee", "sub_admin"]) {
      expect(settingsForRole(role)).toEqual({
        profileEditable: false,
        personalization: false,
        deleteAccount: false,
        contactChange: "request",
      });
    }
  });
});
