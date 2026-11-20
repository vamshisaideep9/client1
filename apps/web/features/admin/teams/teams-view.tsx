"use client";

import * as React from "react";
import { Archive, Pencil, Plus, UserPlus, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DashboardHeader,
  DashboardPage,
  DashboardPanel,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import {
  TEAM_LINE_LABEL,
  TEAM_ROLE_LABEL,
  addTeamMember,
  createTeam,
  getTeamEligible,
  listTeams,
  personName,
  removeTeamMember,
  updateTeam,
  type StaffTeam,
  type StaffTeamList,
  type TeamLine,
  type TeamMemberRole,
  type TeamPerson,
} from "@/lib/staff-teams-api";

const LINES: TeamLine[] = ["loans", "real_estate"];
const ROLES: TeamMemberRole[] = ["telecaller", "employee"];

type State =
  | { status: "loading" }
  | { status: "ready"; data: StaffTeamList }
  | { status: "error"; error: string; code: number | null };

function personOption(person: TeamPerson): string {
  return `${personName(person)} · ${person.staff_code}`;
}

type FormMode = { kind: "create" } | { kind: "edit"; team: StaffTeam };

function TeamFormDialog({
  mode,
  onClose,
  onSaved,
}: {
  mode: FormMode | null;
  onClose: () => void;
  onSaved: (team: StaffTeam) => void;
}) {
  const editing = mode?.kind === "edit" ? mode.team : null;
  const [name, setName] = React.useState("");
  const [line, setLine] = React.useState<TeamLine>("loans");
  const [role, setRole] = React.useState<TeamMemberRole>("telecaller");
  const [manager, setManager] = React.useState<string | undefined>();
  const [managers, setManagers] = React.useState<TeamPerson[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!mode) return;
    setError(null);
    setName(editing?.name ?? "");
    setLine(editing?.business_line ?? "loans");
    setRole(editing?.member_role ?? "telecaller");
    setManager(editing?.manager.staff_profile_uuid);
  }, [mode, editing]);

  React.useEffect(() => {
    if (!mode) return;
    let active = true;
    setManagers(null);
    void getTeamEligible(line, role).then((res) => {
      if (!active) return;
      const free = res.ok ? res.data.managers : [];
      // The current manager is "busy" with this very team; keep them choosable.
      setManagers(editing ? [editing.manager, ...free] : free);
      if (!res.ok) setError(res.error);
    });
    return () => {
      active = false;
    };
  }, [mode, line, role, editing]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return setError("Give the team a name.");
    if (!manager) return setError("Choose the Sub Admin who manages this team.");
    setSaving(true);
    setError(null);
    const res = editing
      ? await updateTeam(editing.id, {
          name: name.trim(),
          manager_staff_profile_uuid: manager,
          archive: false,
        })
      : await createTeam({
          name: name.trim(),
          business_line: line,
          member_role: role,
          manager_staff_profile_uuid: manager,
        });
    setSaving(false);
    if (!res.ok) return setError(res.error);
    toast.success(editing ? "Team updated" : "Team created");
    onSaved(res.data);
  }

  return (
    <Dialog open={mode !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent preventOutsideClose className="max-w-lg">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? "Edit team" : "New team"}</DialogTitle>
            <DialogDescription>
              {editing
                ? `${TEAM_LINE_LABEL[editing.business_line]} · ${TEAM_ROLE_LABEL[editing.member_role]}. The line and role of a team cannot change.`
                : "A team is one business line and one role. Its manager sees the team's work and can move it between members."}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="team-name">Team name</Label>
              <Input
                id="team-name"
                value={name}
                maxLength={80}
                onChange={(event) => setName(event.target.value)}
                autoComplete="off"
              />
            </div>
            {editing ? null : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="team-line">Business line</Label>
                  <Select
                    value={line}
                    onValueChange={(value) => {
                      setLine(value as TeamLine);
                      setManager(undefined);
                    }}
                  >
                    <SelectTrigger id="team-line">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LINES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {TEAM_LINE_LABEL[value]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="team-role">Members</Label>
                  <Select value={role} onValueChange={(value) => setRole(value as TeamMemberRole)}>
                    <SelectTrigger id="team-role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {TEAM_ROLE_LABEL[value]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="team-manager">Manager (Sub Admin)</Label>
              <Select value={manager} onValueChange={setManager} disabled={managers === null}>
                <SelectTrigger id="team-manager">
                  <SelectValue
                    placeholder={managers === null ? "Loading Sub Admins…" : "Choose a Sub Admin"}
                  />
                </SelectTrigger>
                <SelectContent>
                  {(managers ?? []).map((person) => (
                    <SelectItem key={person.staff_profile_uuid} value={person.staff_profile_uuid}>
                      {personOption(person)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {managers !== null && managers.length === 0 ? (
                <p className="text-xs text-text-secondary">
                  Every active Sub Admin already manages a {TEAM_LINE_LABEL[line]} team.
                </p>
              ) : null}
            </div>
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
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : editing ? "Save changes" : "Create team"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AddMemberDialog({
  team,
  onClose,
  onSaved,
}: {
  team: StaffTeam | null;
  onClose: () => void;
  onSaved: (team: StaffTeam) => void;
}) {
  const [people, setPeople] = React.useState<TeamPerson[] | null>(null);
  const [chosen, setChosen] = React.useState<string | undefined>();
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!team) return;
    let active = true;
    setPeople(null);
    setChosen(undefined);
    setError(null);
    void getTeamEligible(team.business_line, team.member_role).then((res) => {
      if (!active) return;
      setPeople(res.ok ? res.data.members : []);
      if (!res.ok) setError(res.error);
    });
    return () => {
      active = false;
    };
  }, [team]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!team || !chosen) return setError("Choose someone to add.");
    setSaving(true);
    const res = await addTeamMember(team.id, chosen);
    setSaving(false);
    if (!res.ok) return setError(res.error);
    toast.success("Member added");
    onSaved(res.data);
  }

  const roleWord = team?.member_role === "employee" ? "Employee" : "Telecaller";
  return (
    <Dialog open={team !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent preventOutsideClose className="max-w-md">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Add to {team?.name}</DialogTitle>
            <DialogDescription>
              Active {team ? TEAM_LINE_LABEL[team.business_line] : ""} {roleWord}s who are not
              in another {team ? TEAM_LINE_LABEL[team.business_line] : ""} team.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="team-member">{roleWord}</Label>
            <Select value={chosen} onValueChange={setChosen} disabled={!people?.length}>
              <SelectTrigger id="team-member">
                <SelectValue
                  placeholder={
                    people === null
                      ? "Loading…"
                      : people.length === 0
                        ? `No ${roleWord.toLowerCase()}s available`
                        : `Choose a ${roleWord.toLowerCase()}`
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {(people ?? []).map((person) => (
                  <SelectItem key={person.staff_profile_uuid} value={person.staff_profile_uuid}>
                    {personOption(person)}
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
              {saving ? "Adding…" : "Add member"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TeamCard({
  team,
  canEdit,
  onEdit,
  onAdd,
  onRemove,
  onArchive,
}: {
  team: StaffTeam;
  canEdit: boolean;
  onEdit: () => void;
  onAdd: () => void;
  onRemove: (person: TeamPerson) => void;
  onArchive: () => void;
}) {
  const managerInactive = team.manager.status !== "active";
  return (
    <article className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-heading text-base font-semibold text-brand-heading">{team.name}</h3>
          <p className="mt-0.5 text-sm text-text-secondary">
            Managed by <span className="text-text-primary">{personName(team.manager)}</span>
            {managerInactive ? (
              <Badge variant="outline" className="ml-2">
                Manager inactive
              </Badge>
            ) : null}
          </p>
        </div>
        <Badge variant="secondary">{TEAM_ROLE_LABEL[team.member_role]}</Badge>
      </div>

      {team.members.length === 0 ? (
        <p className="mt-4 text-sm text-text-secondary">No members yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-border rounded-lg border border-border" aria-label={`${team.name} members`}>
          {team.members.map((member) => (
            <li key={member.staff_profile_uuid} className="flex min-h-11 items-center gap-3 px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                {personName(member)}
                <span className="ml-2 text-xs text-text-secondary">{member.staff_code}</span>
              </span>
              {member.status !== "active" ? <Badge variant="outline">Inactive</Badge> : null}
              {canEdit ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${personName(member)} from ${team.name}`}
                  onClick={() => onRemove(member)}
                >
                  <X />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {canEdit ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onAdd}>
            <UserPlus /> Add member
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            <Pencil /> Edit
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onArchive}>
            <Archive /> Archive
          </Button>
        </div>
      ) : null}
    </article>
  );
}

export function TeamsView() {
  const [state, setState] = React.useState<State>({ status: "loading" });
  const [reloadKey, setReloadKey] = React.useState(0);
  const [formMode, setFormMode] = React.useState<FormMode | null>(null);
  const [addingTo, setAddingTo] = React.useState<StaffTeam | null>(null);
  const { confirm, confirmDialog } = useConfirm();

  React.useEffect(() => {
    let active = true;
    void listTeams().then((res) => {
      if (!active) return;
      setState(
        res.ok
          ? { status: "ready", data: res.data }
          : { status: "error", error: res.error, code: res.status },
      );
    });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const data = state.status === "ready" ? state.data : null;
  const canEdit = data?.can_edit ?? false;

  function upsert(team: StaffTeam) {
    setState((current) => {
      if (current.status !== "ready") return current;
      const others = current.data.teams.filter((existing) => existing.id !== team.id);
      const teams = team.archived_at ? others : [...others, team];
      teams.sort((a, b) => a.name.localeCompare(b.name));
      return { status: "ready", data: { ...current.data, teams } };
    });
  }

  async function remove(team: StaffTeam, person: TeamPerson) {
    const ok = await confirm({
      title: `Remove ${personName(person)}?`,
      description: `${team.manager.first_name} will no longer see their work. Their leads and tasks stay with them.`,
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!ok) return;
    const res = await removeTeamMember(team.id, person.staff_profile_uuid);
    if (!res.ok) return void toast.error("Could not remove member", { description: res.error });
    toast.success("Member removed");
    upsert(res.data);
  }

  async function archive(team: StaffTeam) {
    const ok = await confirm({
      title: `Archive ${team.name}?`,
      description: `${personName(team.manager)} loses access to this team's work at once, and its members become free to join another team. This cannot be undone.`,
      confirmLabel: "Archive team",
      destructive: true,
    });
    if (!ok) return;
    const res = await updateTeam(team.id, { archive: true });
    if (!res.ok) return void toast.error("Could not archive team", { description: res.error });
    toast.success("Team archived");
    upsert(res.data);
  }

  return (
    <DashboardPage>
      <DashboardHeader
        title="Teams"
        description="Sub Admins who manage Telecallers or Employees in one business line. A manager sees their team's work and can move it between members; new work is still shared across the whole line."
        actions={
          canEdit ? (
            <Button type="button" onClick={() => setFormMode({ kind: "create" })}>
              <Plus /> New team
            </Button>
          ) : null
        }
      />

      {state.status === "error" ? (
        <FetchError
          status={state.code}
          message={state.error}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      ) : !data ? (
        <ListLoadingState rows={4} />
      ) : (
        <div className="space-y-5">
          {canEdit ? null : (
            <p className="rounded-lg border border-border bg-muted px-4 py-3 text-sm text-text-secondary">
              Only the Main Admin can create or change teams.
            </p>
          )}
          {LINES.map((line) => {
            const teams = data.teams.filter((team) => team.business_line === line);
            return (
              <DashboardPanel
                key={line}
                title={TEAM_LINE_LABEL[line]}
                description={
                  teams.length === 1 ? "1 team" : `${teams.length} teams`
                }
              >
                {teams.length === 0 ? (
                  <p className="py-4 text-sm text-text-secondary">
                    No {TEAM_LINE_LABEL[line]} teams yet.
                  </p>
                ) : (
                  <div className="grid gap-4 lg:grid-cols-2">
                    {teams.map((team) => (
                      <TeamCard
                        key={team.id}
                        team={team}
                        canEdit={canEdit}
                        onEdit={() => setFormMode({ kind: "edit", team })}
                        onAdd={() => setAddingTo(team)}
                        onRemove={(person) => void remove(team, person)}
                        onArchive={() => void archive(team)}
                      />
                    ))}
                  </div>
                )}
              </DashboardPanel>
            );
          })}
        </div>
      )}

      <TeamFormDialog
        mode={formMode}
        onClose={() => setFormMode(null)}
        onSaved={(team) => {
          setFormMode(null);
          upsert(team);
        }}
      />
      <AddMemberDialog
        team={addingTo}
        onClose={() => setAddingTo(null)}
        onSaved={(team) => {
          setAddingTo(null);
          upsert(team);
        }}
      />
      {confirmDialog}
    </DashboardPage>
  );
}
