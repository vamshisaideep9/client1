"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, ChevronRight, Circle } from "lucide-react";

import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import {
  DashboardBackLink,
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import {
  EXCLUSION_LABEL,
  formatContestDates,
  formatMetricValue,
  METRIC_LABEL,
  prizeStatus,
  progressRows,
  STATUS_LABEL,
  STATUS_TONE,
} from "@/lib/contest-rules";
import {
  getMyContest,
  isContestId,
  listMyContests,
  type ContestCriteria,
  type ContestProgress,
  type MyContestDetail,
  type MyContestSummary,
} from "@/lib/contests-api";
import { formatPaise } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ContestRulesPanel } from "./contest-rules-panel";

const GROUPS: { key: string; title: string; statuses: MyContestSummary["status"][] }[] = [
  { key: "live", title: "Live now", statuses: ["live"] },
  { key: "upcoming", title: "Starting soon", statuses: ["approved"] },
  { key: "ended", title: "Ended", statuses: ["ended", "finalized"] },
];

function prizeText(contest: MyContestSummary): string {
  if (contest.audience === "team") {
    const parts = [];
    if (contest.my_role === "team_manager" && contest.manager_item_prize)
      parts.push(`${contest.manager_item_prize.label} for you as manager`);
    if (contest.member_item_prize) parts.push(`${contest.member_item_prize.label} per member`);
    if (contest.my_role === "team_manager" && contest.manager_prize_paise)
      parts.push(`${formatPaise(contest.manager_prize_paise)} for you as manager`);
    if (contest.member_prize_paise) parts.push(`${formatPaise(contest.member_prize_paise)} per member`);
    return parts.join(" · ") || "Team prize";
  }
  if (contest.item_prize) return `${contest.item_prize.label} per winner`;
  return contest.prize_paise ? `${formatPaise(contest.prize_paise)} per winner` : "";
}

function standingText(contest: MyContestSummary): string {
  if (!contest.eligible) return "You are not eligible for this one";
  if (!contest.me) return "Starts on the first day";
  const who = contest.audience === "team" ? "Your team" : "You";
  const rank = contest.me.rank ? `rank ${contest.me.rank} of ${contest.participants ?? "—"}` : "not ranked yet";
  return `${who}: ${formatMetricValue(contest.metric, contest.me.metric_value)} · ${rank}`;
}

export function ProgressBars({
  criteria,
  progress,
}: {
  criteria: ContestCriteria;
  progress: ContestProgress | null | undefined;
}) {
  const rows = progressRows(criteria, progress ?? {});
  if (rows.length === 0) return null;
  return (
    <ul className="space-y-3" aria-label="Progress against each target">
      {rows.map((row) => (
        <li key={row.key} className="space-y-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
            <span className="flex items-center gap-1.5 font-medium text-text-primary">
              {row.met ? (
                <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
              ) : (
                <Circle className="h-4 w-4 text-text-secondary" aria-hidden />
              )}
              {row.label}
              <span className="sr-only">{row.met ? " (met)" : " (not met yet)"}</span>
            </span>
            <span className="tabular-nums text-text-secondary">
              <span className="font-medium text-text-primary">{row.achieved}</span> · {row.target}
            </span>
          </div>
          <div
            className="h-2 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label={row.label}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(row.share * 100)}
          >
            <div
              className={cn("h-full rounded-full", row.met ? "bg-success" : "bg-brand-link")}
              style={{ width: `${Math.round(row.share * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function ContestCard({ contest }: { contest: MyContestSummary }) {
  return (
    <Link
      href={`/dashboard/contests?contest=${encodeURIComponent(contest.id)}`}
      className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4 shadow-sm outline-none transition-colors hover:border-brand-blue/50 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="min-w-0 space-y-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-text-primary group-hover:text-brand-link">{contest.title}</span>
          <StatusBadge tone={STATUS_TONE[contest.status]}>{STATUS_LABEL[contest.status]}</StatusBadge>
        </span>
        <span className="block text-sm text-text-secondary">
          {formatContestDates(contest.starts_on, contest.ends_on, contest.start_time, contest.end_time)} · {prizeText(contest)}
        </span>
        <span className="block text-sm text-text-primary">{standingText(contest)}</span>
      </span>
      <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-text-secondary" aria-hidden />
    </Link>
  );
}

function ContestList() {
  const [rows, setRows] = React.useState<MyContestSummary[] | null>(null);
  const [error, setError] = React.useState<{ status: number | null; message: string } | null>(null);
  const load = React.useCallback(async () => {
    const response = await listMyContests();
    if (response.ok) {
      setRows(response.data);
      setError(null);
    } else {
      setError({ status: response.status, message: response.error });
    }
  }, []);
  React.useEffect(() => {
    void load();
  }, [load]);

  if (error) return <FetchError status={error.status} message={error.message} onRetry={() => void load()} />;
  if (rows === null) return <ListLoadingState rows={3} />;
  if (rows.length === 0) {
    return (
      <ListEmptyState
        icon={DASHBOARD_ICONS.contests}
        title="No contests for you right now"
        description="When a contest opens for your role, it shows up here with its rules and your progress."
      />
    );
  }
  return (
    <div className="space-y-6">
      {GROUPS.map((group) => {
        const items = rows.filter((row) => group.statuses.includes(row.status));
        if (items.length === 0) return null;
        return (
          <section key={group.key} aria-labelledby={`contest-group-${group.key}`} className="space-y-3">
            <h2 id={`contest-group-${group.key}`} className="font-heading text-base font-semibold text-brand-heading">
              {group.title}
            </h2>
            <div className="grid gap-3 lg:grid-cols-2">
              {items.map((contest) => (
                <ContestCard key={contest.id} contest={contest} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ResultBanner({ detail }: { detail: MyContestDetail }) {
  const me = detail.me;
  if (detail.status !== "finalized" || !me) return null;
  if (me.won && ((me.prize_paise ?? 0) > 0 || me.item_prize)) {
    return (
      <p role="status" className="rounded-xl border border-success/40 bg-success/10 p-4 text-sm text-text-primary">
        <span className="font-semibold">You won {me.item_prize?.label ?? formatPaise(me.prize_paise ?? 0)}.</span>{" "}
        {prizeStatus(me.payment_status ?? "unpaid", Boolean(me.item_prize))}
        {detail.audience === "agent" && !me.item_prize ? " · paid to your saved payout details after a second Admin approves it." : ""}
      </p>
    );
  }
  if (me.won) {
    return <p role="status" className="rounded-xl border border-success/40 bg-success/10 p-4 text-sm">Your team won.</p>;
  }
  return (
    <p className="rounded-xl border border-border bg-muted/40 p-4 text-sm text-text-secondary">
      {me.excluded_reason ? `${EXCLUSION_LABEL[me.excluded_reason] ?? "No prize"}.` : "Not a winner this time."}
    </p>
  );
}

function ContestDetailView({ id }: { id: string }) {
  const router = useRouter();
  const [detail, setDetail] = React.useState<MyContestDetail | null>(null);
  const [error, setError] = React.useState<{ status: number | null; message: string } | null>(null);
  const load = React.useCallback(async () => {
    const response = await getMyContest(id);
    if (response.ok) {
      setDetail(response.data);
      setError(null);
    } else if (response.status === 404) {
      router.replace("/dashboard/contests");
    } else {
      setError({ status: response.status, message: response.error });
    }
  }, [id, router]);
  React.useEffect(() => {
    void load();
  }, [load]);

  const header = (
    <DashboardHeader
      title={detail?.title ?? "Contest"}
      description={
        detail
          ? `${STATUS_LABEL[detail.status]} · ${formatContestDates(detail.starts_on, detail.ends_on, detail.start_time, detail.end_time)} · ${prizeText(detail)}`
          : "Loading the contest."
      }
      actions={<DashboardBackLink href="/dashboard/contests">All contests</DashboardBackLink>}
    />
  );
  if (error) {
    return (
      <>
        {header}
        <FetchError status={error.status} message={error.message} onRetry={() => void load()} />
      </>
    );
  }
  if (!detail) {
    return (
      <>
        {header}
        <ListLoadingState rows={4} />
      </>
    );
  }
  const team = detail.team;
  const metric = METRIC_LABEL[detail.metric];

  return (
    <>
    {header}
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-4 max-xl:order-1 xl:col-start-1">
        <ResultBanner detail={detail} />
        {!detail.eligible ? (
          <p className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm text-text-primary">
            You are not eligible for this contest (see who can take part below). You can still follow it.
          </p>
        ) : null}
        <DashboardPanel
          title={detail.audience === "team" ? `${team?.team_name ?? "Your team"}'s progress` : "Your progress"}
          description={
            detail.me
              ? `${metric}: ${formatMetricValue(detail.metric, detail.me.metric_value)}${detail.me.rank ? ` · rank ${detail.me.rank} of ${detail.participants}` : ""}`
              : "Progress appears once the contest starts."
          }
        >
          {detail.me ? (
            <ProgressBars criteria={detail.criteria} progress={detail.me.progress} />
          ) : (
            <p className="text-sm text-text-secondary">
              Starts {formatContestDates(detail.starts_on, detail.starts_on)} at {detail.start_time?.slice(0, 5) ?? "00:00"} IST.
            </p>
          )}
          {team && team.members.length > 0 ? (
            <div className="mt-5 space-y-2">
              <h3 className="text-sm font-semibold text-text-primary">
                {detail.my_role === "team_manager" ? "Members" : "Your contribution"}
              </h3>
              <ul className="divide-y divide-border rounded-xl border border-border">
                {team.members.map((member) => (
                  <li key={member.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                    <span className="font-medium text-text-primary">
                      {member.name}
                      {member.is_me ? <span className="ml-1 text-xs text-text-secondary">(you)</span> : null}
                    </span>
                    <span className="flex items-center gap-2 tabular-nums">
                      {formatMetricValue(detail.metric, member.metric_value)}
                      {member.meets_member_minimum === null ? null : (
                        <StatusBadge tone={member.meets_member_minimum ? "success" : "neutral"}>
                          {member.meets_member_minimum ? "Above the minimum" : "Below the minimum"}
                        </StatusBadge>
                      )}
                      {member.item_prize && member.payment_status ? (
                        <StatusBadge tone={member.payment_status === "paid" ? "success" : "warning"}>
                          {member.item_prize.label} · {prizeStatus(member.payment_status, true)}
                        </StatusBadge>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </DashboardPanel>
      </div>
      {/* Phones read progress, then the leaderboard, then the rules. */}
      <div className="min-w-0 max-xl:order-3 xl:col-start-1">
        <DashboardPanel title="Rules">
          <ContestRulesPanel contest={detail} />
        </DashboardPanel>
      </div>
      <DashboardPanel
        className="max-xl:order-2 xl:col-start-2 xl:row-span-2 xl:row-start-1"
        title="Leaderboard"
        description={detail.computed_at ? (detail.status === "live" ? "Live standings" : "Final standings") : undefined}
      >
        {detail.leaderboard.length === 0 ? (
          <p className="text-sm text-text-secondary">The leaderboard opens on the first day.</p>
        ) : (
          <ol className="space-y-1" aria-label="Leaderboard">
            {detail.leaderboard.map((entry, index) => (
              <li
                key={`${entry.rank}-${index}`}
                className={cn(
                  "flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm",
                  entry.is_me ? "bg-brand-cta-tint font-medium" : "",
                )}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span className="w-6 shrink-0 text-right tabular-nums text-text-secondary">{entry.rank ?? "—"}</span>
                  <span className="truncate text-text-primary">
                    {entry.is_me ? "You" : (entry.name ?? "Participant")}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 tabular-nums">
                  {formatMetricValue(detail.metric, entry.achieved)}
                  {entry.qualified ? <CheckCircle2 className="h-4 w-4 text-success" aria-label="Met every target" /> : null}
                </span>
              </li>
            ))}
          </ol>
        )}
      </DashboardPanel>
    </div>
    </>
  );
}

export function MyContestsView() {
  const params = useSearchParams();
  const linked = params.get("contest");
  // Security review: only a canonical UUID may reach the API path; anything
  // else (`..`, slashes, query text) shows the list instead.
  const id = isContestId(linked) ? linked : null;
  return (
    <DashboardPage>
      {id ? (
        <ContestDetailView id={id} />
      ) : (
        <>
          <DashboardHeader
            title="Contests"
            description="Contests you can take part in, their rules and how you are doing."
          />
          <ContestList />
        </>
      )}
    </DashboardPage>
  );
}
