"use client";

import * as React from "react";

import type { ApiResponse } from "@/lib/api/client";

import type { EligibilitySummary, IntakeAttempt, IntakeAttemptList } from "./eligibility";

/**
 * The eligibility summary and the "Not accepted" attempts for one panel
 * (CS-024). The loaders are module-level API functions, so they are stable
 * across renders. A failure here never blocks the page's own list: each part
 * reports its own error.
 */
export function useEligibility(
  loadSummary: () => Promise<ApiResponse<EligibilitySummary>>,
  loadAttempts: () => Promise<ApiResponse<IntakeAttemptList>>,
) {
  const [summary, setSummary] = React.useState<EligibilitySummary | null>(null);
  const [attempts, setAttempts] = React.useState<IntakeAttempt[]>([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [summaryError, setSummaryError] = React.useState<string | null>(null);
  const [attemptsError, setAttemptsError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setSummaryError(null);
    setAttemptsError(null);
    const [summaryRes, attemptsRes] = await Promise.all([loadSummary(), loadAttempts()]);
    if (summaryRes.ok) setSummary(summaryRes.data);
    else setSummaryError(summaryRes.error);
    if (attemptsRes.ok) {
      setAttempts(attemptsRes.data.attempts);
      setTotal(attemptsRes.data.total);
    } else {
      setAttemptsError(attemptsRes.error);
    }
    setLoading(false);
  }, [loadSummary, loadAttempts]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return { summary, attempts, total, loading, summaryError, attemptsError, reload: load };
}
