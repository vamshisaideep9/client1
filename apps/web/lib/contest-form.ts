// Pure form state <-> ContestDefinition for the Sub Admin contest form
// (CS-027). Rupees are typed by people and converted to integer paise here; the
// server re-validates every rule, these checks only give earlier feedback.

import type { components } from "@contracts/generated/schema";

type Schemas = components["schemas"];
type Definition = Schemas["ContestDefinition"];
type Contest = Schemas["ContestRead"];
type ItemPrize = Schemas["ContestItemPrize"];

export type ItemPrizeForm = { label: string; details: string; estimate: string };
export type ItemPrizeField = "itemPrize" | "managerItemPrize" | "memberItemPrize";

export type ContestFormState = {
  title: string;
  description: string;
  terms: string;
  businessLine: "loans" | "real_estate";
  audience: Schemas["ContestAudience"];
  teamMemberRole: Schemas["ContestTeamMemberRole"];
  metric: Schemas["ContestMetric"];
  winMode: Schemas["ContestWinMode"];
  topN: string;
  prizeRupees: string;
  managerPrizeRupees: string;
  memberPrizeRupees: string;
  memberMinimum: string;
  budgetCapRupees: string;
  prizeKind: Schemas["ContestPrizeKind"];
  itemPrize: ItemPrizeForm;
  managerItemPrize: ItemPrizeForm;
  memberItemPrize: ItemPrizeForm;
  startsOn: string;
  startTime: string;
  endsOn: string;
  endTime: string;
  // Business conditions (the line decides which block is sent).
  loanTypeIds: string[];
  bankIds: string[];
  loanStage: Schemas["LoanCriteria"]["counted_stage"];
  dealStage: Schemas["RealEstateCriteria"]["counted_stage"];
  categories: string[];
  subtypes: string[];
  intents: string[];
  cities: string[];
  perCaseMinRupees: string;
  perCaseMaxRupees: string;
  countAtLeast: string;
  countAtMost: string;
  totalAtLeastRupees: string;
  // Activity targets (staff only).
  callsAtLeast: string;
  connectRatePercent: string;
  connectRateMinCalls: string;
  followUpsAtLeast: string;
  tasksCompletedAtLeast: string;
  tasksOnTimeAtLeast: string;
  siteVisitsAtLeast: string;
  // Eligibility.
  minTenureDays: string;
  kycVerified: boolean;
};

export const ACTIVITY_METRICS = [
  "calls_logged",
  "follow_ups_on_time",
  "tasks_completed",
  "tasks_on_time",
  "site_visits_completed",
] as const;

export function emptyContestForm(today: string): ContestFormState {
  return {
    title: "",
    description: "",
    terms: "",
    businessLine: "loans",
    audience: "agent",
    teamMemberRole: "telecaller",
    metric: "cases",
    winMode: "threshold",
    topN: "3",
    prizeRupees: "",
    managerPrizeRupees: "",
    memberPrizeRupees: "",
    memberMinimum: "",
    budgetCapRupees: "",
    prizeKind: "cash",
    itemPrize: itemPrizeForm(),
    managerItemPrize: itemPrizeForm(),
    memberItemPrize: itemPrizeForm(),
    startsOn: today,
    startTime: "00:00",
    endsOn: today,
    endTime: "23:59",
    loanTypeIds: [],
    bankIds: [],
    loanStage: "disbursed",
    dealStage: "closed",
    categories: [],
    subtypes: [],
    intents: [],
    cities: [],
    perCaseMinRupees: "",
    perCaseMaxRupees: "",
    countAtLeast: "",
    countAtMost: "",
    totalAtLeastRupees: "",
    callsAtLeast: "",
    connectRatePercent: "",
    connectRateMinCalls: "",
    followUpsAtLeast: "",
    tasksCompletedAtLeast: "",
    tasksOnTimeAtLeast: "",
    siteVisitsAtLeast: "",
    minTenureDays: "",
    kycVerified: false,
  };
}

/** The role whose work is scored: the audience, or a team's members. */
export function scoredRole(form: Pick<ContestFormState, "audience" | "teamMemberRole">) {
  return form.audience === "team" ? form.teamMemberRole : form.audience;
}

export function metricOptions(form: ContestFormState): Schemas["ContestMetric"][] {
  const role = scoredRole(form);
  const business: Schemas["ContestMetric"][] = ["cases", "amount"];
  if (role === "agent") return business;
  const visits: Schemas["ContestMetric"][] =
    form.businessLine === "real_estate" ? ["site_visits_completed"] : [];
  if (role === "telecaller") return [...business, "calls_logged", "follow_ups_on_time", ...visits];
  return [...business, "tasks_completed", "tasks_on_time", ...visits];
}

const rupeesToPaise = (value: string): number | null => {
  const trimmed = value.replace(/,/g, "").trim();
  if (!trimmed) return null;
  const amount = Number(trimmed);
  return Number.isFinite(amount) ? Math.round(amount * 100) : Number.NaN;
};

const whole = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isInteger(n) ? n : Number.NaN;
};

const paiseToRupees = (paise: number | null | undefined): string =>
  paise === null || paise === undefined ? "" : String(paise / 100);
const text = (value: number | null | undefined): string =>
  value === null || value === undefined ? "" : String(value);

function itemPrizeForm(prize?: ItemPrize | null): ItemPrizeForm {
  return {
    label: prize?.label ?? "",
    details: prize?.details ?? "",
    estimate: paiseToRupees(prize?.estimated_value_paise),
  };
}

function itemPrizeValue(form: ItemPrizeForm): ItemPrize | null {
  const label = form.label.trim();
  return label ? {
    label,
    details: form.details.trim() || null,
    estimated_value_paise: rupeesToPaise(form.estimate),
  } : null;
}

export const IST_MINUTE = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

export function usesBusiness(form: ContestFormState): boolean {
  return (
    scoredRole(form) === "agent" ||
    form.metric === "cases" ||
    form.metric === "amount" ||
    form.loanTypeIds.length > 0 ||
    form.bankIds.length > 0 ||
    form.categories.length > 0 ||
    form.subtypes.length > 0 ||
    form.intents.length > 0 ||
    form.cities.length > 0 ||
    [form.countAtLeast, form.countAtMost, form.totalAtLeastRupees, form.perCaseMinRupees, form.perCaseMaxRupees].some(
      (value) => value.trim() !== "",
    )
  );
}

/** Field errors keyed by form field; empty when the form can be sent. */
export function validateContestForm(form: ContestFormState): Record<string, string> {
  const errors: Record<string, string> = {};
  const positive = (key: keyof ContestFormState, label: string, value: number | null) => {
    if (value !== null && (Number.isNaN(value) || value < 1)) errors[key] = `${label} must be 1 or more.`;
  };
  if (form.title.trim().length < 3) errors.title = "Give the contest a title of at least 3 characters.";
  if (!form.startsOn) errors.startsOn = "Choose a start date.";
  if (!form.endsOn) errors.endsOn = "Choose an end date.";
  if (!IST_MINUTE.test(form.startTime)) errors.startTime = "Choose a start time.";
  if (!IST_MINUTE.test(form.endTime)) errors.endTime = "Choose an end time.";
  if (form.startsOn && form.endsOn && form.endsOn < form.startsOn)
    errors.endsOn = "The end date is before the start date.";
  if (!errors.startTime && !errors.endTime && form.startsOn === form.endsOn && form.endTime < form.startTime)
    errors.endTime = "The end time is before the start time.";

  if (form.winMode === "top_n") {
    const n = whole(form.topN);
    if (n === null || Number.isNaN(n) || n < 1 || n > 100) errors.topN = "Choose between 1 and 100 winners.";
  }
  if (form.prizeKind === "item") {
    const fields: ItemPrizeField[] = form.audience === "team"
      ? ["managerItemPrize", "memberItemPrize"] : ["itemPrize"];
    if (fields.every((field) => !form[field].label.trim()))
      errors[fields[0]] = form.audience === "team" ? "Set a manager or member item." : "Name the item.";
    for (const field of fields) {
      const prize = form[field];
      const value = rupeesToPaise(prize.estimate);
      if (!prize.label.trim() && (prize.details.trim() || prize.estimate.trim()))
        errors[field] = "Name the item or clear its details.";
      else if (value !== null && (!Number.isFinite(value) || value < 1 || value > 1_000_000_000))
        errors[field] = "Enter a positive estimate of up to ₹1 crore.";
    }
    if (form.audience === "team" && form.memberItemPrize.label.trim()) {
      const minimum = form.metric === "amount" ? rupeesToPaise(form.memberMinimum)
        : whole(form.memberMinimum.replace(/,/g, ""));
      if (!minimum || minimum < 1) errors.memberMinimum = "Set the minimum each member must contribute.";
    }
  } else if (form.audience === "team") {
    const manager = rupeesToPaise(form.managerPrizeRupees);
    const member = rupeesToPaise(form.memberPrizeRupees);
    if (manager === null || Number.isNaN(manager) || manager < 0)
      errors.managerPrizeRupees = "Enter the manager prize (0 for none).";
    if (member === null || Number.isNaN(member) || member < 0)
      errors.memberPrizeRupees = "Enter the member prize (0 for none).";
    if (!errors.managerPrizeRupees && !errors.memberPrizeRupees && (manager ?? 0) + (member ?? 0) <= 0)
      errors.managerPrizeRupees = "Set a manager or a member prize.";
    if ((member ?? 0) > 0) {
      const minimum = whole(form.memberMinimum.replace(/,/g, ""));
      if (minimum === null || Number.isNaN(minimum) || minimum < 1)
        errors.memberMinimum = "Set the minimum each member must contribute.";
    }
  } else {
    const prize = rupeesToPaise(form.prizeRupees);
    if (prize === null || Number.isNaN(prize) || prize < 1) errors.prizeRupees = "Enter the prize for each winner.";
  }
  const cap = rupeesToPaise(form.budgetCapRupees);
  if (form.prizeKind === "cash" && cap !== null && (Number.isNaN(cap) || cap < 1))
    errors.budgetCapRupees = "Enter a positive budget cap or leave it empty.";

  if (usesBusiness(form)) {
    const atLeast = whole(form.countAtLeast);
    const atMost = whole(form.countAtMost);
    positive("countAtLeast", "The at-least count", atLeast);
    positive("countAtMost", "The at-most count", atMost);
    if (atMost !== null && atLeast === null)
      errors.countAtMost = "An at-most count needs an at-least count too, or it rewards doing less.";
    else if (atMost !== null && atLeast !== null && atMost < atLeast)
      errors.countAtMost = "The at-most count is below the at-least count.";
    const min = rupeesToPaise(form.perCaseMinRupees);
    const max = rupeesToPaise(form.perCaseMaxRupees);
    if (min !== null && Number.isNaN(min)) errors.perCaseMinRupees = "Enter an amount in rupees.";
    if (max !== null && Number.isNaN(max)) errors.perCaseMaxRupees = "Enter an amount in rupees.";
    if (min !== null && max !== null && max < min) errors.perCaseMaxRupees = "The maximum is below the minimum.";
    const total = rupeesToPaise(form.totalAtLeastRupees);
    if (total !== null && (Number.isNaN(total) || total < 1)) errors.totalAtLeastRupees = "Enter an amount in rupees.";
  }
  const rate = whole(form.connectRatePercent);
  const minCalls = whole(form.connectRateMinCalls);
  if (rate !== null && (Number.isNaN(rate) || rate < 1 || rate > 100))
    errors.connectRatePercent = "Enter a percentage between 1 and 100.";
  if ((rate === null) !== (minCalls === null))
    errors.connectRateMinCalls = "A connect-rate target needs a minimum number of calls.";
  for (const [key, label] of [
    ["callsAtLeast", "Calls"],
    ["followUpsAtLeast", "Follow-ups"],
    ["tasksCompletedAtLeast", "Tasks"],
    ["tasksOnTimeAtLeast", "On-time tasks"],
    ["siteVisitsAtLeast", "Site visits"],
    ["connectRateMinCalls", "Minimum calls"],
  ] as const) {
    if (!errors[key]) positive(key, label, whole(form[key]));
  }
  if (form.winMode === "threshold" && !hasTarget(form))
    errors.countAtLeast = "Add at least one target, or everyone would win.";
  return errors;
}

function hasTarget(form: ContestFormState): boolean {
  return [
    form.countAtLeast,
    form.totalAtLeastRupees,
    form.callsAtLeast,
    form.connectRatePercent,
    form.followUpsAtLeast,
    form.tasksCompletedAtLeast,
    form.tasksOnTimeAtLeast,
    form.siteVisitsAtLeast,
  ].some((value) => value.trim() !== "");
}

function activityFor(form: ContestFormState): Schemas["ActivityCriteria"] | null {
  const role = scoredRole(form);
  if (role === "agent") return null;
  const activity: Schemas["ActivityCriteria"] =
    role === "telecaller"
      ? {
          calls_logged_at_least: whole(form.callsAtLeast),
          connect_rate_at_least_percent: whole(form.connectRatePercent),
          connect_rate_min_calls: whole(form.connectRateMinCalls),
          follow_ups_on_time_at_least: whole(form.followUpsAtLeast),
        }
      : {
          tasks_completed_at_least: whole(form.tasksCompletedAtLeast),
          tasks_on_time_at_least: whole(form.tasksOnTimeAtLeast),
        };
  if (form.businessLine === "real_estate")
    activity.site_visits_completed_at_least = whole(form.siteVisitsAtLeast);
  const populated = Object.values(activity).some((value) => value !== null && value !== undefined);
  return populated ? activity : null;
}

export function buildContestDefinition(form: ContestFormState): Definition {
  const team = form.audience === "team";
  const criteria: Schemas["ContestCriteria"] = { version: 1 };
  if (usesBusiness(form)) {
    const counts = {
      count_at_least: whole(form.countAtLeast),
      count_at_most: whole(form.countAtMost),
    };
    if (form.businessLine === "loans") {
      criteria.loans = {
        loan_type_ids: form.loanTypeIds,
        bank_ids: form.bankIds,
        counted_stage: form.loanStage,
        case_amount_min_paise: rupeesToPaise(form.perCaseMinRupees),
        case_amount_max_paise: rupeesToPaise(form.perCaseMaxRupees),
        amount_at_least_paise: rupeesToPaise(form.totalAtLeastRupees),
        ...counts,
      };
    } else {
      criteria.real_estate = {
        property_categories: form.categories as Schemas["RealEstateCriteria"]["property_categories"],
        property_subtypes: form.subtypes as Schemas["RealEstateCriteria"]["property_subtypes"],
        listing_intents: form.intents as Schemas["RealEstateCriteria"]["listing_intents"],
        cities: form.cities,
        counted_stage: form.dealStage,
        deal_value_min_paise: rupeesToPaise(form.perCaseMinRupees),
        deal_value_max_paise: rupeesToPaise(form.perCaseMaxRupees),
        value_at_least_paise: rupeesToPaise(form.totalAtLeastRupees),
        ...counts,
      };
    }
  }
  const activity = activityFor(form);
  if (activity) criteria.activity = activity;
  criteria.eligibility = {
    min_tenure_days: whole(form.minTenureDays) ?? 0,
    kyc_verified: scoredRole(form) === "agent" ? form.kycVerified : false,
  };
  const cash = form.prizeKind === "cash";
  const memberPrize = cash && team ? rupeesToPaise(form.memberPrizeRupees) ?? 0 : null;
  const memberItem = !cash && team ? itemPrizeValue(form.memberItemPrize) : null;
  return {
    title: form.title.trim(),
    description: form.description.trim() || null,
    terms: form.terms.trim() || null,
    business_line: form.businessLine,
    audience: form.audience,
    team_member_role: team ? form.teamMemberRole : null,
    metric: form.metric,
    criteria,
    win_mode: form.winMode,
    top_n: form.winMode === "top_n" ? whole(form.topN) : null,
    prize_paise: cash && !team ? rupeesToPaise(form.prizeRupees) : null,
    manager_prize_paise: cash && team ? rupeesToPaise(form.managerPrizeRupees) ?? 0 : null,
    member_prize_paise: memberPrize,
    prize_kind: form.prizeKind,
    item_prize: !cash && !team ? itemPrizeValue(form.itemPrize) : null,
    manager_item_prize: !cash && team ? itemPrizeValue(form.managerItemPrize) : null,
    member_item_prize: memberItem,
    member_min_contribution:
      team && ((memberPrize ?? 0) > 0 || memberItem)
        ? form.metric === "amount"
          ? rupeesToPaise(form.memberMinimum)
          : whole(form.memberMinimum)
        : null,
    budget_cap_paise: cash ? rupeesToPaise(form.budgetCapRupees) : null,
    starts_on: form.startsOn,
    ends_on: form.endsOn,
    start_time: form.startTime,
    end_time: form.endTime,
  };
}

export function formFromContest(contest: Contest): ContestFormState {
  const loans = contest.criteria.loans;
  const deals = contest.criteria.real_estate;
  const business = loans ?? deals;
  const activity = contest.criteria.activity;
  return {
    ...emptyContestForm(contest.starts_on),
    title: contest.title,
    description: contest.description ?? "",
    terms: contest.terms ?? "",
    businessLine: contest.business_line,
    audience: contest.audience,
    teamMemberRole: contest.team_member_role ?? "telecaller",
    metric: contest.metric,
    winMode: contest.win_mode,
    topN: text(contest.top_n) || "3",
    prizeRupees: paiseToRupees(contest.prize_paise),
    managerPrizeRupees: paiseToRupees(contest.manager_prize_paise),
    memberPrizeRupees: paiseToRupees(contest.member_prize_paise),
    memberMinimum:
      contest.metric === "amount"
        ? paiseToRupees(contest.member_min_contribution)
        : text(contest.member_min_contribution),
    budgetCapRupees: paiseToRupees(contest.budget_cap_paise),
    prizeKind: contest.prize_kind ?? "cash",
    itemPrize: itemPrizeForm(contest.item_prize),
    managerItemPrize: itemPrizeForm(contest.manager_item_prize),
    memberItemPrize: itemPrizeForm(contest.member_item_prize),
    startsOn: contest.starts_on,
    startTime: contest.start_time?.slice(0, 5) ?? "00:00",
    endsOn: contest.ends_on,
    endTime: contest.end_time?.slice(0, 5) ?? "23:59",
    loanTypeIds: loans?.loan_type_ids ?? [],
    bankIds: loans?.bank_ids ?? [],
    loanStage: loans?.counted_stage ?? "disbursed",
    dealStage: deals?.counted_stage ?? "closed",
    categories: deals?.property_categories ?? [],
    subtypes: deals?.property_subtypes ?? [],
    intents: deals?.listing_intents ?? [],
    cities: deals?.cities ?? [],
    perCaseMinRupees: paiseToRupees(loans?.case_amount_min_paise ?? deals?.deal_value_min_paise),
    perCaseMaxRupees: paiseToRupees(loans?.case_amount_max_paise ?? deals?.deal_value_max_paise),
    countAtLeast: text(business?.count_at_least),
    countAtMost: text(business?.count_at_most),
    totalAtLeastRupees: paiseToRupees(loans?.amount_at_least_paise ?? deals?.value_at_least_paise),
    callsAtLeast: text(activity?.calls_logged_at_least),
    connectRatePercent: text(activity?.connect_rate_at_least_percent),
    connectRateMinCalls: text(activity?.connect_rate_min_calls),
    followUpsAtLeast: text(activity?.follow_ups_on_time_at_least),
    tasksCompletedAtLeast: text(activity?.tasks_completed_at_least),
    tasksOnTimeAtLeast: text(activity?.tasks_on_time_at_least),
    siteVisitsAtLeast: text(activity?.site_visits_completed_at_least),
    minTenureDays: contest.criteria.eligibility?.min_tenure_days
      ? String(contest.criteria.eligibility.min_tenure_days)
      : "",
    kycVerified: contest.criteria.eligibility?.kyc_verified ?? false,
  };
}
