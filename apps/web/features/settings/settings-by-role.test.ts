import { describe, expect, it } from "vitest";

import { settingsForRole } from "./settings-by-role";

describe("settingsForRole", () => {
  it("keeps everything for clients", () => {
    expect(settingsForRole("client")).toEqual({ profileEditable: true, personalization: true, deleteAccount: true });
  });

  it("drops only the personalization card for agents and admins", () => {
    for (const role of ["agent", "admin"]) {
      expect(settingsForRole(role)).toEqual({ profileEditable: true, personalization: false, deleteAccount: true });
    }
  });

  it("makes Admin-managed staff read-only with no personalization or delete", () => {
    for (const role of ["telecaller", "employee", "sub_admin"]) {
      expect(settingsForRole(role)).toEqual({ profileEditable: false, personalization: false, deleteAccount: false });
    }
  });
});
