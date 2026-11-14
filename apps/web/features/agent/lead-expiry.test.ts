import { describe, expect, it } from "vitest";

import {
  AGENT_LEAD_EXPIRY_POLICY,
  formatAgentLeadExpiry,
  isAgentLeadExpiryDue,
} from "./lead-expiry";

const NOW = Date.parse("2026-08-06T00:00:00Z");

describe("formatAgentLeadExpiry", () => {
  it("shows a live window without a day countdown", () => {
    const label = formatAgentLeadExpiry("new", "2026-09-05T00:00:00Z", null, { nowMs: NOW });
    expect(label).toBe("Active");
    expect(label).not.toMatch(/Expires in/);
  });

  it("states the 30-day policy and the resubmit option", () => {
    expect(AGENT_LEAD_EXPIRY_POLICY).toContain("30 days");
    expect(AGENT_LEAD_EXPIRY_POLICY).toContain("resubmit");
  });

  it("distinguishes scheduler-pending, terminal, and expired ownership", () => {
    expect(
      formatAgentLeadExpiry("assigned", "2026-08-05T00:00:00Z", null, { nowMs: NOW }),
    ).toBe("Expiry due — awaiting pool release");
    expect(
      formatAgentLeadExpiry("converted", "2026-08-05T00:00:00Z", null, { nowMs: NOW }),
    ).toBe("No longer subject to expiry");
    expect(
      formatAgentLeadExpiry("expired", "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z", {
        nowMs: NOW,
      }),
    ).toBe("Expired 6 Aug 2026 — returned to pool");
  });

  it("offers a resubmit when the lead is eligible", () => {
    expect(
      formatAgentLeadExpiry("expired", "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z", {
        resubmittable: true,
        nowMs: NOW,
      }),
    ).toBe("Expired 6 Aug 2026 — you can resubmit it");
  });

  it("formats the transition date in the product's India timezone", () => {
    expect(
      formatAgentLeadExpiry("expired", "2026-08-06T00:00:00Z", "2026-08-06T20:00:00Z", {
        nowMs: NOW,
      }),
    ).toContain("7 Aug 2026");
  });

  it("treats a reached non-terminal deadline as due", () => {
    expect(isAgentLeadExpiryDue("assigned", "2026-08-05T00:00:00Z", null, NOW)).toBe(true);
    expect(isAgentLeadExpiryDue("converted", "2026-08-05T00:00:00Z", null, NOW)).toBe(false);
    expect(isAgentLeadExpiryDue("new", "invalid", null, NOW)).toBe(false);
  });
});
