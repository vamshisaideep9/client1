"use client";

import * as React from "react";
import Link from "next/link";
import type { components } from "@contracts/generated/schema";

import { Button } from "@/components/ui/button";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { apiRequest } from "@/lib/api/client";
import { formatDate, formatPaise } from "@/lib/format";
import { ACCESS_LINES } from "@/lib/sub-admin-access";

type Commission = components["schemas"]["ScopedCommission"];
type Divergences = components["schemas"]["PayoutLinkDivergencesRead"];

export function ScopedFinanceOverview() {
  const [commissions, setCommissions] = React.useState<Awaited<ReturnType<typeof apiRequest<Commission[]>>>>();
  const [divergences, setDivergences] = React.useState<Awaited<ReturnType<typeof apiRequest<Divergences>>>>();
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    void apiRequest<Commission[]>("/api/v1/admin/commissions/scoped-summary").then((result) => { if (live) setCommissions(result); });
    void apiRequest<Divergences>("/api/v1/payouts/link-divergences").then((result) => { if (live) setDivergences(result); });
    return () => { live = false; };
  }, [attempt]);

  const retry = () => { setCommissions(undefined); setDivergences(undefined); setAttempt((value) => value + 1); };
  const differences = divergences?.ok ? [
    ...divergences.data.paid_direction.map((item) => ({ ...item, reason: "Settlement link pending" })),
    ...divergences.data.release_direction.map((item) => ({ ...item, reason: "Release link pending" })),
  ] : [];
  return <DashboardPage>
    <DashboardHeader title="Finance overview" actions={<Button asChild variant="outline"><Link href="/dashboard/payouts">Open payouts</Link></Button>} />
    <DashboardPanel title="Recent commissions">
      {!commissions ? <p role="status">Loading commissions…</p> : !commissions.ok ? (
        <div role="alert"><p className="text-sm text-destructive">{commissions.error}</p><Button size="sm" onClick={retry}>Retry</Button></div>
      ) : commissions.data.length ? (
        <ul className="divide-y divide-border">{commissions.data.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span>{ACCESS_LINES[item.business_line]} · {formatDate(item.created_at)}</span>
            <span className="capitalize text-text-secondary">{item.status.replaceAll("_", " ")}</span>
            <span className="font-medium">{formatPaise(item.agreed_amount_paise)}</span>
          </li>
        ))}</ul>
      ) : <p className="text-sm text-text-secondary">No commissions in your assigned lines.</p>}
    </DashboardPanel>
    <DashboardPanel title="Commission payout reconciliation">
      {!divergences ? <p role="status">Loading reconciliation…</p> : !divergences.ok ? (
        <div role="alert"><p className="text-sm text-destructive">{divergences.error}</p><Button size="sm" onClick={retry}>Retry</Button></div>
      ) : differences.length ? <ul className="divide-y divide-border">{differences.map((item) => (
        <li key={item.payout_id + item.reason} className="flex flex-wrap justify-between gap-2 py-2 text-sm"><span>Payout {item.payout_id.slice(0, 8)}</span><span>{item.reason}</span></li>
      ))}</ul> : <p className="text-sm text-text-secondary">No differences in the visible records.</p>}
    </DashboardPanel>
  </DashboardPage>;
}
