"use client";

import * as React from "react";
import { ArrowRightLeft, PhoneCall } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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
import { CallLogList } from "@/features/telecaller/telecaller-call-log";
import {
  DISPOSITION_LABEL,
  STATUS_LABEL,
  STATUS_STYLE,
  formatDateTime,
} from "@/features/telecaller/telecaller-lead-status";
import { formatDate } from "@/lib/format";
import { resolveRangePreset, type DateRangeValue } from "@/lib/analytics-range";
import { DateRangePicker } from "@/features/analytics/date-range-picker";
import {
  getMemberAnalytics,
  getMemberWork,
  getMyTeams,
  getTeamLead,
  personName,
  reassignTeamWork,
  teamLabel,
  type StaffTeam,
  type TeamLeadRow,
  type TeamMember,
  type TeamTaskRow,
} from "@/lib/staff-teams-api";
import { cn } from "@/lib/utils";

import { useLoad } from "./use-load";

const TASK_TYPE_LABEL: Record<string, string> = {
  document_collection: "Document collection",
  property_visit: "Property visit",
  background_check: "Background check",
};

const TASK_STATUS_LABEL: Record<string, string> = {
  unassigned: "Unassigned",
  assigned: "Assigned",
  in_progress: "In progress",
  blocked: "Blocked",
  completed: "Completed",
  cancelled: "Cancelled",
};

const OPEN_LEAD = new Set(["assigned", "working"]);
const OPEN_TASK = new Set(["assigned", "in_progress", "blocked"]);

type MoveTarget = { kind: "leads" | "tasks"; id: string; label: string };

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

function MoveDialog({
  team,
  member,
  target,
  onClose,
  onMoved,
}: {
  team: StaffTeam;
  member: TeamMember;
  target: MoveTarget | null;
  onClose: () => void;
  onMoved: () => void;
}) {
  const teammates = team.members.filter(
    (person) => person.staff_profile_uuid !== member.staff_profile_uuid && person.status === "active",
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
    onMoved();
  }

  return (
    <Dialog open={target !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent className="max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Move to a teammate</DialogTitle>
            <DialogDescription>
              {target?.label} moves from {personName(member)} to the person you choose. The call
              history stays with the client.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="move-to">Teammate</Label>
            <Select value={chosen} onValueChange={setChosen} disabled={teammates.length === 0}>
              <SelectTrigger id="move-to">
                <SelectValue
                  placeholder={
                    teammates.length === 0 ? "No other active members" : "Choose a teammate"
                  }
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

function LeadCallsDialog({
  teamId,
  lead,
  onClose,
}: {
  teamId: string;
  lead: TeamLeadRow | null;
  onClose: () => void;
}) {
  const { state, retry } = useLoad(
    () =>
      lead
        ? getTeamLead(teamId, lead.id)
        : Promise.resolve({ ok: false as const, error: "", status: 0 }),
    [teamId, lead?.id],
  );
  const detail = lead && state.status === "ready" && state.data.lead.id === lead.id ? state.data : null;

  return (
    <Dialog open={lead !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{lead?.name ?? "Unnamed client"}</DialogTitle>
          <DialogDescription>
            {lead ? `${lead.mobile} · ${STATUS_LABEL[lead.status] ?? lead.status}` : null}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-4">
          {detail ? (
            <>
              {detail.lead.requests.length > 0 ? (
                <section aria-label="Applications">
                  <h3 className="text-sm font-medium text-text-primary">Applications</h3>
                  <ul className="mt-2 space-y-1 text-sm">
                    {detail.lead.requests.map((request) => (
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
              <section aria-label="Call log">
                <h3 className="mb-3 text-sm font-medium text-text-primary">Call log</h3>
                <CallLogList activities={detail.activities} requests={[]} />
              </section>
            </>
          ) : state.status === "error" && lead ? (
            <FetchError status={state.code} message={state.error} onRetry={retry} />
          ) : (
            <ListLoadingState rows={3} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LeadList({
  leads,
  onCalls,
  onMove,
}: {
  leads: TeamLeadRow[];
  onCalls: (lead: TeamLeadRow) => void;
  onMove: (lead: TeamLeadRow) => void;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Leads">
      {leads.map((lead) => {
        const latest = lead.requests[0];
        const name = lead.name ?? "Unnamed client";
        return (
          <li key={lead.id} className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text-primary">{name}</span>
                <StatusPill status={lead.status} label={STATUS_LABEL[lead.status] ?? lead.status} />
              </p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {lead.mobile}
                {latest ? ` · ${latest.title}` : ""}
              </p>
              <p className="mt-0.5 text-xs text-text-secondary">
                {lead.last_call
                  ? `Last call ${formatDateTime(lead.last_call.created_at)}: ${DISPOSITION_LABEL[lead.last_call.disposition] ?? lead.last_call.disposition}`
                  : "Not called yet"}
                {lead.last_call?.follow_up_at
                  ? ` · follow-up ${formatDateTime(lead.last_call.follow_up_at)}`
                  : ""}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => onCalls(lead)}>
                <PhoneCall /> Calls<span className="sr-only"> for {name}</span>
              </Button>
              {OPEN_LEAD.has(lead.status) ? (
                <Button type="button" variant="outline" size="sm" onClick={() => onMove(lead)}>
                  <ArrowRightLeft /> Move<span className="sr-only"> {name}</span>
                </Button>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function TaskList({ tasks, onMove }: { tasks: TeamTaskRow[]; onMove: (task: TeamTaskRow) => void }) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Tasks">
      {tasks.map((task) => {
        const type = TASK_TYPE_LABEL[task.task_type] ?? task.task_type;
        return (
          <li key={task.id} className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text-primary">{type}</span>
                <Badge variant="outline">{TASK_STATUS_LABEL[task.status] ?? task.status}</Badge>
              </p>
              <p className="mt-0.5 text-sm text-text-secondary">
                {task.lead_name ?? "Unnamed client"} ·{" "}
                {task.due_at ? `due ${formatDate(task.due_at)}` : "no due date"}
              </p>
            </div>
            {OPEN_TASK.has(task.status) ? (
              <Button type="button" variant="outline" size="sm" onClick={() => onMove(task)}>
                <ArrowRightLeft /> Move<span className="sr-only"> {type}</span>
              </Button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function WorkPanel({ team, member }: { team: StaffTeam; member: TeamMember }) {
  const [scope, setScope] = React.useState<"open" | "all">("open");
  const { state, retry } = useLoad(
    () => getMemberWork(team.id, member.staff_profile_uuid, scope),
    [team.id, member.staff_profile_uuid, scope],
  );
  const [moving, setMoving] = React.useState<MoveTarget | null>(null);
  const [calls, setCalls] = React.useState<TeamLeadRow | null>(null);
  const data = state.status === "ready" ? state.data : null;
  const noun = team.member_role === "telecaller" ? "leads" : "tasks";

  return (
    <DashboardPanel
      title={team.member_role === "telecaller" ? "Leads" : "Field tasks"}
      description={`${personName(member)}'s ${noun}, most recently updated first.`}
      action={
        <ToggleGroup
          type="single"
          value={scope}
          onValueChange={(value) => value && setScope(value as "open" | "all")}
          aria-label={`Which ${noun}`}
        >
          <ToggleGroupItem value="open" className="px-3">
            Open
          </ToggleGroupItem>
          <ToggleGroupItem value="all" className="px-3">
            All
          </ToggleGroupItem>
        </ToggleGroup>
      }
    >
      {state.status === "error" ? (
        <FetchError status={state.code} message={state.error} onRetry={retry} />
      ) : !data ? (
        <ListLoadingState rows={4} />
      ) : data.kind === "leads" ? (
        data.leads.length === 0 ? (
          <ListEmptyState icon={DASHBOARD_ICONS.leads} title={`No ${scope === "open" ? "open " : ""}leads`} />
        ) : (
          <LeadList
            leads={data.leads}
            onCalls={setCalls}
            onMove={(lead) =>
              setMoving({ kind: "leads", id: lead.id, label: lead.name ?? "This lead" })
            }
          />
        )
      ) : data.tasks.length === 0 ? (
        <ListEmptyState icon={DASHBOARD_ICONS.tasks} title={`No ${scope === "open" ? "open " : ""}tasks`} />
      ) : (
        <TaskList
          tasks={data.tasks}
          onMove={(task) =>
            setMoving({
              kind: "tasks",
              id: task.id,
              label: `The ${(TASK_TYPE_LABEL[task.task_type] ?? "field").toLowerCase()} task`,
            })
          }
        />
      )}

      <MoveDialog
        team={team}
        member={member}
        target={moving}
        onClose={() => setMoving(null)}
        onMoved={() => {
          setMoving(null);
          retry();
        }}
      />
      <LeadCallsDialog teamId={team.id} lead={calls} onClose={() => setCalls(null)} />
    </DashboardPanel>
  );
}

function MemberAnalytics({ teamId, memberId }: { teamId: string; memberId: string }) {
  const [range, setRange] = React.useState<DateRangeValue>(() =>
    resolveRangePreset("last_30_days", new Date()),
  );
  const { state, retry } = useLoad(
    () => getMemberAnalytics(teamId, memberId, range),
    [teamId, memberId, range],
  );
  return (
    <section aria-label="Analytics" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-heading text-lg font-semibold text-brand-heading">Analytics</h2>
        <DateRangePicker value={range} onChange={setRange} />
      </div>
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
            <WorkPanel team={team} member={member} />
            <MemberAnalytics teamId={team.id} memberId={member.staff_profile_uuid} />
          </div>
        </>
      )}
    </DashboardPage>
  );
}
