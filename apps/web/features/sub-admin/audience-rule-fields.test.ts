import { describe, expect, it } from "vitest";

import {
  audienceSummary,
  emptyAudienceRules,
  normalizeAudienceRules,
  withAgentSignals,
  withClientJourneyStages,
  withPlaceTargets,
} from "./audience-rule-fields";

describe("audience rule helpers", () => {
  it("keeps a generated-contract-compatible generic rule shape", () => {
    expect(emptyAudienceRules()).toEqual({
      version: 1,
      user_types: [],
      client_journey_stages: [],
      agent_signals: [],
      locations: [],
      pincodes: [],
      cities: [],
    });
    expect(audienceSummary(emptyAudienceRules())).toBe("Everyone");
  });

  it("uses version 2 only when pincode or city targets are present (CS-026)", () => {
    const plain = normalizeAudienceRules({ version: 1, user_types: ["client"] });
    expect(plain.version).toBe(1);

    const shared = { ...emptyAudienceRules(), user_types: ["client", "agent"] as ("client" | "agent")[] };
    const placed = withPlaceTargets(shared, {
      pincodes: ["500001"],
      cities: [{ district: "Hyderabad", state: "Telangana" }],
    });
    expect(placed.version).toBe(2);
    expect(placed.user_types).toEqual(["client"]);
    expect(audienceSummary(placed)).toBe("Clients · 1 city · 1 pincode");

    const cleared = withPlaceTargets(placed, { pincodes: [], cities: [] });
    expect(cleared.version).toBe(1);

    // Agent signals make the audience Agent-only, which drops place targets.
    const agentOnly = withAgentSignals(placed, ["no_leads"]);
    expect(agentOnly.pincodes).toEqual([]);
    expect(agentOnly.cities).toEqual([]);
    expect(agentOnly.version).toBe(1);
  });

  it("summarizes targeted dimensions without exposing coordinates", () => {
    const rules = normalizeAudienceRules({
      version: 1,
      user_types: ["client"],
      client_journey_stages: ["in_progress", "on_hold"],
      locations: [
        { label: "Hyderabad", latitude: 17.39, longitude: 78.49, radius_km: 25 },
      ],
    });

    expect(audienceSummary(rules)).toBe("Clients · 2 workflow signals · 1 area");
    expect(audienceSummary(rules)).not.toContain("17.39");
  });

  it("describes a role-only shared audience", () => {
    expect(
      audienceSummary({ version: 1, user_types: ["client", "agent"] }),
    ).toBe("Clients + Agents");
  });

  it("keeps role-specific workflow dimensions mutually exclusive", () => {
    const shared = emptyAudienceRules();
    shared.user_types = ["client", "agent"];
    const clientRules = withClientJourneyStages(shared, ["in_progress"]);
    expect(clientRules.user_types).toEqual(["client"]);
    expect(clientRules.agent_signals).toEqual([]);

    const agentRules = withAgentSignals(clientRules, ["has_active_leads"]);
    expect(agentRules.user_types).toEqual(["agent"]);
    expect(agentRules.client_journey_stages).toEqual([]);
  });
});
