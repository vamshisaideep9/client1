"use client";

import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DashboardHeader, DashboardPage, DashboardPanel, DashboardQuickAction, QuickActionGrid } from "@/features/dashboard/dashboard-ui";
import { ACCESS_LINES, ASSIGNMENTS, assignedLines, type Assignment, type SubAdminAccess } from "@/lib/sub-admin-access";

const icons = {
  team_manager: DASHBOARD_ICONS.team,
  media_sub_admin: DASHBOARD_ICONS.banners,
  account_manager: DASHBOARD_ICONS.payouts,
  relationship_manager: DASHBOARD_ICONS.team,
};

export function ScopedSubAdminHome({ access }: { access: SubAdminAccess }) {
  const assignments = Object.keys(ASSIGNMENTS) as Assignment[];
  if (access.status === "pending") {
    return <DashboardPage><DashboardHeader title="Home" /><DashboardPanel title="Dashboard access pending">
      <p className="text-sm text-text-secondary">Main Admin will activate your account and assign the areas you can use.</p>
    </DashboardPanel></DashboardPage>;
  }
  return <DashboardPage>
    <DashboardHeader title="Home" />
    <QuickActionGrid>
      {assignments.map((assignment) => {
        const lines = assignedLines(access, assignment, "view");
        return lines.length ? <DashboardQuickAction key={assignment} href={ASSIGNMENTS[assignment].path}
          title={ASSIGNMENTS[assignment].label} description={lines.map((line) => ACCESS_LINES[line]).join(" and ")} icon={icons[assignment]} /> : null;
      })}
      <DashboardQuickAction href="/dashboard/attendance" title="My attendance" description="Clock in, review your calendar, and manage requests." icon={DASHBOARD_ICONS.attendance} />
    </QuickActionGrid>
  </DashboardPage>;
}
