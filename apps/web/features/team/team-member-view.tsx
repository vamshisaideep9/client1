"use client";

import * as React from "react";

import {
  AnalyticsLoading,
  AnalyticsReport,
} from "@/features/analytics/staff-analytics-view";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import {
  DashboardBackLink,
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { resolveRangePreset, type DateRangeValue } from "@/lib/analytics-range";
import {
  getMemberAnalytics,
  getMyTeams,
  personName,
  teamLabel,
  type StaffTeam,
  type TeamAnalyticsFilters,
} from "@/lib/staff-teams-api";

import { TeamAnalyticsFilterBar, useHiddenFilters, useTeamAnalyticsRequest } from "./team-analytics-filter-bar";
import { TeamWorkList } from "./team-work-list";
import { useLoad } from "./use-load";

function MemberAnalytics({ team, memberId }: { team: StaffTeam; memberId: string }) {
  const [range, setRange] = React.useState<DateRangeValue>(() =>
    resolveRangePreset("last_month", new Date()),
  );
  const [filters, setFilters] = React.useState<TeamAnalyticsFilters>({});
  const [hidden, reportHidden] = useHiddenFilters();
  const { context, sent } = useTeamAnalyticsRequest(team, filters, hidden);
  const { state, retry } = useLoad(
    () => getMemberAnalytics(team.id, memberId, range, sent),
    [team.id, memberId, range, sent],
  );
  const data = state.status === "ready" ? state.data : null;
  React.useEffect(() => reportHidden(data?.hidden_filters), [data, reportHidden]);
  return (
    <section aria-label="Analytics" className="space-y-4">
      <h2 className="font-heading text-lg font-semibold text-brand-heading">Analytics</h2>
      <TeamAnalyticsFilterBar
        team={team}
        range={range}
        onRangeChange={setRange}
        filters={filters}
        onFiltersChange={setFilters}
        withMembers={false}
        context={context}
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : state.status === "loading" ? (
        <AnalyticsLoading />
      ) : (
        <AnalyticsReport data={state.data} />
      )}
    </section>
  );
}

export function TeamMemberView({ teamId, memberId }: { teamId: string; memberId: string }) {
  const { state, retry } = useLoad(getMyTeams, []);
  const team = state.status === "ready" ? state.data.teams.find((t) => t.id === teamId) : undefined;
  const member = team?.members.find((person) => person.staff_profile_uuid === memberId);

  return (
    <DashboardPage>
      <DashboardBackLink href="/dashboard/team">My team</DashboardBackLink>
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : state.status === "loading" ? (
        <ListLoadingState rows={4} />
      ) : !team || !member ? (
        <ListEmptyState
          icon={DASHBOARD_ICONS.team}
          title="Not in your team"
          description="This person is not a member of a team you manage."
        />
      ) : (
        <>
          <DashboardHeader
            title={personName(member)}
            description={`${team.name} · ${teamLabel(team)} · ${member.staff_code}`}
          />
          <div className="space-y-6">
            <DashboardPanel
              title={team.member_role === "telecaller" ? "Leads" : "Field tasks"}
              description={`${personName(member)}'s ${team.member_role === "telecaller" ? "leads" : "tasks"}, most recently updated first. Open one to read and add notes, change it, or move it to a teammate.`}
            >
              <TeamWorkList team={team} memberId={member.staff_profile_uuid} />
            </DashboardPanel>
            <MemberAnalytics team={team} memberId={member.staff_profile_uuid} />
          </div>
        </>
      )}
    </DashboardPage>
  );
}
