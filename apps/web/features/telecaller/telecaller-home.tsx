"use client";

import * as React from "react";
import Link from "next/link";
import { Bell } from "lucide-react";

import { DashboardPageSkeleton } from "@/features/dashboard/dashboard-page-skeleton";
import { FetchError } from "@/features/dashboard/fetch-error";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
  DashboardTextLink,
  MetricCard,
  MetricGrid,
} from "@/features/dashboard/dashboard-ui";
import { ContestHomeCard } from "@/features/contests/contest-home-card";
import { AttendanceTodayCard } from "@/features/attendance/staff-attendance-view";
import { useLine } from "@/features/dashboard/line-provider";
import { useMe } from "@/features/dashboard/me-provider";
import { ProductWorkPanels, SpecialtyChip } from "@/features/dashboard/product-work-panels";
import { getNotifications, type AppNotification } from "@/lib/notifications";
import { getTelecallerHome, type TelecallerHome as TelecallerHomeData } from "@/lib/telecaller-api";

import { formatAppliedAt } from "./telecaller-requests";

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  assigned: "Assigned",
  working: "Working",
  converted: "Converted",
  closed: "Closed",
  released: "Released",
};

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "-"
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

type Status = "loading" | "ready" | "error";

/** "Hi, Asha" once the profile is known; "Hi there" until then or without a name. */
export function greeting(firstName: string | null | undefined): string {
  const name = firstName?.trim();
  return name ? `Hi, ${name}` : "Hi there";
}

// Telecaller landing page: follow-ups due today, assigned-lead counts, and a
// notifications preview. Mirrors AdminHome's minimal-landing posture — this
// slice ships the lead-follow-up flow only.
export function TelecallerHome() {
  const { activeLine } = useLine();
  const { me } = useMe();
  const [home, setHome] = React.useState<TelecallerHomeData | null>(null);
  const [notifications, setNotifications] = React.useState<AppNotification[]>([]);
  const [status, setStatus] = React.useState<Status>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  const retry = React.useCallback(() => {
    setStatus("loading");
    setError(null);
    setErrorStatus(null);
    setReloadKey((k) => k + 1);
  }, []);

  React.useEffect(() => {
    let active = true;
    const run = async () => {
      const [homeRes, notifRes] = await Promise.all([getTelecallerHome(), getNotifications()]);
      if (!active) return;
      if (!homeRes.ok) {
        setError(homeRes.error);
        setErrorStatus(homeRes.status);
        setStatus("error");
        return;
      }
      setHome(homeRes.data);
      setNotifications(notifRes.ok ? notifRes.data.slice(0, 3) : []);
      setStatus("ready");
    };
    void run();
    return () => {
      active = false;
    };
  }, [activeLine, reloadKey]);

  if (status === "loading") {
    return <DashboardPageSkeleton overview />;
  }

  if (status === "error" || !home) {
    return (
      <DashboardPage>
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      </DashboardPage>
    );
  }

  const assignedTotal = Object.values(home.counts_by_status).reduce((sum, count) => sum + count, 0);

  return (
    <DashboardPage>
      <DashboardHeader
        title={greeting(me?.firstName)}
        description="Welcome to your workspace."
        meta={home.specialty ? <SpecialtyChip specialty={home.specialty} /> : undefined}
        actions={<DashboardTextLink href="/dashboard/leads">Open lead queue</DashboardTextLink>}
      />

      <MetricGrid>
        <MetricCard
          label="Follow-ups due"
          value={home.follow_ups_due.length}
          icon={DASHBOARD_ICONS.leads}
          href="/dashboard/leads?followUp=due"
          attention={home.follow_ups_due.length > 0}
        />
        <MetricCard
          label="Assigned leads"
          value={assignedTotal}
          icon={DASHBOARD_ICONS.leads}
          href="/dashboard/leads"
        />
        <MetricCard
          label="Working"
          value={home.counts_by_status.working ?? 0}
          icon={DASHBOARD_ICONS.leads}
          href="/dashboard/leads"
        />
        <MetricCard
          label="Converted"
          value={home.counts_by_status.converted ?? 0}
          icon={DASHBOARD_ICONS.leads}
          href="/dashboard/leads"
        />
      </MetricGrid>

      {activeLine === "loans" ? (
        <ProductWorkPanels kind="leads" specialty={home.specialty} counts={home.product_counts} />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <DashboardPanel
          title="Follow-ups due"
          description="Callbacks requiring attention now"
          action={<DashboardTextLink href="/dashboard/leads">View all leads</DashboardTextLink>}
        >
          {home.follow_ups_due.length === 0 ? (
            <p className="text-sm text-text-secondary">Nothing due right now.</p>
          ) : (
            <div className="space-y-3">
              {/* Five rows tall; the rest scroll inside the panel. Focusable so
                  keyboard users can scroll it too. */}
              <div
                className="max-h-[17.5rem] overflow-y-auto rounded-xl border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                tabIndex={0}
                role="region"
                aria-label={`Follow-ups due, ${home.follow_ups_due.length} leads`}
              >
                <table className="w-full text-left text-sm">
                  <thead className="sticky top-0 z-10 bg-card text-xs uppercase tracking-wide text-text-secondary shadow-[inset_0_-1px_0_var(--border)]">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">Lead</th>
                      <th scope="col" className="px-3 py-2 font-medium">Request</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Due</th>
                    </tr>
                  </thead>
                  <tbody>
                    {home.follow_ups_due.map((item) => (
                      <tr key={item.lead_uuid} className="h-12 border-b border-border last:border-0">
                        <td className="max-w-0 px-3 py-2">
                          <Link
                            href={`/dashboard/leads/${item.lead_uuid}`}
                            className="block truncate font-medium text-brand-link underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {item.name ?? item.mobile}
                          </Link>
                        </td>
                        <td className="max-w-0 px-3 py-2 text-text-secondary">
                          {item.latest_request ? (
                            <span className="block truncate" title={`${item.latest_request.title} · applied ${formatAppliedAt(item.latest_request.applied_at)}`}>
                              {item.latest_request.title}
                            </span>
                          ) : (
                            <span aria-label="No request">-</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right text-text-secondary">
                          <time dateTime={item.follow_up_at}>{formatDateTime(item.follow_up_at)}</time>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <DashboardTextLink href="/dashboard/leads?followUp=due">View all follow-ups</DashboardTextLink>
            </div>
          )}
        </DashboardPanel>

        <DashboardPanel title="Pipeline distribution" description="Assigned leads by current status">
          {Object.keys(home.counts_by_status).length === 0 ? (
            <p className="text-sm text-text-secondary">No leads assigned yet.</p>
          ) : (
            <ul className="space-y-2">
              {Object.entries(home.counts_by_status).map(([key, count]) => (
                <li key={key} className="flex items-center justify-between text-sm">
                  <span className="text-text-secondary">{STATUS_LABEL[key] ?? key}</span>
                  <span className="font-medium text-text-primary">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </DashboardPanel>
      </div>

      <ContestHomeCard />
      <AttendanceTodayCard />

      <DashboardPanel
        title="Notifications"
        description="Recent assignment and workflow updates"
        action={<DashboardTextLink href="/dashboard/notifications">View all</DashboardTextLink>}
      >
        {notifications.length === 0 ? (
          <p className="text-sm text-text-secondary">No notifications yet.</p>
        ) : (
          <ul className="space-y-3">
            {notifications.map((n) => (
              <li key={n.id} className="flex items-start gap-2 text-sm">
                <Bell className="mt-0.5 h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
                <div>
                  <p className="font-medium text-text-primary">{n.title}</p>
                  <p className="text-text-secondary">{n.body}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </DashboardPanel>
    </DashboardPage>
  );
}
