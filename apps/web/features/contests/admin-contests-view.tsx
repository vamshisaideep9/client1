"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Inbox } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MoneyPayoutDialog } from "@/features/admin/money-payout-dialog";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { FetchError } from "@/features/dashboard/fetch-error";
import { EMPTY_FILTERS, FilterBar, type FilterBarValue } from "@/features/dashboard/filter-bar";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { buildCommissionPayoutPayload } from "@/lib/commission-payout-form";
import {
  AUDIENCE_LABEL,
  EXCLUSION_LABEL,
  formatContestDates,
  formatMetricValue,
  LINE_LABEL,
  PAYMENT_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
} from "@/lib/contest-rules";
import {
  approveContest,
  cancelContest,
  finalizeContest,
  getStandings,
  listContests,
  markPrizePaid,
  recalculateContest,
  rejectContest,
  requestPrizePayout,
  type Contest,
  type ContestStandings,
  type StandingRow,
} from "@/lib/contests-api";
import { formatPaise } from "@/lib/format";

import { ContestRulesPanel } from "./contest-rules-panel";
import { audienceText, filterContests, ReasonDialog } from "./sub-admin-contests-view";

type Tab = "review" | "winners" | "running" | "done";

const TAB_STATUSES: Record<Tab, readonly Contest["status"][]> = {
  review: ["pending_approval"],
  winners: ["ended"],
  running: ["approved", "live"],
  done: ["finalized", "cancelled", "rejected", "draft"],
};

const TAB_TITLE: Record<Tab, string> = {
  review: "Waiting for your approval",
  winners: "Ended, waiting for winners to be confirmed",
  running: "Approved and live",
  done: "Finished, cancelled or sent back",
};

const AUDIENCE_OPTIONS = (Object.keys(AUDIENCE_LABEL) as Contest["audience"][]).map((value) => ({
  value,
  label: AUDIENCE_LABEL[value],
}));

export function AdminContestsView() {
  const params = useSearchParams();
  const [rows, setRows] = React.useState<Contest[] | null>(null);
  const [error, setError] = React.useState<{ status: number | null; message: string } | null>(null);
  const [tab, setTab] = React.useState<Tab>("review");
  const [filters, setFilters] = React.useState<FilterBarValue>(EMPTY_FILTERS);
  const [openId, setOpenId] = React.useState<string | null>(params.get("contest"));

  const load = React.useCallback(async () => {
    const response = await listContests();
    if (response.ok) {
      setRows(response.data.filter((row) => row.status !== "draft"));
      setError(null);
    } else {
      setError({ status: response.status, message: response.error });
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const counts = React.useMemo(() => {
    const result = { review: 0, winners: 0, running: 0, done: 0 } as Record<Tab, number>;
    for (const row of rows ?? []) {
      for (const key of Object.keys(TAB_STATUSES) as Tab[]) {
        if (TAB_STATUSES[key].includes(row.status)) result[key] += 1;
      }
    }
    return result;
  }, [rows]);
  const waiting = counts.review + counts.winners;
  const open = rows?.find((row) => row.id === openId) ?? null;

  const columns: DataColumn<Contest>[] = [
    {
      key: "title",
      header: "Contest",
      render: (row) => (
        <DataTablePrimaryCell title={row.title} subtitle={`${audienceText(row)} · ${LINE_LABEL[row.business_line]}`} />
      ),
    },
    {
      key: "dates",
      header: "Dates",
      cellClassName: "whitespace-nowrap",
      render: (row) => formatContestDates(row.starts_on, row.ends_on),
    },
    { key: "maker", header: "Created by", render: (row) => row.created_by_name ?? "Sub Admin" },
    {
      key: "status",
      header: "Status",
      render: (row) => <StatusBadge tone={STATUS_TONE[row.status]}>{STATUS_LABEL[row.status]}</StatusBadge>,
    },
  ];

  return (
    <DashboardPage>
      <DashboardHeader
        title="Contest approvals"
        description="Approve contests Sub Admins submit, then confirm winners after the end date and pay or record each prize."
        actions={
          <span
            className={
              waiting
                ? "inline-flex items-center gap-2 rounded-full border border-warning/40 bg-warning/10 px-3 py-1.5 text-sm font-medium text-warning"
                : "inline-flex items-center gap-2 rounded-full border border-border bg-muted/40 px-3 py-1.5 text-sm font-medium text-text-secondary"
            }
          >
            {waiting ? <Inbox className="h-4 w-4" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
            {waiting ? `${waiting} waiting on you` : "Nothing waiting"}
          </span>
        }
      />
      <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)} className="space-y-4">
        <TabsList aria-label="Contest queue" className="grid !h-auto w-full max-w-3xl grid-cols-2 gap-1 rounded-xl border border-border bg-muted/50 p-1 sm:grid-cols-4">
          {(
            [
              ["review", "To approve"],
              ["winners", "To confirm winners"],
              ["running", "Upcoming & live"],
              ["done", "Closed"],
            ] as const
          ).map(([value, label]) => (
            <TabsTrigger
              key={value}
              value={value}
              className="!h-auto min-h-11 min-w-0 flex-wrap gap-1.5 whitespace-normal rounded-lg px-3 py-2 data-[state=active]:bg-brand-blue data-[state=active]:text-white dark:data-[state=active]:bg-brand-blue dark:data-[state=active]:text-white"
            >
              {label}
              {counts[value] ? (
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-[11px] font-semibold tabular-nums text-text-primary">
                  {counts[value]}
                </span>
              ) : null}
            </TabsTrigger>
          ))}
        </TabsList>
        <FilterBar
          value={filters}
          onChange={setFilters}
          searchLabel="Search contests"
          searchPlaceholder="Search by title"
          showStatus={false}
          lineOptions={[
            { value: "loans", label: LINE_LABEL.loans },
            { value: "real_estate", label: LINE_LABEL.real_estate },
          ]}
          kindOptions={AUDIENCE_OPTIONS}
          kindLabel="Audience"
          showDates={false}
        />
        {(Object.keys(TAB_STATUSES) as Tab[]).map((key) => {
          const list = filterContests(
            (rows ?? []).filter((row) => TAB_STATUSES[key].includes(row.status)),
            filters,
          );
          return (
            <TabsContent key={key} value={key}>
              <DashboardPanel title={TAB_TITLE[key]}>
                {error ? (
                  <FetchError status={error.status} message={error.message} onRetry={() => void load()} />
                ) : rows === null ? (
                  <ListLoadingState />
                ) : list.length === 0 ? (
                  <ListEmptyState icon={DASHBOARD_ICONS.contests} title="Nothing here" description="Contests appear here as they move through review." />
                ) : (
                  <DataTable
                    columns={columns}
                    rows={list}
                    rowKey={(row) => row.id}
                    onRowClick={(row) => setOpenId(row.id)}
                    rowActionLabel="Open contest"
                    minWidth="min-w-[640px]"
                  />
                )}
              </DashboardPanel>
            </TabsContent>
          );
        })}
      </Tabs>

      <ContestReviewDialog contest={open} onClose={() => setOpenId(null)} onChanged={load} />
    </DashboardPage>
  );
}

function ContestReviewDialog({
  contest,
  onClose,
  onChanged,
}: {
  contest: Contest | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [standings, setStandings] = React.useState<ContestStandings | null>(null);
  const [rejecting, setRejecting] = React.useState<Contest | null>(null);
  const [cancelling, setCancelling] = React.useState<Contest | null>(null);
  const [paying, setPaying] = React.useState<StandingRow | null>(null);
  const [marking, setMarking] = React.useState<StandingRow | null>(null);
  const [busy, setBusy] = React.useState(false);
  const { confirm, confirmDialog } = useConfirm();
  const showsStandings = contest ? ["live", "ended", "finalized"].includes(contest.status) : false;

  const loadStandings = React.useCallback(async () => {
    if (!contest || !["live", "ended", "finalized"].includes(contest.status)) {
      setStandings(null);
      return;
    }
    const response = await getStandings(contest.id);
    setStandings(response.ok ? response.data : null);
    if (!response.ok) toast.error("Could not load the standings", { description: response.error });
  }, [contest]);

  React.useEffect(() => {
    void loadStandings();
  }, [loadStandings]);

  async function act(action: () => Promise<{ ok: boolean; error?: string }>, success: string) {
    setBusy(true);
    const response = await action();
    setBusy(false);
    if (response.ok) {
      toast.success(success);
      await onChanged();
      await loadStandings();
    } else {
      toast.error("That did not work", { description: response.error });
    }
  }

  if (!contest) return null;
  const finalized = contest.status === "finalized";

  return (
    <>
      <Dialog open onOpenChange={(next) => (next ? undefined : onClose())}>
        <DialogContent className="max-h-[92dvh] w-[calc(100vw-2rem)] max-w-4xl overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2">
              {contest.title}
              <StatusBadge tone={STATUS_TONE[contest.status]}>{STATUS_LABEL[contest.status]}</StatusBadge>
            </DialogTitle>
            <DialogDescription>
              Created by {contest.created_by_name ?? "a Sub Admin"}
              {contest.checker_name ? ` · approved by ${contest.checker_name}` : ""}
            </DialogDescription>
          </DialogHeader>
          <ContestRulesPanel contest={contest} />

          {showsStandings ? (
            <section aria-label="Standings" className="space-y-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-heading text-base font-semibold text-brand-heading">
                  {finalized ? "Winners and prizes" : contest.status === "ended" ? "Final standings" : "Live standings"}
                </h3>
                {standings ? (
                  <p className="text-xs text-text-secondary">
                    {standings.source === "snapshot" ? "Snapshot at the end date" : "Updated just now"}
                    {finalized
                      ? ` · ${standings.winners} ${standings.winners === 1 ? "winner" : "winners"} · ${formatPaise(standings.prize_total_paise)} owed · ${formatPaise(standings.paid_total_paise)} paid`
                      : ""}
                  </p>
                ) : null}
              </div>
              {standings === null ? (
                <ListLoadingState rows={3} />
              ) : (
                <StandingsTable
                  contest={contest}
                  rows={[...standings.rows, ...standings.team_people]}
                  onPay={setPaying}
                  onMarkPaid={setMarking}
                />
              )}
            </section>
          ) : null}

          <DialogFooter className="flex-wrap gap-2 sm:justify-between">
            <div>
              {["approved", "live", "ended"].includes(contest.status) ? (
                <Button variant="outline" onClick={() => setCancelling(contest)} disabled={busy}>
                  Cancel contest
                </Button>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              {contest.status === "pending_approval" ? (
                <>
                  <Button variant="outline" onClick={() => setRejecting(contest)} disabled={busy}>
                    Request changes
                  </Button>
                  <Button onClick={() => void act(() => approveContest(contest.id), "Contest approved")} disabled={busy}>
                    Approve
                  </Button>
                </>
              ) : null}
              {contest.status === "ended" ? (
                <>
                  <Button variant="outline" onClick={() => void act(() => recalculateContest(contest.id), "Standings recalculated")} disabled={busy}>
                    Recalculate
                  </Button>
                  <Button
                    disabled={busy}
                    onClick={async () => {
                      if (
                        await confirm({
                          title: "Confirm the winners?",
                          description:
                            "Winners and prizes are fixed from these standings and winners are told. This cannot be undone.",
                          confirmLabel: "Confirm winners",
                        })
                      ) {
                        await act(() => finalizeContest(contest.id), "Winners confirmed");
                      }
                    }}
                  >
                    Confirm winners
                  </Button>
                </>
              ) : null}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ReasonDialog
        contest={rejecting}
        title="Request changes?"
        description="The Sub Admin sees your note, edits the contest and submits it again."
        label="What should change"
        confirmLabel="Request changes"
        onOpenChange={(next) => (next ? undefined : setRejecting(null))}
        onConfirm={async (note) => {
          setRejecting(null);
          await act(() => rejectContest(contest.id, note), "Changes requested");
        }}
      />
      <ReasonDialog
        contest={cancelling}
        onOpenChange={(next) => (next ? undefined : setCancelling(null))}
        onConfirm={async (reason) => {
          setCancelling(null);
          await act(() => cancelContest(contest.id, reason), "Contest cancelled");
        }}
      />
      <MoneyPayoutDialog
        open={paying !== null}
        onOpenChange={(next) => (next ? undefined : setPaying(null))}
        title={paying ? formatPaise(paying.prize_paise) : "Contest prize"}
        description={paying ? `${paying.name} · ${contest.title}` : ""}
        idPrefix="contest-prize-payout"
        lockedCopy="Recipient and amount come from this result and cannot be changed here. A different Admin approves the payout in Payouts."
        submitLabel="Raise payout"
        conflictTitle="This prize may already have a payout"
        savedDestinationTarget={paying?.agent_profile_uuid ? { agentProfileUuid: paying.agent_profile_uuid } : null}
        onSubmit={async (form) => {
          const response = await requestPrizePayout(contest.id, paying!.result_id!, buildCommissionPayoutPayload(form));
          if (response.ok) await loadStandings();
          return response;
        }}
      />
      <ReasonDialog
        contest={marking ? contest : null}
        title="Record this prize as paid?"
        description={marking ? `${marking.name} · ${formatPaise(marking.prize_paise)}. Staff prizes are paid outside Payouts, for example with payroll.` : ""}
        label="How it was paid (no bank or personal details)"
        confirmLabel="Mark paid"
        onOpenChange={(next) => (next ? undefined : setMarking(null))}
        onConfirm={async (reference) => {
          const row = marking;
          setMarking(null);
          if (row?.result_id) await act(() => markPrizePaid(contest.id, row.result_id!, reference), "Prize recorded as paid");
        }}
      />
      {confirmDialog}
    </>
  );
}

function StandingsTable({
  contest,
  rows,
  onPay,
  onMarkPaid,
}: {
  contest: Contest;
  rows: StandingRow[];
  onPay: (row: StandingRow) => void;
  onMarkPaid: (row: StandingRow) => void;
}) {
  const finalized = contest.status === "finalized";
  if (rows.length === 0) {
    return <p className="text-sm text-text-secondary">Nobody is taking part yet.</p>;
  }
  const kindLabel: Record<string, string> = {
    team_manager: "Manager",
    team_member: "Member",
  };
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="bg-muted/50 text-left text-xs text-text-secondary">
          <tr>
            <th scope="col" className="px-3 py-2">Rank</th>
            <th scope="col" className="px-3 py-2">Participant</th>
            <th scope="col" className="px-3 py-2 text-right">Achieved</th>
            <th scope="col" className="px-3 py-2">Targets</th>
            {finalized ? <th scope="col" className="px-3 py-2">Prize</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.result_id ?? `${row.kind}-${row.name}-${index}`} className="border-t border-border">
              <td className="px-3 py-2 tabular-nums">{row.kind === "team_member" || row.kind === "team_manager" ? "—" : (row.rank ?? "—")}</td>
              <td className="px-3 py-2">
                <span className="font-medium text-text-primary">{row.name}</span>
                {kindLabel[row.kind] ? (
                  <span className="ml-1 text-xs text-text-secondary">
                    {kindLabel[row.kind]} · {row.team_name}
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{formatMetricValue(contest.metric, row.metric_value)}</td>
              <td className="px-3 py-2">
                {row.kind === "team_manager" ? (
                  <span className="text-xs text-text-secondary">Team result</span>
                ) : (
                  <StatusBadge tone={row.qualified ? "success" : "neutral"}>{row.qualified ? "Met" : "Not yet"}</StatusBadge>
                )}
              </td>
              {finalized ? (
                <td className="px-3 py-2">
                  <PrizeCell row={row} onPay={onPay} onMarkPaid={onMarkPaid} />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PrizeCell({
  row,
  onPay,
  onMarkPaid,
}: {
  row: StandingRow;
  onPay: (row: StandingRow) => void;
  onMarkPaid: (row: StandingRow) => void;
}) {
  if (row.kind === "team") return <span className="text-xs text-text-secondary">{row.won ? "Won" : "—"}</span>;
  if (row.prize_paise <= 0) {
    return (
      <span className="text-xs text-text-secondary">
        {row.excluded_reason ? EXCLUSION_LABEL[row.excluded_reason] ?? "No prize" : "No prize"}
      </span>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-medium tabular-nums">{formatPaise(row.prize_paise)}</span>
      <StatusBadge tone={row.payment_status === "paid" ? "success" : row.payment_status === "payout_pending" ? "info" : "warning"}>
        {PAYMENT_LABEL[row.payment_status] ?? row.payment_status}
      </StatusBadge>
      {row.payment_status === "unpaid" && row.participant_type === "agent" ? (
        <Button size="sm" variant="outline" onClick={() => onPay(row)}>
          Pay prize
        </Button>
      ) : null}
      {row.payment_status === "unpaid" && row.participant_type === "staff" ? (
        <Button size="sm" variant="outline" onClick={() => onMarkPaid(row)}>
          Mark paid
        </Button>
      ) : null}
    </div>
  );
}
