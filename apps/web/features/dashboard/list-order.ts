// Default ordering for lead and loan-application lists, so finished work never
// fills the first page. Pure and framework-free: the Telecaller, Agent, team
// (manager) and Admin lead lists and the loan lists all use these helpers.

/** New > Assigned > Working > Converted > Closed > Released (agent "expired" last). */
export const LEAD_STATUS_ORDER = ["new", "assigned", "working", "converted", "closed", "released", "expired"] as const;

const LEAD_RANK = new Map<string, number>(LEAD_STATUS_ORDER.map((status, index) => [status, index]));

/** Position of a lead status in the default order; unknown statuses sort last. */
export function leadStatusRank(status: string | null | undefined): number {
  if (!status) return LEAD_STATUS_ORDER.length;
  return LEAD_RANK.get(status) ?? LEAD_STATUS_ORDER.length;
}

/** Earliest first; a missing time sorts after every real one. */
export function compareOptionalTimes(a: string | null | undefined, b: string | null | undefined): number {
  const left = a ? new Date(a).getTime() : Number.NaN;
  const right = b ? new Date(b).getTime() : Number.NaN;
  const leftMissing = Number.isNaN(left);
  const rightMissing = Number.isNaN(right);
  if (leftMissing || rightMissing) return Number(leftMissing) - Number(rightMissing);
  return left - right;
}

/**
 * Compares two leads by status rank, then by next follow-up (soonest first,
 * none last). Ties keep their incoming order because `Array.sort` is stable.
 */
export function compareLeadsByDefaultOrder(
  a: { status: string; followUpAt?: string | null },
  b: { status: string; followUpAt?: string | null },
): number {
  return leadStatusRank(a.status) - leadStatusRank(b.status) || compareOptionalTimes(a.followUpAt, b.followUpAt);
}

/** A copy of `rows` in the default lead order. */
export function sortLeadsByDefaultOrder<T>(
  rows: readonly T[],
  status: (row: T) => string,
  followUpAt: (row: T) => string | null | undefined = () => null,
): T[] {
  return [...rows].sort((a, b) =>
    compareLeadsByDefaultOrder(
      { status: status(a), followUpAt: followUpAt(a) },
      { status: status(b), followUpAt: followUpAt(b) },
    ),
  );
}

/** Loan applications that are finished one way or the other. */
export const FINISHED_LOAN_STATUSES: ReadonlySet<string> = new Set(["closed", "rejected"]);

/** 0 for an active application, 1 for a closed or rejected one. */
export function loanFinishedRank(status: string): number {
  return FINISHED_LOAN_STATUSES.has(status) ? 1 : 0;
}

/** A copy of `rows` with closed and rejected applications moved below active ones, otherwise unchanged. */
export function sinkFinishedLoans<T>(rows: readonly T[], status: (row: T) => string): T[] {
  return [...rows].sort((a, b) => loanFinishedRank(status(a)) - loanFinishedRank(status(b)));
}
