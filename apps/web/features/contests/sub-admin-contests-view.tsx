"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { DataTable, DataTablePrimaryCell, type DataColumn } from "@/features/dashboard/data-table";
import { FetchError } from "@/features/dashboard/fetch-error";
import { EMPTY_FILTERS, FilterBar, matchesSearch, type FilterBarValue } from "@/features/dashboard/filter-bar";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import {
  AUDIENCE_LABEL,
  formatContestDates,
  LINE_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
  TEAM_ROLE_LABEL,
} from "@/lib/contest-rules";
import {
  cancelContest,
  deleteContest,
  isContestId,
  listContests,
  submitContest,
  withdrawContest,
  type Contest,
} from "@/lib/contests-api";

import { ContestFormDialog } from "./contest-form-dialog";
import { ContestRulesPanel } from "./contest-rules-panel";

const STATUS_OPTIONS = (Object.keys(STATUS_LABEL) as Contest["status"][]).map((value) => ({
  value,
  label: STATUS_LABEL[value],
}));
const AUDIENCE_OPTIONS = (Object.keys(AUDIENCE_LABEL) as Contest["audience"][]).map((value) => ({
  value,
  label: AUDIENCE_LABEL[value],
}));
const LINE_OPTIONS = [
  { value: "loans", label: LINE_LABEL.loans },
  { value: "real_estate", label: LINE_LABEL.real_estate },
];

export function audienceText(contest: Pick<Contest, "audience" | "team_member_role">): string {
  return contest.audience === "team" && contest.team_member_role
    ? TEAM_ROLE_LABEL[contest.team_member_role]
    : AUDIENCE_LABEL[contest.audience];
}

export function filterContests(rows: readonly Contest[], filters: FilterBarValue): Contest[] {
  return rows.filter(
    (row) =>
      (filters.status === "all" || row.status === filters.status) &&
      (filters.line === "all" || row.business_line === filters.line) &&
      (filters.kind === "all" || row.audience === filters.kind) &&
      (!filters.search || matchesSearch(`${row.title} ${row.description ?? ""}`, filters.search)),
  );
}

export function SubAdminContestsView() {
  const params = useSearchParams();
  const [rows, setRows] = React.useState<Contest[] | null>(null);
  const [error, setError] = React.useState<{ status: number | null; message: string } | null>(null);
  const [filters, setFilters] = React.useState<FilterBarValue>(EMPTY_FILTERS);
  const [editing, setEditing] = React.useState<Contest | null>(null);
  const [formOpen, setFormOpen] = React.useState(false);
  const [openId, setOpenId] = React.useState<string | null>(() => {
    const linked = params.get("contest");
    return isContestId(linked) ? linked : null;
  });
  const [cancelling, setCancelling] = React.useState<Contest | null>(null);
  const { confirm, confirmDialog } = useConfirm();

  const load = React.useCallback(async () => {
    const response = await listContests();
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

  const visible = React.useMemo(() => filterContests(rows ?? [], filters), [rows, filters]);
  const open = rows?.find((row) => row.id === openId) ?? null;

  function replace(contest: Contest) {
    setRows((current) => {
      const list = current ?? [];
      return list.some((row) => row.id === contest.id)
        ? list.map((row) => (row.id === contest.id ? contest : row))
        : [contest, ...list];
    });
  }

  async function run(action: () => Promise<{ ok: boolean; error?: string }>, success: string) {
    const response = await action();
    if (response.ok) {
      toast.success(success);
      await load();
    } else {
      toast.error("That did not work", { description: response.error });
    }
  }

  const columns: DataColumn<Contest>[] = [
    {
      key: "title",
      header: "Contest",
      render: (row) => (
        <DataTablePrimaryCell
          title={row.title}
          subtitle={`${audienceText(row)} · ${LINE_LABEL[row.business_line]}`}
        />
      ),
    },
    {
      key: "dates",
      header: "Dates",
      cellClassName: "whitespace-nowrap",
      render: (row) => formatContestDates(row.starts_on, row.ends_on, row.start_time, row.end_time),
    },
    {
      key: "maker",
      header: "Created by",
      render: (row) => (row.is_mine ? "You" : (row.created_by_name ?? "Another Sub Admin")),
    },
    {
      key: "status",
      header: "Status",
      render: (row) => <StatusBadge tone={STATUS_TONE[row.status]}>{STATUS_LABEL[row.status]}</StatusBadge>,
    },
  ];

  return (
    <DashboardPage>
      <DashboardHeader
        title="Contests"
        description="Create incentive contests for Agents, Telecallers, Officers or teams. A platform Admin approves each one before it goes live."
        actions={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="h-4 w-4" aria-hidden />
            New contest
          </Button>
        }
      />
      <FilterBar
        value={filters}
        onChange={setFilters}
        searchLabel="Search contests"
        searchPlaceholder="Search by title"
        statusOptions={STATUS_OPTIONS}
        lineOptions={LINE_OPTIONS}
        kindOptions={AUDIENCE_OPTIONS}
        kindLabel="Audience"
        showDates={false}
      />
      <DashboardPanel title="All contests" description="Every Sub Admin sees every contest; only the creator can change one.">
        {error ? (
          <FetchError status={error.status} message={error.message} onRetry={() => void load()} />
        ) : rows === null ? (
          <ListLoadingState />
        ) : visible.length === 0 ? (
          <ListEmptyState
            icon={DASHBOARD_ICONS.contests}
            title={rows.length === 0 ? "No contests yet" : "No contests match these filters"}
            description={rows.length === 0 ? "Create the first one with New contest." : "Clear a filter to see more."}
          />
        ) : (
          <DataTable
            columns={columns}
            rows={visible}
            rowKey={(row) => row.id}
            onRowClick={(row) => setOpenId(row.id)}
            rowActionLabel="Open contest"
            minWidth="min-w-[640px]"
          />
        )}
      </DashboardPanel>

      <Dialog open={open !== null} onOpenChange={(next) => (next ? undefined : setOpenId(null))}>
        <DialogContent className="max-h-[92dvh] w-[calc(100vw-2rem)] max-w-2xl overflow-y-auto sm:max-w-2xl">
          {open ? (
            <>
              <DialogHeader>
                <DialogTitle className="flex flex-wrap items-center gap-2">
                  {open.title}
                  <StatusBadge tone={STATUS_TONE[open.status]}>{STATUS_LABEL[open.status]}</StatusBadge>
                </DialogTitle>
                <DialogDescription>
                  {open.is_mine ? "You created this contest." : `Created by ${open.created_by_name ?? "another Sub Admin"}.`}
                </DialogDescription>
              </DialogHeader>
              {open.status === "rejected" && open.review_note ? (
                <p role="status" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-text-primary">
                  <span className="font-medium">Changes requested{open.checker_name ? ` by ${open.checker_name}` : ""}:</span>{" "}
                  {open.review_note}
                </p>
              ) : null}
              {open.status === "cancelled" && open.cancel_reason ? (
                <p className="rounded-lg border border-border bg-muted/40 p-3 text-sm">Cancelled: {open.cancel_reason}</p>
              ) : null}
              <ContestRulesPanel contest={open} />
              {open.is_mine ? (
                <DialogFooter className="flex-wrap gap-2 sm:justify-between">
                  <div className="flex flex-wrap gap-2">
                    {open.status === "draft" ? (
                      <Button
                        variant="ghost"
                        className="text-destructive"
                        onClick={async () => {
                          if (
                            await confirm({
                              title: "Delete this draft?",
                              description: "It has never been submitted. This cannot be undone.",
                              destructive: true,
                            })
                          ) {
                            setOpenId(null);
                            await run(() => deleteContest(open.id), "Draft deleted");
                          }
                        }}
                      >
                        Delete draft
                      </Button>
                    ) : null}
                    {["draft", "pending_approval", "rejected"].includes(open.status) ? (
                      <Button variant="outline" onClick={() => setCancelling(open)}>
                        Cancel contest
                      </Button>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {open.status === "pending_approval" ? (
                      <Button variant="outline" onClick={() => void run(() => withdrawContest(open.id), "Taken back to draft")}>
                        Take back to edit
                      </Button>
                    ) : null}
                    {["draft", "rejected"].includes(open.status) ? (
                      <>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setEditing(open);
                            setFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        <Button onClick={() => void run(() => submitContest(open.id), "Submitted for approval")}>
                          Submit for approval
                        </Button>
                      </>
                    ) : null}
                  </div>
                </DialogFooter>
              ) : null}
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <ReasonDialog
        contest={cancelling}
        onOpenChange={(next) => (next ? undefined : setCancelling(null))}
        onConfirm={async (reason) => {
          if (!cancelling) return;
          const id = cancelling.id;
          setCancelling(null);
          await run(() => cancelContest(id, reason), "Contest cancelled");
        }}
      />

      <ContestFormDialog
        open={formOpen}
        contest={editing}
        onOpenChange={setFormOpen}
        onSaved={(contest) => {
          replace(contest);
          setOpenId(contest.id);
        }}
      />
      {confirmDialog}
    </DashboardPage>
  );
}

export function ReasonDialog({
  contest,
  onOpenChange,
  onConfirm,
  title = "Cancel this contest?",
  description = "Nobody is paid for a cancelled contest. Tell the team why.",
  label = "Reason",
  confirmLabel = "Cancel contest",
}: {
  contest: Contest | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reason: string) => Promise<void>;
  title?: string;
  description?: string;
  label?: string;
  confirmLabel?: string;
}) {
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (contest) setReason("");
  }, [contest]);
  const valid = reason.trim().length >= 3;
  return (
    <Dialog open={contest !== null} onOpenChange={onOpenChange}>
      <DialogContent preventOutsideClose className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="contest-reason">{label}</Label>
          <Input
            id="contest-reason"
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
          />
          {!valid && reason ? <p className="text-xs text-text-secondary">At least 3 characters.</p> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Keep it
          </Button>
          <Button
            variant="destructive"
            disabled={!valid || busy}
            onClick={async () => {
              setBusy(true);
              await onConfirm(reason.trim());
              setBusy(false);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
