"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { DashboardPanel, DashboardTextLink } from "@/features/dashboard/dashboard-ui";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { formatContestDates, formatMetricValue, STATUS_LABEL, STATUS_TONE } from "@/lib/contest-rules";
import { listMyContests, type MyContestSummary } from "@/lib/contests-api";

const SHOWN = 3;

/**
 * Home card for Agents, Telecallers and Employees: the contests open to them
 * now or soon, with their standing. Renders nothing when there are none or the
 * list cannot be read, so it never adds an error to the home page.
 */
export function ContestHomeCard() {
  const [rows, setRows] = React.useState<MyContestSummary[] | null>(null);
  React.useEffect(() => {
    let live = true;
    void listMyContests().then((response) => {
      if (live && response.ok) {
        setRows(response.data.filter((row) => row.status === "live" || row.status === "approved"));
      }
    });
    return () => {
      live = false;
    };
  }, []);

  if (!rows || rows.length === 0) return null;
  return (
    <DashboardPanel
      title="Contests"
      description="Open to you now or starting soon"
      action={<DashboardTextLink href="/dashboard/contests">All contests</DashboardTextLink>}
    >
      <ul className="divide-y divide-border">
        {rows.slice(0, SHOWN).map((contest) => (
          <li key={contest.id}>
            <Link
              href={`/dashboard/contests?contest=${contest.id}`}
              className="flex items-center justify-between gap-3 rounded-lg py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-text-primary">{contest.title}</span>
                  <StatusBadge tone={STATUS_TONE[contest.status]}>{STATUS_LABEL[contest.status]}</StatusBadge>
                </span>
                <span className="block text-sm text-text-secondary">
                  {contest.me
                    ? `${formatMetricValue(contest.metric, contest.me.metric_value)}${contest.me.rank ? ` · rank ${contest.me.rank}` : ""}${contest.me.qualified ? " · targets met" : ""}`
                    : formatContestDates(contest.starts_on, contest.ends_on)}
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </DashboardPanel>
  );
}
