"use client";

import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import {
  AUDIENCE_LABEL,
  describeCriteria,
  describeWinning,
  formatContestDates,
  LINE_LABEL,
  TEAM_ROLE_LABEL,
} from "@/lib/contest-rules";
import type { components } from "@contracts/generated/schema";

type Schemas = components["schemas"];

type RulesSource = Pick<
  Schemas["ContestRead"],
  | "criteria"
  | "audience"
  | "team_member_role"
  | "business_line"
  | "starts_on"
  | "ends_on"
  | "start_time"
  | "end_time"
  | "win_mode"
  | "top_n"
  | "prize_paise"
  | "manager_prize_paise"
  | "member_prize_paise"
  | "item_prize"
  | "manager_item_prize"
  | "member_item_prize"
  | "member_min_contribution"
  | "metric"
  | "budget_cap_paise"
  | "description"
  | "terms"
>;

/** The rules of one contest in plain language, for every audience. */
export function ContestRulesPanel({ contest }: { contest: RulesSource }) {
  const catalogue = useProductCatalogue(Boolean(contest.criteria.loans));
  const loanTypes = Object.fromEntries(catalogue.loanTypes.map((o) => [o.value, o.label]));
  const banks = Object.fromEntries(catalogue.banks.map((o) => [o.value, o.label]));
  const who =
    contest.audience === "team" && contest.team_member_role
      ? TEAM_ROLE_LABEL[contest.team_member_role]
      : AUDIENCE_LABEL[contest.audience];
  return (
    <div className="space-y-4 text-sm">
      {contest.description ? <p className="text-text-primary">{contest.description}</p> : null}
      <dl className="grid gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-text-secondary">Who</dt>
          <dd className="font-medium text-text-primary">
            {who} · {LINE_LABEL[contest.business_line]}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-text-secondary">When</dt>
          <dd className="font-medium text-text-primary">
            {formatContestDates(contest.starts_on, contest.ends_on, contest.start_time, contest.end_time)}
            {" · End minute included"}
          </dd>
        </div>
      </dl>
      <section aria-label="Targets">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">What counts</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-text-primary">
          {describeCriteria(contest.criteria, { loanTypes, banks }).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
      <section aria-label="Winning">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Winning</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-text-primary">
          {describeWinning(contest).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
      {contest.terms ? (
        <section aria-label="Terms">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Terms</h3>
          <p className="mt-2 whitespace-pre-line text-text-secondary">{contest.terms}</p>
        </section>
      ) : null}
    </div>
  );
}
