"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ACCESS_LINES, ACTION_LABELS, ASSIGNMENTS, searchRelationshipAgents, type AccessLine, type Assignment, type RelationshipAgent, type SubAdminGrant } from "@/lib/sub-admin-access";

const assignments = Object.keys(ASSIGNMENTS) as Assignment[];
const lines = Object.keys(ACCESS_LINES) as AccessLine[];

function AgentAssignments({ grant, onChange }: { grant: SubAdminGrant; onChange: (grant: SubAdminGrant) => void }) {
  const [query, setQuery] = React.useState("");
  const [options, setOptions] = React.useState<RelationshipAgent[]>([]);
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const selected = grant.agent_profile_ids ?? [];
  const inputId = React.useId();

  async function search() {
    setBusy(true);
    const result = await searchRelationshipAgents(grant.business_line, query.trim());
    setOptions(result.ok ? result.data : []);
    setMessage(result.ok ? (result.data.length ? "" : "No matching Agents.") : result.error);
    setBusy(false);
  }

  return (
    <div className="space-y-2 pl-5">
      <label className="text-xs font-medium" htmlFor={inputId}>Find an Agent by name or code</label>
      <div className="flex gap-2">
        <Input id={inputId} value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} />
        <Button type="button" variant="outline" onClick={() => void search()} disabled={busy || query.trim().length < 2}>
          {busy ? "Searching…" : "Search"}
        </Button>
      </div>
      {message ? <p role="status" className="text-xs text-text-secondary">{message}</p> : null}
      {options.map((agent) => (
        <label key={agent.id} className="flex min-h-9 items-center gap-2 text-sm">
          <input type="checkbox" checked={selected.includes(agent.id)} disabled={selected.length >= 100 && !selected.includes(agent.id)}
            onChange={(event) => onChange({ ...grant, agent_profile_ids: event.target.checked ? [...selected, agent.id] : selected.filter((id) => id !== agent.id) })} />
          {agent.name} · {agent.agent_code}
        </label>
      ))}
      {selected.length ? (
        <div className="flex items-center gap-3 text-xs">
          <span>{selected.length} assigned</span>
          <Button type="button" size="sm" variant="ghost" onClick={() => onChange({ ...grant, agent_profile_ids: [] })}>Clear Agents</Button>
        </div>
      ) : null}
    </div>
  );
}

export function SubAdminGrantEditor({ grants, onChange, disabled }: {
  grants: SubAdminGrant[]; onChange: (grants: SubAdminGrant[]) => void; disabled?: boolean;
}) {
  function save(assignment: Assignment, line: AccessLine, grant?: SubAdminGrant) {
    const remaining = grants.filter((item) => item.assignment !== assignment || item.business_line !== line);
    onChange(grant ? [...remaining, grant] : remaining);
  }

  return (
    <fieldset className="space-y-3" disabled={disabled}>
      <legend className="mb-2 text-sm font-semibold">Dashboard access</legend>
      <div className="grid items-start gap-2 sm:grid-cols-2">
        {assignments.map((assignment) => (
          <fieldset key={assignment} className="space-y-1 rounded-lg border border-border px-3 py-2">
            <legend className="px-1 text-sm font-medium">{ASSIGNMENTS[assignment].label}</legend>
            {lines.map((line) => {
              const grant = grants.find((item) => item.assignment === assignment && item.business_line === line);
              return (
                <div key={line}>
                  <label className="flex min-h-9 items-center gap-2 text-sm">
                    <input type="checkbox" checked={Boolean(grant)}
                      onChange={(event) => save(assignment, line, event.target.checked ? { assignment, business_line: line, actions: ["view", ...ASSIGNMENTS[assignment].actions] } : undefined)} />
                    {ACCESS_LINES[line]}
                  </label>
                  {grant ? ASSIGNMENTS[assignment].actions.map((action) => (
                    <label key={action} className="flex min-h-8 items-center gap-2 pl-5 text-xs">
                      <input type="checkbox" checked={grant.actions.includes(action)} onChange={(event) => save(assignment, line, {
                        ...grant, actions: event.target.checked ? [...grant.actions, action] : grant.actions.filter((value) => value !== action),
                      })} />
                      {ACTION_LABELS[action]}
                    </label>
                  )) : null}
                  {grant && assignment === "relationship_manager" ? <AgentAssignments grant={grant} onChange={(next) => save(assignment, line, next)} /> : null}
                </div>
              );
            })}
          </fieldset>
        ))}
      </div>
      <div aria-live="polite" className="rounded-lg bg-muted/50 p-3 text-sm">
        <p className="font-medium">Dashboard preview</p>
        {grants.length ? (
          <ul className="mt-1 space-y-1 text-xs text-text-secondary">
            {grants.map((grant) => <li key={`${grant.assignment}-${grant.business_line}`}>{ASSIGNMENTS[grant.assignment].label} · {ACCESS_LINES[grant.business_line]} · {grant.actions.map((action) => ACTION_LABELS[action]).join(", ")}</li>)}
          </ul>
        ) : <p className="mt-1 text-xs text-text-secondary">No operational modules selected.</p>}
      </div>
    </fieldset>
  );
}
