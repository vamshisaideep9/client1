import { expect, it } from "vitest";
import { agentLeadUpdate } from "./agent-lead-update";

it("an email-only update never tries to clear hidden notes belonging to someone else", () => {
  expect(agentLeadUpdate({ product_slug: "home-loan" }, "", "new@example.com")).toEqual({
    requirement: { email: "new@example.com" },
  });
  expect(agentLeadUpdate({ notes: "Own note", email: "own@example.com" }, "Own note", "")).toEqual({
    requirement: { email: null },
  });
  expect(agentLeadUpdate({ notes: "Own note" }, "", "")).toEqual({ requirement: { notes: "" } });
  expect(agentLeadUpdate({ notes: "Own note", email: "own@example.com" }, "Own note", "own@example.com")).toBeNull();
});
