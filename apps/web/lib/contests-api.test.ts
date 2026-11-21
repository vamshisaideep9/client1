import { afterEach, describe, expect, it, vi } from "vitest";

import {
  approveContest,
  getContest,
  getMyContest,
  isContestId,
  markPrizePaid,
  requestPrizePayout,
} from "./contests-api";

const ID = "50000000-0000-4000-8000-000000000011";
const RESULT = "60000000-0000-4000-8000-000000000001";

function fakeFetch() {
  const fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({}),
  }) as unknown as Response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("contest ids in API paths (security review)", () => {
  it("accepts only canonical UUIDs", () => {
    expect(isContestId(ID)).toBe(true);
    expect(isContestId(ID.toUpperCase())).toBe(true);
    for (const bad of [null, "", "..", "../../auth/me", `${ID}/../x`, `${ID}?x=1`, "%2e%2e", `${ID} `]) {
      expect(isContestId(bad)).toBe(false);
    }
  });

  it("never sends a request for a crafted id", async () => {
    const fetch = fakeFetch();
    for (const bad of ["..", "../../admin/users", "%2e%2e%2fadmin", `${ID}/approve`]) {
      const responses = await Promise.all([
        getMyContest(bad),
        getContest(bad),
        approveContest(bad),
        markPrizePaid(ID, bad, "Payroll"),
        requestPrizePayout(bad, RESULT, { destination_type: "vpa", destination: { vpa: "a@b" } }),
      ]);
      for (const response of responses) {
        expect(response).toMatchObject({ ok: false, status: 400 });
      }
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("builds the expected paths for valid ids", async () => {
    const fetch = fakeFetch();
    await getMyContest(ID);
    await markPrizePaid(ID, RESULT, "Payroll");
    const urls = fetch.mock.calls.map((call) => String((call as unknown[])[0]));
    expect(urls[0]).toMatch(new RegExp(`/api/v1/my-contests/${ID}$`));
    expect(urls[1]).toMatch(new RegExp(`/api/v1/contests/${ID}/results/${RESULT}/mark-paid$`));
  });
});
