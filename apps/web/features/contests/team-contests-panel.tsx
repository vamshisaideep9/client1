"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import {
  formatContestDates,
  formatMetricValue,
  METRIC_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
} from "@/lib/contest-rules";
import {
  getMyContest,
  listMyContests,
  type MyContestDetail,
  type MyContestSummary,
} from "@/lib/contests-api";
import { formatPaise } from "@/lib/format";

import { ProgressBars } from "./my-contests-view";

/**
 * A managing Sub Admin's team contests (CS-027), inside My team: the team's
 * standing per contest and, on request, its progress against each target and
 * every member's contribution. Hidden when the manager has none.
 */
export function TeamContestsPanel({ teamName }: { teamName: string }) {
  const [rows, setRows] = React.useState<MyContestSummary[] | null>(null);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<MyContestDetail | null>(null);

  React.useEffect(() => {
    let live = true;
    void listMyContests().then((response) => {
      if (live && response.ok) setRows(response.data.filter((row) => row.my_role === "team_manager"));
    });
    return () => {
      live = false;
    };
  }, []);

  React.useEffect(() => {
    if (!openId) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetail(null);
    void getMyContest(openId).then((response) => {
      if (live && response.ok) setDetail(response.data);
    });
    return () => {
      live = false;
    };
  }, [openId]);

  if (!rows || rows.length === 0) return null;
  return (
    <DashboardPanel title="Team contests" description={`Contests your teams take part in (${teamName} shown first).`}>
      <ul className="space-y-3">
        {rows.map((contest) => {
          const open = openId === contest.id;
          return (
            <li key={contest.id} className="rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-text-primary">{contest.title}</span>
                    <StatusBadge tone={STATUS_TONE[contest.status]}>{STATUS_LABEL[contest.status]}</StatusBadge>
                  </p>
                  <p className="text-sm text-text-secondary">
                    {formatContestDates(contest.starts_on, contest.ends_on)}
                    {contest.manager_prize_paise ? ` · ${formatPaise(contest.manager_prize_paise)} manager prize` : ""}
                  </p>
                  <p className="text-sm text-text-primary">
                    {contest.me
                      ? `${METRIC_LABEL[contest.metric]}: ${formatMetricValue(contest.metric, contest.me.metric_value)}${contest.me.rank ? ` · rank ${contest.me.rank} of ${contest.participants}` : ""}${contest.me.qualified ? " · targets met" : ""}`
                      : "Starts on the first day"}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  aria-expanded={open}
                  aria-controls={`team-contest-${contest.id}`}
                  onClick={() => setOpenId(open ? null : contest.id)}
                >
                  {open ? "Hide progress" : "Show progress"}
                </Button>
              </div>
              {open ? (
                <div id={`team-contest-${contest.id}`} className="mt-4 space-y-4">
                  {detail?.id !== contest.id ? (
                    <ListLoadingState rows={2} />
                  ) : (
                    <>
                      {detail.me ? <ProgressBars criteria={detail.criteria} progress={detail.me.progress} /> : null}
                      {detail.team?.members.length ? (
                        <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Member contributions">
                          {detail.team.members.map((member) => (
                            <li key={member.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                              <span className="font-medium text-text-primary">{member.name}</span>
                              <span className="flex items-center gap-2 tabular-nums">
                                {formatMetricValue(detail.metric, member.metric_value)}
                                {member.meets_member_minimum === null ? null : (
                                  <StatusBadge tone={member.meets_member_minimum ? "success" : "neutral"}>
                                    {member.meets_member_minimum ? "Above the minimum" : "Below the minimum"}
                                  </StatusBadge>
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </DashboardPanel>
  );
}
