import * as React from "react";

import { getReport, type ReportKind } from "@/lib/reports-api";

import type { ReportFilterInput, ReportResponse } from "./use-report";

// The API caps a report page at 500 rows. Journey charts read every bucket
// of the filtered period in time order; the Agents chart only needs the top
// ten by leads (the summary and line totals cover everyone).
export const CHART_LIMIT = 500;
export const TOP_AGENTS = 10;

/**
 * A second, chart-only read of the same report. It shares the table's
 * filters but not its sort or page, so the chart always shows the whole
 * filtered period. A request id drops responses a newer filter superseded.
 */
export function useReportChart(kind: ReportKind, filters: ReportFilterInput) {
  const [data, setData] = React.useState<ReportResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const agentKey = (filters.agentProfileUuids ?? []).join(",");
  const detailKey = JSON.stringify(filters.detail ?? {});
  const requestIdRef = React.useRef(0);

  const load = React.useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    const agents = kind === "agents";
    const res = await getReport(kind, {
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      bucket: filters.bucket,
      businessLine: filters.businessLine,
      agentProfileUuids: filters.agentProfileUuids,
      detail: filters.detail,
      sortBy: agents ? "leads_total" : "bucket_start",
      sortDir: agents ? "desc" : "asc",
      limit: agents ? TOP_AGENTS : CHART_LIMIT,
      offset: 0,
    });
    if (requestId !== requestIdRef.current) return;
    if (res.ok) {
      setData(res.data);
    } else {
      setError(res.error);
    }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, filters.dateFrom, filters.dateTo, filters.bucket, filters.businessLine, agentKey, detailKey]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, error, reload: load };
}
