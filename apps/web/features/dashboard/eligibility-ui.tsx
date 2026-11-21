"use client";

import * as React from "react";
import { BadgeCheck, CircleSlash, Copy, ShieldCheck } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  ATTEMPT_ELIGIBILITY_OPTIONS,
  ELIGIBILITY_LABEL,
  ELIGIBILITY_TONE,
  matchesAttemptOutcome,
  notEligibleHint,
  rowEligibility,
  type EligibilityOutcome,
  type EligibilitySummary,
  type IntakeAttempt,
} from "./eligibility";
import { FetchError } from "./fetch-error";
import { FilterSelect } from "./filter-select";
import { ListEmptyState } from "./list-states";
import { ListPagination, useListPagination } from "./list-pagination";
import { StatusBadge } from "./status-badge";

/** The Eligible / Not eligible / Duplicate pill, with the rule underneath when one applies. */
export function EligibilityBadge({
  eligibility,
  reasonLabel,
  className,
}: {
  eligibility: EligibilityOutcome | null;
  reasonLabel?: string | null;
  className?: string;
}) {
  if (!eligibility) return <span className="text-text-secondary">-</span>;
  return (
    <span className={cn("flex min-w-0 flex-col items-start gap-1", className)}>
      <StatusBadge tone={ELIGIBILITY_TONE[eligibility]}>{ELIGIBILITY_LABEL[eligibility]}</StatusBadge>
      {reasonLabel ? (
        <span className="max-w-56 text-xs text-text-secondary [overflow-wrap:anywhere]">{reasonLabel}</span>
      ) : null}
    </span>
  );
}

/** Badge for a list row that carries `eligibility` and its reason label. */
export function RowEligibilityBadge({
  row,
}: {
  row: { eligibility?: string | null; eligibility_reason_label?: string | null };
}) {
  const eligibility = rowEligibility(row);
  return (
    <EligibilityBadge
      eligibility={eligibility}
      reasonLabel={eligibility === "not_eligible" ? row.eligibility_reason_label : null}
    />
  );
}

/**
 * Three counts: Eligible (accepted rows), Not eligible (accepted rows a rule
 * excludes plus attempts a rule turned away) and Duplicate (attempts turned
 * away as duplicates). Hidden quietly if the summary could not load; the
 * lists below still work.
 */
export function EligibilitySummaryCards({
  summary,
  loading,
  noun,
  eligibleHint,
  duplicateHint,
}: {
  summary: EligibilitySummary | null;
  loading: boolean;
  noun: { one: string; many: string };
  eligibleHint: string;
  duplicateHint: string;
}) {
  if (loading && !summary) return <Skeleton className="h-24 rounded-xl" aria-hidden="true" />;
  if (!summary) return null;
  const tiles = [
    { outcome: "eligible", icon: BadgeCheck, value: summary.eligible, hint: eligibleHint },
    { outcome: "not_eligible", icon: CircleSlash, value: summary.not_eligible, hint: notEligibleHint(summary, noun) },
    { outcome: "duplicate", icon: Copy, value: summary.duplicate, hint: duplicateHint },
  ] as const;
  // One card split in three, so the counts stay side by side on a phone
  // instead of stacking three full-height cards above the list.
  return (
    <section
      aria-label="Eligibility summary"
      className="grid grid-cols-3 divide-x divide-border rounded-xl border border-border bg-card shadow-sm"
    >
      {tiles.map(({ outcome, icon: Icon, value, hint }) => (
        <div key={outcome} className="min-w-0 p-3 sm:p-4">
          <p className="flex items-center gap-1.5 text-xs font-medium text-text-secondary sm:text-sm">
            <Icon className={cn("h-4 w-4 shrink-0", TONE_TEXT[ELIGIBILITY_TONE[outcome]])} aria-hidden="true" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{ELIGIBILITY_LABEL[outcome]}</span>
          </p>
          <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-brand-heading">{value}</p>
          <p className="mt-1 text-xs text-text-secondary [overflow-wrap:anywhere]">{hint}</p>
        </div>
      ))}
    </section>
  );
}

const TONE_TEXT: Record<string, string> = {
  success: "text-success",
  danger: "text-destructive",
  warning: "text-warning",
};

/** "Not accepted (3)" for the tab trigger. */
export function notAcceptedTabLabel(total: number): string {
  return total > 0 ? `Not accepted (${total})` : "Not accepted";
}

/**
 * Recorded attempts that were turned away, with an Eligibility filter
 * (Duplicate / Not eligible), the masked number, the reason and the date.
 */
export function NotAcceptedList({
  attempts,
  total,
  loading,
  error,
  onRetry,
  emptyDescription,
  label,
}: {
  attempts: readonly IntakeAttempt[];
  total: number;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  emptyDescription: string;
  /** Accessible name of the table and its pages, e.g. "Leads not accepted". */
  label: string;
}) {
  const [outcome, setOutcome] = React.useState("all");
  const filtered = React.useMemo(
    () => attempts.filter((attempt) => matchesAttemptOutcome(attempt, outcome)),
    [attempts, outcome],
  );
  const { page, pageItems, setPage } = useListPagination(filtered);
  const changeOutcome = (next: string) => {
    setOutcome(next);
    setPage(0);
  };

  if (loading && attempts.length === 0) return <Skeleton className="h-40 rounded-xl" />;
  if (error) return <FetchError status={null} message={error} onRetry={onRetry} />;
  if (attempts.length === 0) {
    return <ListEmptyState icon={ShieldCheck} title="Nothing turned away" description={emptyDescription} />;
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-2 sm:max-w-xs">
        <FilterSelect
          label="Eligibility"
          value={outcome}
          options={ATTEMPT_ELIGIBILITY_OPTIONS}
          onValueChange={changeOutcome}
        />
      </div>
      {filtered.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-text-secondary">
          No attempts match this filter.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-left text-sm" aria-label={label}>
            <thead className="border-b border-border text-xs uppercase tracking-wide text-text-secondary">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Number</th>
                <th scope="col" className="px-4 py-3 font-medium">Result</th>
                <th scope="col" className="hidden px-4 py-3 font-medium sm:table-cell">Reason</th>
                <th scope="col" className="hidden px-4 py-3 font-medium sm:table-cell">Date</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((attempt) => (
                <tr key={attempt.id} className="border-b border-border align-top last:border-0">
                  <td className="px-4 py-3">
                    <span className="font-medium tabular-nums text-text-primary">{attempt.mobile_masked}</span>
                    <span className="mt-0.5 block text-xs text-text-secondary sm:hidden">
                      {formatDate(attempt.created_at)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge tone={ELIGIBILITY_TONE[attempt.outcome]}>
                      {ELIGIBILITY_LABEL[attempt.outcome]}
                    </StatusBadge>
                    <span className="mt-1 block max-w-56 text-xs text-text-secondary [overflow-wrap:anywhere] sm:hidden">
                      {attempt.reason_label}
                    </span>
                  </td>
                  <td className="hidden px-4 py-3 text-text-secondary sm:table-cell">{attempt.reason_label}</td>
                  <td className="hidden whitespace-nowrap px-4 py-3 text-text-secondary sm:table-cell">
                    {formatDate(attempt.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ListPagination page={page} total={filtered.length} onPageChange={setPage} label={`${label} pages`} />
      <p className="text-xs text-text-secondary">
        Shows the last four digits only. Recorded since this list was introduced
        {total > attempts.length ? `; the latest ${attempts.length} of ${total} are shown` : ""}.
      </p>
    </div>
  );
}
