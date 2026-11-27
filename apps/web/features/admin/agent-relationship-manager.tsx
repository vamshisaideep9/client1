"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  listRelationshipManagerOptions,
  setAgentRelationshipManager,
  type RelationshipManager,
  type RelationshipManagerOption,
} from "@/lib/sub-admin-access";

const NONE = "none";

export function relationshipManagerText(manager: RelationshipManager | null | undefined): string {
  if (!manager) return "Not assigned";
  return manager.name ? `${manager.name} · ${manager.staff_code}` : manager.staff_code;
}

/**
 * An approved Agent's one Relationship Manager with a "Change" dialog. Only
 * the Main Admin can change it; the API refuses everyone else and the dialog
 * shows that refusal.
 */
export function AgentRelationshipManagerField({
  agentProfileId,
  agentName,
  manager,
  onChanged,
}: {
  agentProfileId: string;
  agentName: string;
  manager: RelationshipManager | null | undefined;
  onChanged: (manager: RelationshipManager | null) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [options, setOptions] = React.useState<RelationshipManagerOption[]>();
  const [error, setError] = React.useState("");
  const [choice, setChoice] = React.useState<string>(NONE);
  const [saving, setSaving] = React.useState(false);
  const groupId = React.useId();

  async function openDialog() {
    setOpen(true);
    setOptions(undefined);
    setError("");
    setChoice(manager?.staff_profile_id ?? NONE);
    const result = await listRelationshipManagerOptions(agentProfileId);
    if (result.ok) setOptions(result.data);
    else setError(result.error);
  }

  async function save() {
    setSaving(true);
    const result = await setAgentRelationshipManager(agentProfileId, choice === NONE ? null : choice);
    setSaving(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onChanged(result.data.relationship_manager ?? null);
    toast.success(
      result.data.relationship_manager
        ? `${relationshipManagerText(result.data.relationship_manager)} is now ${agentName}'s Relationship Manager`
        : `${agentName} has no Relationship Manager now`,
    );
    setOpen(false);
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="min-w-0 break-words font-medium text-text-primary">{relationshipManagerText(manager)}</span>
      <Button type="button" size="sm" variant="outline" onClick={() => void openDialog()}>
        Change
      </Button>
      <Dialog open={open} onOpenChange={(next) => !saving && setOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Relationship Manager for {agentName}</DialogTitle>
            <DialogDescription>
              An Agent has one Relationship Manager. Choosing someone else moves the Agent off the current one.
            </DialogDescription>
          </DialogHeader>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          {options === undefined && !error ? (
            <p role="status" className="flex items-center gap-2 text-sm text-text-secondary">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading Relationship Managers…
            </p>
          ) : null}
          {options ? (
            <fieldset className="space-y-1" aria-describedby={`${groupId}-hint`}>
              <legend className="sr-only">Relationship Manager</legend>
              <p id={`${groupId}-hint`} className="text-xs text-text-secondary">
                Sub Admins with Relationship Manager access on this Agent&apos;s department.
              </p>
              <label className="flex min-h-11 items-center gap-3 rounded-md px-2 text-sm hover:bg-muted/50">
                <input type="radio" name={groupId} value={NONE} checked={choice === NONE} onChange={() => setChoice(NONE)} />
                No Relationship Manager
              </label>
              {options.map((option) => (
                <label key={`${option.staff_profile_id}-${option.business_line}`}
                  className="flex min-h-11 items-center gap-3 rounded-md px-2 text-sm hover:bg-muted/50">
                  <input type="radio" name={groupId} value={option.staff_profile_id}
                    checked={choice === option.staff_profile_id} onChange={() => setChoice(option.staff_profile_id)} />
                  <span className="min-w-0">
                    <span className="block font-medium">{option.name ?? option.staff_code}</span>
                    <span className="block text-xs text-text-secondary">
                      {option.staff_code} · {option.agent_count} {option.agent_count === 1 ? "Agent" : "Agents"}
                      {option.current ? " · current" : ""}
                    </span>
                  </span>
                </label>
              ))}
              {options.length === 0 ? (
                <p className="text-sm text-text-secondary">
                  No Sub Admin has Relationship Manager access on this department yet. Give one access in Users first.
                </p>
              ) : null}
            </fieldset>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="button" disabled={saving || options === undefined || choice === (manager?.staff_profile_id ?? NONE)}
              onClick={() => void save()}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
