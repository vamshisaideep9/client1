"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMetric } from "@/features/analytics/analytics-format";
import {
  AnalyticsLoading,
  AnalyticsReport,
} from "@/features/analytics/staff-analytics-view";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import {
  formatRangeLabel,
  resolveRangePreset,
  type DateRangeValue,
} from "@/lib/analytics-range";
import {
  getMyTeams,
  getTeamOverview,
  personName,
  teamLabel,
  type StaffTeam,
  type TeamAnalyticsFilters,
  type TeamOverview,
} from "@/lib/staff-teams-api";

import { TeamAnalyticsFilterBar } from "./team-analytics-filter-bar";
import { TeamWorkList } from "./team-work-list";
import { useLoad } from "./use-load";

function MembersTable({ team, overview }: { team: StaffTeam; overview: TeamOverview }) {
  const columns = overview.members[0]?.kpis ?? overview.totals;
  const href = (memberId: string) => `/dashboard/team/${team.id}/members/${memberId}`;

  if (overview.members.length === 0) {
    return (
      <ListEmptyState
        icon={DASHBOARD_ICONS.team}
        title="No members yet"
        description="The Main Admin adds people to your team from the Teams page."
      />
    );
  }

  return (
    <>
      {/* Phones: one card per member. */}
      <ul className="space-y-3 md:hidden" aria-label="Team members">
        {overview.members.map(({ member, kpis }) => (
          <li key={member.staff_profile_uuid}>
            <Link
              href={href(member.staff_profile_uuid)}
              className="block rounded-xl border border-border bg-card p-4 shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium text-text-primary">{personName(member)}</span>
                <ChevronRight aria-hidden="true" className="size-4 text-text-secondary" />
              </span>
              {member.status !== "active" ? (
                <Badge variant="outline" className="mt-1">
                  Inactive
                </Badge>
              ) : null}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {kpis.map((kpi) => (
                  <div key={kpi.key} className="min-w-0">
                    <dt className="truncate text-xs text-text-secondary">{kpi.label}</dt>
                    <dd className="tabular-nums text-text-primary">{formatMetric(kpi.value, kpi.unit)}</dd>
                  </div>
                ))}
              </dl>
            </Link>
          </li>
        ))}
      </ul>

      {/* Tablet and up: a comparison table. */}
      <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{team.name}: figures per member</caption>
          <thead className="bg-muted text-xs text-text-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                Member
              </th>
              {columns.map((kpi) => (
                <th key={kpi.key} scope="col" className="px-3 py-2 text-right font-medium">
                  {kpi.label}
                </th>
              ))}
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">Open</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {overview.members.map(({ member, kpis }) => (
              <tr key={member.staff_profile_uuid} className="hover:bg-background">
                <th scope="row" className="px-3 py-2 font-medium text-text-primary">
                  {personName(member)}
                  {member.status !== "active" ? (
                    <Badge variant="outline" className="ml-2">
                      Inactive
                    </Badge>
                  ) : null}
                </th>
                {kpis.map((kpi) => (
                  <td key={kpi.key} className="px-3 py-2 text-right tabular-nums">
                    {formatMetric(kpi.value, kpi.unit)}
                  </td>
                ))}
                <td className="px-3 py-2 text-right">
                  <Link
                    href={href(member.staff_profile_uuid)}
                    className="inline-flex min-h-11 items-center gap-1 text-brand-link outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    View<span className="sr-only"> {personName(member)}</span>
                    <ChevronRight aria-hidden="true" className="size-4" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function TeamOverviewPanel({ team }: { team: StaffTeam }) {
  const [range, setRange] = React.useState<DateRangeValue>(() =>
    resolveRangePreset("last_month", new Date()),
  );
  const [filters, setFilters] = React.useState<TeamAnalyticsFilters>({});
  const { state, retry } = useLoad(
    () => getTeamOverview(team.id, range, filters),
    [team.id, range, filters],
  );
  const data = state.status === "ready" ? state.data : null;

  return (
    <div className="space-y-5">
      <TeamAnalyticsFilterBar
        team={team}
        range={range}
        onRangeChange={setRange}
        filters={filters}
        onFiltersChange={setFilters}
        withMembers
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : !data ? (
        <AnalyticsLoading />
      ) : (
        <>
          {data.report ? (
            <AnalyticsReport data={data.report} />
          ) : (
            <ListEmptyState icon={DASHBOARD_ICONS.team} title="No members to show" />
          )}
          <DashboardPanel
            title="Members"
            description={`Each member's figures for ${formatRangeLabel({ dateFrom: data.date_from, dateTo: data.date_to })}. Open a member to see their work.`}
          >
            <MembersTable team={team} overview={data} />
          </DashboardPanel>
        </>
      )}
    </div>
  );
}

export function MyTeamView() {
  const { state, retry } = useLoad(getMyTeams, []);
  const teams = state.status === "ready" ? state.data.teams : null;
  const [selected, setSelected] = React.useState<string | null>(null);
  const [section, setSection] = React.useState<"overview" | "work">("overview");
  const team = teams?.find((candidate) => candidate.id === selected) ?? teams?.[0] ?? null;

  return (
    <DashboardPage>
      <DashboardHeader
        title="My team"
        description="How your team is doing, and the work each member holds. New leads and tasks are still shared across the whole line."
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : teams === null ? (
        <ListLoadingState rows={4} />
      ) : !team ? (
        <ListEmptyState
          icon={DASHBOARD_ICONS.team}
          title="You don't manage a team yet"
          description="The Main Admin can make you the manager of a Telecaller or Employee team."
        />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {teams.length > 1 ? (
              <Select value={team.id} onValueChange={setSelected}>
                <SelectTrigger className="w-full sm:w-72" aria-label="Team">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {teams.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.name} · {teamLabel(candidate)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <h2 className="font-heading text-lg font-semibold text-brand-heading">{team.name}</h2>
            )}
            <p className="text-sm text-text-secondary">
              {teamLabel(team)} · {team.members.length}{" "}
              {team.members.length === 1 ? "member" : "members"}
            </p>
          </div>
          <Tabs value={section} onValueChange={(value) => setSection(value as "overview" | "work")}>
            <TabsList aria-label="Team sections">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="work">Work</TabsTrigger>
            </TabsList>
            <TabsContent value="overview" className="mt-5">
              <TeamOverviewPanel key={team.id} team={team} />
            </TabsContent>
            <TabsContent value="work" className="mt-5">
              <TeamWorkList key={team.id} team={team} />
            </TabsContent>
          </Tabs>
        </div>
      )}
    </DashboardPage>
  );
}
