import { describe, expect, it } from "vitest";

import {
  buildContestDefinition,
  emptyContestForm,
  formFromContest,
  metricOptions,
  validateContestForm,
  type ContestFormState,
} from "./contest-form";
import { describeCriteria, describeWinning, formatContestDates } from "./contest-rules";

function form(overrides: Partial<ContestFormState> = {}): ContestFormState {
  return {
    ...emptyContestForm("2030-01-01"),
    title: "Personal loan sprint",
    endsOn: "2030-01-31",
    prizeRupees: "10000",
    countAtLeast: "1",
    ...overrides,
  };
}

describe("contest form", () => {
  it("sends minute windows and item prizes without a cash budget", () => {
    const input = form({
      prizeKind: "item",
      itemPrize: { label: "Headphones", details: "Office collection", estimate: "4000" },
      startsOn: "2030-01-01",
      endsOn: "2030-01-01",
      startTime: "09:00",
      endTime: "09:00",
      budgetCapRupees: "9000",
    });
    expect(validateContestForm(input)).toEqual({});
    expect(buildContestDefinition(input)).toMatchObject({
      start_time: "09:00",
      end_time: "09:00",
      prize_kind: "item",
      item_prize: { label: "Headphones", details: "Office collection", estimated_value_paise: 400000 },
      prize_paise: null,
      budget_cap_paise: null,
    });
    expect(validateContestForm({ ...input, endTime: "08:59" }).endTime).toMatch(/before/);
  });

  it("builds the reference example in paise", () => {
    const definition = buildContestDefinition(
      form({
        loanTypeIds: ["pl"],
        loanStage: "sanctioned",
        countAtMost: "5",
        totalAtLeastRupees: "50,00,000",
        metric: "amount",
        kycVerified: true,
        minTenureDays: "30",
      }),
    );
    expect(definition.criteria.loans).toMatchObject({
      loan_type_ids: ["pl"],
      counted_stage: "sanctioned",
      count_at_least: 1,
      count_at_most: 5,
      amount_at_least_paise: 50_00_000_00, // ₹50 lakh
    });
    expect(definition.criteria.eligibility).toEqual({ min_tenure_days: 30, kyc_verified: true });
    expect(definition.prize_paise).toBe(10_000_00);
    expect(definition.criteria.activity).toBeUndefined();
  });

  it("refuses an at-most count without an at-least count", () => {
    const errors = validateContestForm(form({ countAtLeast: "", countAtMost: "5" }));
    expect(errors.countAtMost).toMatch(/rewards doing less/);
  });

  it("needs a target when everyone who hits it wins", () => {
    expect(validateContestForm(form({ countAtLeast: "" })).countAtLeast).toMatch(/at least one target/);
    expect(validateContestForm(form({ countAtLeast: "", winMode: "top_n" }))).toEqual({});
  });

  it("offers only the metrics the audience can be measured on", () => {
    expect(metricOptions(form())).toEqual(["cases", "amount"]);
    expect(metricOptions(form({ audience: "telecaller" }))).toContain("calls_logged");
    expect(metricOptions(form({ audience: "employee" }))).not.toContain("calls_logged");
    expect(metricOptions(form({ audience: "employee", businessLine: "real_estate" }))).toContain(
      "site_visits_completed",
    );
  });

  it("sends staff activity only for the scored role and the team prize shape", () => {
    const definition = buildContestDefinition(
      form({
        audience: "team",
        teamMemberRole: "telecaller",
        metric: "calls_logged",
        countAtLeast: "",
        callsAtLeast: "500",
        tasksCompletedAtLeast: "9",
        prizeRupees: "",
        managerPrizeRupees: "5000",
        memberPrizeRupees: "1000",
        memberMinimum: "50",
      }),
    );
    expect(definition.criteria.loans).toBeUndefined();
    expect(definition.criteria.activity).toEqual({
      calls_logged_at_least: 500,
      connect_rate_at_least_percent: null,
      connect_rate_min_calls: null,
      follow_ups_on_time_at_least: null,
    });
    expect(definition).toMatchObject({
      prize_paise: null,
      manager_prize_paise: 5_000_00,
      member_prize_paise: 1_000_00,
      member_min_contribution: 50,
      team_member_role: "telecaller",
    });
  });

  it("requires a member minimum with a member prize and a connect-rate minimum", () => {
    const errors = validateContestForm(
      form({
        audience: "team",
        metric: "calls_logged",
        prizeRupees: "",
        managerPrizeRupees: "0",
        memberPrizeRupees: "100",
        connectRatePercent: "40",
      }),
    );
    expect(errors.memberMinimum).toBeDefined();
    expect(errors.connectRateMinCalls).toBeDefined();
  });

  it("round-trips a stored contest", () => {
    const definition = buildContestDefinition(
      form({ businessLine: "real_estate", dealStage: "booked", cities: ["Hyderabad"], perCaseMinRupees: "100" }),
    );
    const restored = formFromContest({
      ...definition,
      id: "c1",
      status: "draft",
      created_by_uuid: "u",
      created_by_name: null,
      is_mine: true,
      submitted_at: null,
      checker_name: null,
      reviewed_at: null,
      review_note: null,
      live_at: null,
      ended_at: null,
      finalized_at: null,
      cancelled_at: null,
      cancel_reason: null,
      version: 1,
      created_at: "",
      updated_at: "",
    } as never);
    expect(buildContestDefinition(restored)).toEqual(definition);
  });
});

describe("contest rules wording", () => {
  it("describes the criteria in plain language", () => {
    const lines = describeCriteria(
      {
        version: 1,
        loans: {
          loan_type_ids: ["pl"],
          counted_stage: "disbursed",
          count_at_least: 1,
          count_at_most: 5,
          amount_at_least_paise: 50_00_000_00,
        },
        eligibility: { min_tenure_days: 30, kyc_verified: true },
      },
      { loanTypes: { pl: "Personal loan" } },
    );
    expect(lines).toEqual([
      "Personal loan, counted when disbursed.",
      "Between 1 case and 5 cases.",
      "Total amount of at least ₹50,00,000.",
      "Open to people who joined at least 30 days before the start.",
      "KYC must be verified.",
    ]);
  });

  it("describes winning, team prizes and the cap", () => {
    expect(
      describeWinning({
        audience: "team",
        win_mode: "top_n",
        top_n: 2,
        metric: "calls_logged",
        manager_prize_paise: 5_000_00,
        member_prize_paise: 1_000_00,
        member_min_contribution: 50,
        budget_cap_paise: 20_000_00,
      }),
    ).toEqual([
      "The top 2 teams who meet every target win, ranked by calls logged. A tie at the last place is kept whole.",
      "The team's manager gets ₹5,000.",
      "Each member who contributed at least 50 gets ₹1,000.",
      "Prizes are capped at ₹20,000 in total and paid in rank order.",
    ]);
  });

  it("formats inclusive IST dates", () => {
    expect(formatContestDates("2030-01-01", "2030-01-31")).toBe("1 Jan 2030 – 31 Jan 2030");
  });
});
