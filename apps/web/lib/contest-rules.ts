// Labels and plain-language rule summaries for contests (CS-027), shared by the
// Sub Admin form, the Admin review desk and the participant pages. Pure, so the
// wording of money rules is unit-tested.

import type { components } from "@contracts/generated/schema";

import { formatPaise } from "@/lib/format";

type Schemas = components["schemas"];
type Criteria = Schemas["ContestCriteria"];
type Status = Schemas["ContestStatus"];
type Audience = Schemas["ContestAudience"];
type Metric = Schemas["ContestMetric"];

export const STATUS_LABEL: Record<Status, string> = {
  draft: "Draft",
  pending_approval: "Awaiting approval",
  approved: "Upcoming",
  live: "Live",
  ended: "Ended",
  finalized: "Winners confirmed",
  rejected: "Changes requested",
  cancelled: "Cancelled",
};

export const STATUS_TONE: Record<Status, "neutral" | "info" | "warning" | "success" | "danger"> = {
  draft: "neutral",
  pending_approval: "warning",
  approved: "info",
  live: "success",
  ended: "warning",
  finalized: "success",
  rejected: "danger",
  cancelled: "neutral",
};

export const AUDIENCE_LABEL: Record<Audience, string> = {
  agent: "Agents",
  telecaller: "Telecallers",
  employee: "Employees",
  team: "Teams",
};

export const TEAM_ROLE_LABEL: Record<Schemas["ContestTeamMemberRole"], string> = {
  telecaller: "Telecaller teams",
  employee: "Employee teams",
};

export const METRIC_LABEL: Record<Metric, string> = {
  cases: "Number of cases",
  amount: "Total amount",
  calls_logged: "Calls logged",
  follow_ups_on_time: "Follow-ups on time",
  tasks_completed: "Tasks completed",
  tasks_on_time: "Tasks on time",
  site_visits_completed: "Site visits completed",
};

export const LINE_LABEL: Record<"loans" | "real_estate", string> = {
  loans: "Loans",
  real_estate: "Real estate",
};

export const LOAN_STAGE_LABEL: Record<Schemas["LoanCriteria"]["counted_stage"], string> = {
  submitted: "Submitted to bank",
  sanctioned: "Approved (sanctioned)",
  disbursed: "Disbursed",
};

export const DEAL_STAGE_LABEL: Record<Schemas["RealEstateCriteria"]["counted_stage"], string> = {
  site_visit_done: "Site visit done",
  booked: "Booked",
  agreement_signed: "Agreement signed",
  closed: "Closed",
};

export const CATEGORY_LABEL: Record<string, string> = {
  houses: "Houses",
  apartments: "Apartments",
  villas: "Villas",
  plots: "Plots",
  commercial: "Commercial",
};

export const SUBTYPE_LABEL: Record<string, string> = {
  individual_house: "Individual house",
  standalone_apartment: "Standalone apartment",
  gated_community_apartment: "Gated community apartment",
  villa: "Villa",
  locked_space: "Locked space",
  unlocked_space: "Unlocked space",
  plot: "Plot",
  farmland: "Farmland",
  agriland: "Agricultural land",
};

export const SUBTYPE_CATEGORY: Record<string, string> = {
  individual_house: "houses",
  standalone_apartment: "apartments",
  gated_community_apartment: "apartments",
  villa: "villas",
  locked_space: "commercial",
  unlocked_space: "commercial",
  plot: "plots",
  farmland: "plots",
  agriland: "plots",
};

export const EXCLUSION_LABEL: Record<string, string> = {
  budget_cap: "Over the budget cap",
  below_member_minimum: "Below the member minimum",
};

export const PAYMENT_LABEL: Record<string, string> = {
  none: "No prize",
  unpaid: "Prize owed",
  payout_pending: "Payout awaiting approval",
  paid: "Paid",
};

/** The value a metric is measured in: money or a plain count. */
export function formatMetricValue(metric: Metric, value: number | null | undefined): string {
  if (value === null || value === undefined) return "Hidden";
  return metric === "amount" ? formatPaise(value) : value.toLocaleString("en-IN");
}

export function formatContestDates(startsOn: string, endsOn: string): string {
  const format = (iso: string) =>
    new Intl.DateTimeFormat("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(`${iso}T00:00:00Z`));
  return startsOn === endsOn ? format(startsOn) : `${format(startsOn)} – ${format(endsOn)}`;
}

function list(values: readonly string[], labels?: Record<string, string>): string {
  const named = values.map((value) => labels?.[value] ?? value);
  if (named.length <= 1) return named.join("");
  return `${named.slice(0, -1).join(", ")} or ${named[named.length - 1]}`;
}

/**
 * One sentence per rule, in the order a participant reads them. Product and
 * bank ids are named through `names` when known.
 */
export function describeCriteria(
  criteria: Criteria,
  names: { loanTypes?: Record<string, string>; banks?: Record<string, string> } = {},
): string[] {
  const lines: string[] = [];
  const loans = criteria.loans;
  const deals = criteria.real_estate;
  if (loans) {
    const what = loans.loan_type_ids?.length
      ? list(loans.loan_type_ids, names.loanTypes)
      : "Any loan product";
    lines.push(`${what}, counted when ${LOAN_STAGE_LABEL[loans.counted_stage].toLowerCase()}.`);
    if (loans.bank_ids?.length) lines.push(`Banks: ${list(loans.bank_ids, names.banks)}.`);
    pushRange(lines, "Each case", loans.case_amount_min_paise, loans.case_amount_max_paise);
    pushCounts(lines, "case", loans.count_at_least, loans.count_at_most);
    if (loans.amount_at_least_paise)
      lines.push(`Total amount of at least ${formatPaise(loans.amount_at_least_paise)}.`);
  }
  if (deals) {
    const kinds = deals.property_subtypes?.length
      ? list(deals.property_subtypes, SUBTYPE_LABEL)
      : deals.property_categories?.length
        ? list(deals.property_categories, CATEGORY_LABEL)
        : "Any property";
    const intent =
      deals.listing_intents?.length === 1
        ? deals.listing_intents[0] === "sale"
          ? " for sale"
          : " for rent"
        : "";
    lines.push(
      `${kinds}${intent}, counted when ${DEAL_STAGE_LABEL[deals.counted_stage].toLowerCase()}.`,
    );
    if (deals.cities?.length) lines.push(`Cities: ${list(deals.cities)}.`);
    pushRange(lines, "Each deal", deals.deal_value_min_paise, deals.deal_value_max_paise);
    pushCounts(lines, "deal", deals.count_at_least, deals.count_at_most);
    if (deals.value_at_least_paise)
      lines.push(`Total value of at least ${formatPaise(deals.value_at_least_paise)}.`);
  }
  const activity = criteria.activity;
  if (activity) {
    if (activity.calls_logged_at_least)
      lines.push(`At least ${activity.calls_logged_at_least} calls logged.`);
    if (activity.connect_rate_at_least_percent)
      lines.push(
        `Connect rate of ${activity.connect_rate_at_least_percent}% or more, over at least ${activity.connect_rate_min_calls} calls.`,
      );
    if (activity.follow_ups_on_time_at_least)
      lines.push(`At least ${activity.follow_ups_on_time_at_least} follow-ups kept on time.`);
    if (activity.tasks_completed_at_least)
      lines.push(`At least ${activity.tasks_completed_at_least} tasks completed.`);
    if (activity.tasks_on_time_at_least)
      lines.push(`At least ${activity.tasks_on_time_at_least} tasks completed on time.`);
    if (activity.site_visits_completed_at_least)
      lines.push(`At least ${activity.site_visits_completed_at_least} site visits completed.`);
  }
  const eligibility = criteria.eligibility;
  if (eligibility?.min_tenure_days)
    lines.push(`Open to people who joined at least ${eligibility.min_tenure_days} days before the start.`);
  if (eligibility?.kyc_verified) lines.push("KYC must be verified.");
  return lines;
}

function pushRange(
  lines: string[],
  subject: string,
  min: number | null | undefined,
  max: number | null | undefined,
) {
  if (min && max) lines.push(`${subject} between ${formatPaise(min)} and ${formatPaise(max)}.`);
  else if (min) lines.push(`${subject} of at least ${formatPaise(min)}.`);
  else if (max) lines.push(`${subject} of at most ${formatPaise(max)}.`);
}

function pushCounts(
  lines: string[],
  noun: string,
  atLeast: number | null | undefined,
  atMost: number | null | undefined,
) {
  const plural = (n: number) => `${n} ${noun}${n === 1 ? "" : "s"}`;
  if (atLeast && atMost) lines.push(`Between ${plural(atLeast)} and ${plural(atMost)}.`);
  else if (atLeast) lines.push(`At least ${plural(atLeast)}.`);
}

export function describeWinning(contest: {
  audience: Audience;
  win_mode: Schemas["ContestWinMode"];
  top_n?: number | null;
  prize_paise?: number | null;
  manager_prize_paise?: number | null;
  member_prize_paise?: number | null;
  member_min_contribution?: number | null;
  metric: Metric;
  budget_cap_paise?: number | null;
}): string[] {
  const lines: string[] = [];
  const who = contest.audience === "team" ? "team" : "participant";
  lines.push(
    contest.win_mode === "top_n"
      ? `The top ${contest.top_n} ${who}s who meet every target win, ranked by ${METRIC_LABEL[contest.metric].toLowerCase()}. A tie at the last place is kept whole.`
      : `Every ${who} who meets every target wins.`,
  );
  if (contest.audience === "team") {
    if (contest.manager_prize_paise)
      lines.push(`The team's manager gets ${formatPaise(contest.manager_prize_paise)}.`);
    if (contest.member_prize_paise)
      lines.push(
        `Each member who contributed at least ${formatMetricValue(contest.metric, contest.member_min_contribution ?? 0)} gets ${formatPaise(contest.member_prize_paise)}.`,
      );
  } else if (contest.prize_paise) {
    lines.push(`Each winner gets ${formatPaise(contest.prize_paise)}.`);
  }
  if (contest.budget_cap_paise)
    lines.push(
      `Prizes are capped at ${formatPaise(contest.budget_cap_paise)} in total and paid in rank order.`,
    );
  return lines;
}
