"use client";

import * as React from "react";
import { ArrowRightLeft, FileText, Pencil } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { FetchError } from "@/features/dashboard/fetch-error";
import { sortLeadsByDefaultOrder } from "@/features/dashboard/list-order";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import { optionsFromLabels } from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import { leadSignalFilterGroups } from "@/features/telecaller/lead-signal-filter-fields";
import {
  DEFAULT_LEAD_SIGNAL_FILTERS,
  formatReferrer,
  leadSignalActiveCount,
  leadSignalChips,
  leadSignalOptions,
  lineScope,
  rowsHiddenTransactionParts,
  scopedLeadSignalFilters,
  type LeadSignalOptions,
  type LeadSignalScope,
} from "@/features/telecaller/lead-signal-filters";
import { CallLogList } from "@/features/telecaller/telecaller-call-log";
import {
  DISPOSITION_LABEL,
  STATUS_LABEL,
  STATUS_STYLE,
  formatDateTime,
} from "@/features/telecaller/telecaller-lead-status";
import { formatDate } from "@/lib/format";
import {
  addTeamNote,
  getMemberWork,
  getTeamLead,
  getTeamTask,
  getTeamWork,
  personName,
  reassignTeamWork,
  setTeamLeadStatus,
  updateTeamTask,
  type StaffTeam,
  type TeamLeadRow,
  type TeamLeadStatus,
  type TeamLeadDetail,
  type TeamTaskDetail,
  type TeamTaskRow,
  type TeamWork,
} from "@/lib/staff-teams-api";
import { cn } from "@/lib/utils";

import { ManagerNotesList } from "./manager-notes-panel";
import {
  DEFAULT_TEAM_WORK_FILTERS,
  filterTeamLeads,
  filterTeamTasks,
  isOverdueLead,
  isOverdueTask,
  teamSignalValues,
  teamWorkFiltersActive,
  type TeamWorkFilters,
} from "./team-work-filters";
import { useLoad } from "./use-load";

export const TASK_TYPE_LABEL: Record<string, string> = {
  document_collection: "Document collection",
  property_visit: "Property visit",
  background_check: "Background check",
};

const TASK_STATUS_LABEL: Record<string, string> = {
  assigned: "Assigned",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
  cancelled: "Cancelled",
};

const LEAD_STATUS_FILTERS = ["assigned", "working", "converted", "closed"] as const;
const LEAD_EDIT_STATUSES: TeamLeadStatus[] = ["working", "converted", "closed"];
const OPEN_LEAD = new Set(["assigned", "working"]);
const OPEN_TASK = new Set(["assigned", "in_progress", "blocked"]);

type Kind = "leads" | "tasks";
type WorkData = Pick<TeamWork, "kind" | "leads" | "tasks">;
const NOT_LOADED = { ok: false as const, error: "", status: 0 };
type Target = { kind: Kind; id: string; label: string; holder: string | undefined };

function StatusPill({ status, label }: { status: string; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
        STATUS_STYLE[status] ?? "bg-muted text-text-secondary",
      )}
    >
      {label}
    </span>
  );
}

function hiddenLabel(hidden: readonly string[] | undefined, key: string, value: string | null | undefined) {
  if (hidden?.includes(key)) return "Hidden by Admin";
  return value ?? null;
}

function toIso(local: string): string | null {
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function localNowPlus(minutes: number): string {
  const date = new Date(Date.now() + minutes * 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// --- Dialogs ---------------------------------------------------------------------

function MoveDialog({
  team,
  target,
  onClose,
  onDone,
}: {
  team: StaffTeam;
  target: Target | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const teammates = team.members.filter(
    (person) => person.staff_profile_uuid !== target?.holder && person.status === "active",
  );
  const [chosen, setChosen] = React.useState<string | undefined>();
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setChosen(undefined);
    setError(null);
  }, [target]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!target || !chosen) return setError("Choose a teammate.");
    setSaving(true);
    const res = await reassignTeamWork(team.id, target.kind, target.id, chosen);
    setSaving(false);
    if (!res.ok) return setError(res.error);
    const to = teammates.find((person) => person.staff_profile_uuid === chosen);
    toast.success(`Moved to ${to ? personName(to) : "teammate"}`, {
      description: "Both of them have been notified.",
    });
    onDone();
  }

  return (
    <Dialog open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent preventOutsideClose className="max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Move to a teammate</DialogTitle>
            <DialogDescription>
              {target?.label} moves to the person you choose. The call history stays with the
              client.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="move-to">Teammate</Label>
            <Select value={chosen} onValueChange={setChosen} disabled={teammates.length === 0}>
              <SelectTrigger id="move-to">
                <SelectValue
                  placeholder={teammates.length === 0 ? "No other active members" : "Choose a teammate"}
                />
              </SelectTrigger>
              <SelectContent>
                {teammates.map((person) => (
                  <SelectItem key={person.staff_profile_uuid} value={person.staff_profile_uuid}>
                    {personName(person)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {error ? (
              <p role="alert" className="text-sm text-error">
                {error}
              </p>
            ) : null}
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !chosen}>
              {saving ? "Moving…" : "Move"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditDialog({
  team,
  target,
  current,
  onClose,
  onDone,
}: {
  team: StaffTeam;
  target: Target | null;
  current: { status: string; due_at?: string | null } | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const isLead = target?.kind === "leads";
  const [status, setStatus] = React.useState<TeamLeadStatus | undefined>();
  const [mode, setMode] = React.useState<"due" | "cancel">("due");
  const [due, setDue] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setStatus(undefined);
    setMode("due");
    setDue("");
    setReason("");
    setError(null);
  }, [target]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!target) return;
    setError(null);
    let res;
    if (isLead) {
      if (!status) return setError("Choose the new status.");
      setSaving(true);
      res = await setTeamLeadStatus(team.id, target.id, status);
    } else if (mode === "due") {
      const iso = toIso(due);
      if (!iso || new Date(iso).getTime() <= Date.now()) {
        return setError("Choose a due date and time in the future.");
      }
      setSaving(true);
      res = await updateTeamTask(team.id, target.id, { due_at: iso });
    } else {
      if (reason.trim().length < 3) return setError("Say why the task is cancelled.");
      setSaving(true);
      res = await updateTeamTask(team.id, target.id, { cancel_reason: reason.trim() });
    }
    setSaving(false);
    if (!res.ok) return setError(res.error);
    toast.success(isLead ? "Lead updated" : mode === "due" ? "Due date changed" : "Task cancelled", {
      description: "The team member has been notified.",
    });
    onDone();
  }

  const statuses = LEAD_EDIT_STATUSES.filter((value) => value !== current?.status);
  return (
    <Dialog open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent preventOutsideClose className="max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>{isLead ? "Change lead status" : "Change task"}</DialogTitle>
            <DialogDescription>
              {target?.label}.{" "}
              {isLead
                ? "Client details stay with whoever entered them."
                : "Completing a task stays with the Officer, who records the outcome."}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-4">
            {isLead ? (
              <div className="space-y-1.5">
                <Label htmlFor="edit-status">New status</Label>
                <Select value={status} onValueChange={(value) => setStatus(value as TeamLeadStatus)}>
                  <SelectTrigger id="edit-status">
                    <SelectValue placeholder="Choose a status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statuses.map((value) => (
                      <SelectItem key={value} value={value}>
                        {STATUS_LABEL[value] ?? value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <>
                <RadioGroup
                  value={mode}
                  onValueChange={(value) => setMode(value as "due" | "cancel")}
                  aria-label="Change"
                  className="grid gap-2"
                >
                  <Label className="flex min-h-11 items-center gap-2 font-normal">
                    <RadioGroupItem value="due" /> Change the due date
                  </Label>
                  <Label className="flex min-h-11 items-center gap-2 font-normal">
                    <RadioGroupItem value="cancel" /> Cancel the task
                  </Label>
                </RadioGroup>
                {mode === "due" ? (
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-due">
                      New due date
                      {current?.due_at ? (
                        <span className="ml-1 font-normal text-text-secondary">
                          (now {formatDateTime(current.due_at)})
                        </span>
                      ) : null}
                    </Label>
                    <Input
                      id="edit-due"
                      type="datetime-local"
                      min={localNowPlus(5)}
                      value={due}
                      onChange={(event) => setDue(event.target.value)}
                    />
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <Label htmlFor="edit-reason">Reason</Label>
                    <Textarea
                      id="edit-reason"
                      rows={3}
                      maxLength={500}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                    <p className="text-xs text-text-secondary">
                      Saved as a note the Officer can read.
                    </p>
                  </div>
                )}
              </>
            )}
            {error ? (
              <p role="alert" className="text-sm text-error">
                {error}
              </p>
            ) : null}
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={onClose}>
              Close
            </Button>
            <Button
              type="submit"
              variant={!isLead && mode === "cancel" ? "destructive" : "default"}
              disabled={saving}
            >
              {saving ? "Saving…" : !isLead && mode === "cancel" ? "Cancel task" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function NoteForm({
  teamId,
  target,
  onAdded,
}: {
  teamId: string;
  target: Target;
  onAdded: () => void;
}) {
  const [body, setBody] = React.useState("");
  const [followUp, setFollowUp] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const isLead = target.kind === "leads";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!body.trim()) return setError("Write a note.");
    let follow_up_at: string | undefined;
    if (isLead && followUp) {
      const iso = toIso(followUp);
      if (!iso || new Date(iso).getTime() <= Date.now()) {
        return setError("Choose a follow-up in the future, or leave it empty.");
      }
      follow_up_at = iso;
    }
    setSaving(true);
    setError(null);
    const res = await addTeamNote(teamId, target.kind, target.id, { body: body.trim(), follow_up_at });
    setSaving(false);
    if (!res.ok) return setError(res.error);
    setBody("");
    setFollowUp("");
    toast.success("Note added", { description: "The team member has been notified." });
    onAdded();
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 rounded-lg border border-border p-3">
      <div className="space-y-1.5">
        <Label htmlFor="note-body">Add a note for the team member</Label>
        <Textarea
          id="note-body"
          rows={3}
          maxLength={10000}
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
      </div>
      {isLead ? (
        <div className="space-y-1.5">
          <Label htmlFor="note-follow-up">
            Follow up by <span className="font-normal text-text-secondary">(optional)</span>
          </Label>
          <Input
            id="note-follow-up"
            type="datetime-local"
            min={localNowPlus(5)}
            value={followUp}
            onChange={(event) => setFollowUp(event.target.value)}
          />
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" size="sm" disabled={saving}>
          {saving ? "Adding…" : "Add note"}
        </Button>
      </div>
    </form>
  );
}

function DetailDialog({
  team,
  target,
  onClose,
}: {
  team: StaffTeam;
  target: Target | null;
  onClose: () => void;
}) {
  const leadLoad = useLoad<TeamLeadDetail>(
    () =>
      target?.kind === "leads" ? getTeamLead(team.id, target.id) : Promise.resolve(NOT_LOADED),
    [team.id, target?.kind, target?.id],
  );
  const taskLoad = useLoad<TeamTaskDetail>(
    () =>
      target?.kind === "tasks" ? getTeamTask(team.id, target.id) : Promise.resolve(NOT_LOADED),
    [team.id, target?.kind, target?.id],
  );
  const state = target?.kind === "tasks" ? taskLoad.state : leadLoad.state;
  const retry = target?.kind === "tasks" ? taskLoad.retry : leadLoad.retry;
  const lead =
    target?.kind === "leads" && leadLoad.state.status === "ready" && leadLoad.state.data.lead.id === target.id
      ? leadLoad.state.data
      : null;
  const task =
    target?.kind === "tasks" && taskLoad.state.status === "ready" && taskLoad.state.data.task.id === target.id
      ? taskLoad.state.data
      : null;
  const notes = lead?.notes ?? task?.notes ?? [];

  return (
    <Dialog open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent preventOutsideClose className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{target?.label}</DialogTitle>
          <DialogDescription>
            {lead
              ? `${lead.lead.mobile} · ${STATUS_LABEL[lead.lead.status] ?? lead.lead.status} · with ${personName(lead.assigned_to)}`
              : task
                ? `${TASK_STATUS_LABEL[task.task.status] ?? task.task.status} · with ${personName(task.assigned_to)}`
                : null}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-5">
          {lead || task ? (
            <>
              {lead && lead.lead.requests.length > 0 ? (
                <section aria-label="Applications">
                  <h3 className="text-sm font-medium text-text-primary">Applications</h3>
                  <ul className="mt-2 space-y-1 text-sm">
                    {lead.lead.requests.map((request) => (
                      <li key={request.id} className="flex justify-between gap-3">
                        <span className="min-w-0 truncate">{request.title}</span>
                        <span className="shrink-0 text-text-secondary">
                          {request.status} · {formatDate(request.applied_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {task?.task.notes ? (
                <section aria-label="Officer notes">
                  <h3 className="text-sm font-medium text-text-primary">Officer notes</h3>
                  <p className="mt-1 whitespace-pre-line text-sm text-text-primary">{task.task.notes}</p>
                </section>
              ) : null}
              <section aria-label="Your notes" className="space-y-3">
                <h3 className="text-sm font-medium text-text-primary">Your notes</h3>
                <ManagerNotesList notes={notes} />
                {target ? <NoteForm teamId={team.id} target={target} onAdded={retry} /> : null}
              </section>
              {lead ? (
                <section aria-label="Call log">
                  <h3 className="mb-3 text-sm font-medium text-text-primary">Call log</h3>
                  <CallLogList activities={lead.activities} requests={[]} />
                </section>
              ) : null}
            </>
          ) : state.status === "error" && target ? (
            <FetchError status={state.code} message={state.error} onRetry={retry} />
          ) : (
            <ListLoadingState rows={3} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// --- Rows ------------------------------------------------------------------------

function RowActions({
  open,
  name,
  onDetails,
  onEdit,
  onMove,
}: {
  open: boolean;
  name: string;
  onDetails: () => void;
  onEdit: () => void;
  onMove: () => void;
}) {
  return (
    <div className="flex shrink-0 flex-wrap gap-2">
      <Button type="button" variant="outline" size="sm" onClick={onDetails}>
        <FileText /> Details<span className="sr-only"> for {name}</span>
      </Button>
      {open ? (
        <>
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <Pencil /> Edit<span className="sr-only"> {name}</span>
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onMove}>
            <ArrowRightLeft /> Move<span className="sr-only"> {name}</span>
          </Button>
        </>
      ) : null}
    </div>
  );
}

function LeadRows({
  rows,
  showAssignee,
  now,
  onAction,
}: {
  rows: TeamLeadRow[];
  showAssignee: boolean;
  now: Date;
  onAction: (action: "details" | "edit" | "move", row: TeamLeadRow) => void;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Leads">
      {rows.map((lead) => {
        const name = hiddenLabel(lead.hidden_fields, "name", lead.name) ?? "Unnamed client";
        const referrer = lead.hidden_fields?.includes("referrer")
          ? null
          : formatReferrer(lead.signals?.referrer);
        const latest = lead.requests[0];
        const overdue = isOverdueLead(lead, now);
        return (
          <li key={lead.id} className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text-primary">{name}</span>
                <StatusPill status={lead.status} label={STATUS_LABEL[lead.status] ?? lead.status} />
                {overdue ? <Badge variant="outline" className="border-warning text-warning">Follow-up overdue</Badge> : null}
              </p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {lead.mobile}
                {latest ? ` · ${latest.title}` : ""}
                {referrer ? ` · ${referrer}` : ""}
              </p>
              <p className="mt-0.5 text-xs text-text-secondary">
                {showAssignee && lead.assigned_to ? `${personName(lead.assigned_to)} · ` : ""}
                {lead.last_call
                  ? `Last call ${formatDateTime(lead.last_call.created_at)}: ${DISPOSITION_LABEL[lead.last_call.disposition] ?? lead.last_call.disposition}`
                  : "Not called yet"}
                {lead.last_call?.follow_up_at
                  ? ` · follow-up ${formatDateTime(lead.last_call.follow_up_at)}`
                  : ""}
              </p>
            </div>
            <RowActions
              open={OPEN_LEAD.has(lead.status)}
              name={name}
              onDetails={() => onAction("details", lead)}
              onEdit={() => onAction("edit", lead)}
              onMove={() => onAction("move", lead)}
            />
          </li>
        );
      })}
    </ul>
  );
}

function TaskRows({
  rows,
  showAssignee,
  now,
  onAction,
}: {
  rows: TeamTaskRow[];
  showAssignee: boolean;
  now: Date;
  onAction: (action: "details" | "edit" | "move", row: TeamTaskRow) => void;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Tasks">
      {rows.map((task) => {
        const type = TASK_TYPE_LABEL[task.task_type] ?? task.task_type;
        const client = hiddenLabel(task.hidden_fields, "name", task.lead_name) ?? "Unnamed client";
        const overdue = isOverdueTask(task, now);
        return (
          <li key={task.id} className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text-primary">{type}</span>
                <Badge variant="outline">{TASK_STATUS_LABEL[task.status] ?? task.status}</Badge>
                {overdue ? <Badge variant="outline" className="border-warning text-warning">Overdue</Badge> : null}
              </p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {client}
                {task.lead_mobile ? ` · ${task.lead_mobile}` : ""} ·{" "}
                {task.due_at ? `due ${formatDateTime(task.due_at)}` : "no due date"}
              </p>
              {showAssignee && task.assigned_to ? (
                <p className="mt-0.5 text-xs text-text-secondary">{personName(task.assigned_to)}</p>
              ) : null}
            </div>
            <RowActions
              open={OPEN_TASK.has(task.status)}
              name={`${type} for ${client}`}
              onDetails={() => onAction("details", task)}
              onEdit={() => onAction("edit", task)}
              onMove={() => onAction("move", task)}
            />
          </li>
        );
      })}
    </ul>
  );
}

// --- Filter bar -------------------------------------------------------------------

const TASK_TYPE_OPTIONS = optionsFromLabels(TASK_TYPE_LABEL);

/**
 * The shared dashboard filter bar for team work: Open/All and Overdue toggles
 * above; search, status, task type and team member in the first row; the lead
 * signals (call status, lead interest, lead source, referred by, loan status)
 * behind "More filters (n)", shown as chips while active.
 */
function TeamWorkFilterBar({
  team,
  kind,
  filters,
  onChange,
  scope,
  onScope,
  showAssignee,
  signalScope,
  signalOptions,
}: {
  team: StaffTeam;
  kind: Kind;
  filters: TeamWorkFilters;
  onChange: (patch: Partial<TeamWorkFilters>) => void;
  scope: "open" | "all";
  onScope: (scope: "open" | "all") => void;
  showAssignee: boolean;
  signalScope: LeadSignalScope;
  signalOptions: LeadSignalOptions;
}) {
  const statusOptions = (
    kind === "leads"
      ? LEAD_STATUS_FILTERS.filter((value) => scope === "all" || OPEN_LEAD.has(value))
      : Object.keys(TASK_STATUS_LABEL).filter((value) => scope === "all" || OPEN_TASK.has(value))
  ).map((value) => ({ value, label: (kind === "leads" ? STATUS_LABEL : TASK_STATUS_LABEL)[value] ?? value }));
  const memberOptions = team.members.map((member) => ({
    value: member.staff_profile_uuid,
    label: personName(member),
  }));
  return (
    <div role="group" aria-label="Work filters">
      <FilterBar
        value={{ ...EMPTY_FILTERS, search: filters.search, status: filters.status, kind: filters.taskType }}
        onChange={(next) => onChange({ search: next.search, status: next.status, taskType: next.kind })}
        searchLabel="Search client name or mobile"
        searchPlaceholder="Search client name or mobile"
        statusOptions={statusOptions}
        kindOptions={kind === "tasks" ? TASK_TYPE_OPTIONS : undefined}
        kindLabel="Task type"
        showLine={false}
        showDates={false}
        actions={
          <>
            <ToggleGroup
              type="single"
              value={scope}
              onValueChange={(value) => value && onScope(value as "open" | "all")}
              aria-label="Which work"
            >
              <ToggleGroupItem value="open" className="px-3">
                Open
              </ToggleGroupItem>
              <ToggleGroupItem value="all" className="px-3">
                All
              </ToggleGroupItem>
            </ToggleGroup>
            <ToggleGroup
              type="single"
              value={filters.overdueOnly ? "overdue" : ""}
              onValueChange={(value) => onChange({ overdueOnly: value === "overdue" })}
              aria-label="Overdue"
            >
              <ToggleGroupItem value="overdue" className="px-3">
                {kind === "leads" ? "Follow-up overdue" : "Overdue"}
              </ToggleGroupItem>
            </ToggleGroup>
          </>
        }
        extra={
          showAssignee ? (
            <FilterSelect
              label="Team member"
              value={filters.assignee}
              options={memberOptions}
              onValueChange={(assignee) => onChange({ assignee })}
            />
          ) : null
        }
        more={leadSignalFilterGroups({ filters, onChange, scope: signalScope, options: signalOptions })}
        moreActiveCount={leadSignalActiveCount(filters, signalScope)}
        onClearMore={() => onChange(DEFAULT_LEAD_SIGNAL_FILTERS)}
        chips={leadSignalChips(filters, onChange, signalScope, signalOptions)}
        onClear={() => onChange(DEFAULT_TEAM_WORK_FILTERS)}
        hasExternalFilters={teamWorkFiltersActive({ ...filters, ...scopedLeadSignalFilters(filters, signalScope) })}
      />
    </div>
  );
}

// --- List ------------------------------------------------------------------------

/**
 * A manager's filtered work list: every member's work, or one member's when
 * `memberId` is given. Filters run over the loaded rows (at most 200 per scope,
 * like the Telecaller and Employee lists); the API decides what is loaded.
 */
export function TeamWorkList({ team, memberId }: { team: StaffTeam; memberId?: string }) {
  const [scope, setScope] = React.useState<"open" | "all">("open");
  const [filters, setFilters] = React.useState<TeamWorkFilters>(DEFAULT_TEAM_WORK_FILTERS);
  const { state, retry } = useLoad<WorkData>(
    () => (memberId ? getMemberWork(team.id, memberId, scope) : getTeamWork(team.id, scope)),
    [team.id, memberId, scope],
  );
  const [details, setDetails] = React.useState<Target | null>(null);
  const [editing, setEditing] = React.useState<{ target: Target; current: { status: string; due_at?: string | null } } | null>(null);
  const [moving, setMoving] = React.useState<Target | null>(null);
  const [now] = React.useState(() => new Date());

  const data = state.status === "ready" ? state.data : null;
  const kind: Kind = team.member_role === "telecaller" ? "leads" : "tasks";
  // Loan filters on a Loans team, property filters on a Real Estate team, and
  // a Telecaller team's transactions (minus the parts the Admin hides from
  // Telecallers). Options: the active catalogue plus the loaded rows.
  const signalRows = React.useMemo(
    () => (data ? [...data.leads, ...data.tasks].map(teamSignalValues) : []),
    [data],
  );
  const catalogue = useProductCatalogue(team.business_line === "loans");
  const signalScope = React.useMemo(
    () =>
      lineScope(team.business_line, team.member_role === "telecaller", rowsHiddenTransactionParts(signalRows)),
    [team.business_line, team.member_role, signalRows],
  );
  const signalOptions = React.useMemo(() => leadSignalOptions(catalogue, signalRows), [catalogue, signalRows]);
  // A hidden control never keeps narrowing, and a status the Open view does
  // not offer is not applied there.
  const effective = React.useMemo(() => {
    const openStatuses = kind === "leads" ? OPEN_LEAD : OPEN_TASK;
    const status = scope === "open" && !openStatuses.has(filters.status) ? "all" : filters.status;
    return { ...filters, ...scopedLeadSignalFilters(filters, signalScope), status };
  }, [filters, signalScope, scope, kind]);
  // Open work first (New > Assigned > Working > Converted > Closed > Released), then the soonest follow-up.
  const leads = data
    ? sortLeadsByDefaultOrder(
        filterTeamLeads(data.leads, effective, now),
        (row) => row.status,
        (row) => row.last_call?.follow_up_at,
      )
    : [];
  const tasks = data ? filterTeamTasks(data.tasks, effective, now) : [];
  const total = data ? (kind === "leads" ? data.leads.length : data.tasks.length) : 0;
  const shown = kind === "leads" ? leads.length : tasks.length;
  const showAssignee = !memberId;

  function leadTarget(row: TeamLeadRow): Target {
    return {
      kind: "leads",
      id: row.id,
      label: hiddenLabel(row.hidden_fields, "name", row.name) ?? "This lead",
      holder: row.assigned_to?.staff_profile_uuid ?? memberId,
    };
  }

  function taskTarget(row: TeamTaskRow): Target {
    const client = hiddenLabel(row.hidden_fields, "name", row.lead_name) ?? "the client";
    return {
      kind: "tasks",
      id: row.id,
      label: `${TASK_TYPE_LABEL[row.task_type] ?? "Task"} for ${client}`,
      holder: row.assigned_to?.staff_profile_uuid ?? memberId,
    };
  }

  return (
    <div className="space-y-4">
      <TeamWorkFilterBar
        team={team}
        kind={kind}
        filters={filters}
        onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))}
        scope={scope}
        onScope={(next) => {
          setScope(next);
          // A closed or released status is not offered under Open.
          const openStatuses = kind === "leads" ? OPEN_LEAD : OPEN_TASK;
          if (next === "open" && filters.status !== "all" && !openStatuses.has(filters.status)) {
            setFilters((current) => ({ ...current, status: "all" }));
          }
        }}
        showAssignee={showAssignee}
        signalScope={signalScope}
        signalOptions={signalOptions}
      />
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : !data ? (
        <ListLoadingState rows={4} />
      ) : (
        <>
          <p className="text-sm text-text-secondary" role="status">
            {shown === total ? `${total} ${kind}` : `${shown} of ${total} ${kind}`}
          </p>
          {shown === 0 ? (
            <ListEmptyState
              icon={kind === "leads" ? DASHBOARD_ICONS.leads : DASHBOARD_ICONS.tasks}
              title={total === 0 ? `No ${scope === "open" ? "open " : ""}${kind}` : "Nothing matches these filters"}
            />
          ) : kind === "leads" ? (
            <LeadRows
              rows={leads}
              showAssignee={showAssignee}
              now={now}
              onAction={(action, row) => {
                const target = leadTarget(row);
                if (action === "details") setDetails(target);
                else if (action === "edit") setEditing({ target, current: { status: row.status } });
                else setMoving(target);
              }}
            />
          ) : (
            <TaskRows
              rows={tasks}
              showAssignee={showAssignee}
              now={now}
              onAction={(action, row) => {
                const target = taskTarget(row);
                if (action === "details") setDetails(target);
                else if (action === "edit")
                  setEditing({ target, current: { status: row.status, due_at: row.due_at } });
                else setMoving(target);
              }}
            />
          )}
        </>
      )}

      <DetailDialog team={team} target={details} onClose={() => setDetails(null)} />
      <EditDialog
        team={team}
        target={editing?.target ?? null}
        current={editing?.current ?? null}
        onClose={() => setEditing(null)}
        onDone={() => {
          setEditing(null);
          retry();
        }}
      />
      <MoveDialog
        team={team}
        target={moving}
        onClose={() => setMoving(null)}
        onDone={() => {
          setMoving(null);
          retry();
        }}
      />
    </div>
  );
}
