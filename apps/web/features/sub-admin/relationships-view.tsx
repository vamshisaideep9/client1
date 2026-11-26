"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { useMe } from "@/features/dashboard/me-provider";
import { formatDate } from "@/lib/format";
import {
  ACCESS_LINES, addRelationshipActivity, assignedLines, listRelationshipActivity,
  listRelationshipAgents, type RelationshipActivity, type RelationshipAgent,
} from "@/lib/sub-admin-access";

export function RelationshipsView() {
  const { me } = useMe();
  const [agents, setAgents] = React.useState<RelationshipAgent[]>();
  const [selected, setSelected] = React.useState<RelationshipAgent>();
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    void listRelationshipAgents().then((result) => {
      if (live) {
        if (result.ok) setAgents(result.data);
        else setError(result.error);
      }
    });
    return () => { live = false; };
  }, [attempt]);

  return <DashboardPage>
    <DashboardHeader title="Agent relationships" />
    <DashboardPanel title="Assigned Agents">
      {error ? <div role="alert"><p className="text-sm text-destructive">{error}</p><Button size="sm" variant="outline" onClick={() => { setError(""); setAttempt((value) => value + 1); }}>Retry</Button></div>
        : agents === undefined ? <p role="status" className="text-sm">Loading Agents…</p>
          : agents.length ? <ul className="grid gap-2 md:grid-cols-2">{agents.map((agent) => (
            <li key={agent.id}>
              <button type="button" aria-pressed={selected?.id === agent.id} onClick={() => setSelected(agent)}
                className="w-full rounded-lg border border-border p-3 text-left hover:bg-muted/50 aria-pressed:border-ring aria-pressed:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span className="block font-medium">{agent.name} · {agent.agent_code}</span>
                <span className="block text-xs text-text-secondary">{ACCESS_LINES[agent.business_line]} · {agent.status} · {agent.submitted_leads ?? 0} submitted leads</span>
                <span className="block text-xs text-text-secondary">KYC status {agent.kyc_status ?? "pending"}{agent.approved_at ? ` · Approved ${formatDate(agent.approved_at)}` : ""}</span>
              </button>
            </li>
          ))}</ul> : <p className="text-sm text-text-secondary">No Agents are assigned to you.</p>}
    </DashboardPanel>
    {selected ? <Activity key={selected.id} agent={selected} writable={assignedLines(me?.subAdminAccess, "relationship_manager", "follow_up").includes(selected.business_line)} /> : null}
  </DashboardPage>;
}

function Activity({ agent, writable }: { agent: RelationshipAgent; writable: boolean }) {
  const [items, setItems] = React.useState<RelationshipActivity[]>();
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");
  const [kind, setKind] = React.useState<RelationshipActivity["kind"]>("follow_up");
  const [busy, setBusy] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    void listRelationshipActivity(agent.id).then((result) => {
      if (live) {
        if (result.ok) setItems(result.data);
        else setError(result.error);
      }
    });
    return () => { live = false; };
  }, [agent.id, attempt]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const result = await addRelationshipActivity(agent.id, { kind, note });
    if (result.ok) {
      setItems((previous) => [result.data, ...(previous ?? [])].slice(0, 100));
      setNote("");
    } else setError(result.error);
    setBusy(false);
  }

  return <DashboardPanel title={`Activity for ${agent.name}`}>
    {writable ? <form onSubmit={(event) => void submit(event)} className="mb-4 space-y-2">
      <label className="flex items-center gap-3 text-sm">Activity type
        <select className="h-10 rounded-md border border-input bg-background px-2" value={kind}
          onChange={(event) => setKind(event.target.value === "recommendation" ? "recommendation" : "follow_up")}>
          <option value="follow_up">Follow-up</option><option value="recommendation">Recommendation</option>
        </select>
      </label>
      <label className="block text-sm" htmlFor="relationship-note">Note</label>
      <Textarea id="relationship-note" value={note} maxLength={1000} onChange={(event) => setNote(event.target.value)} required />
      <Button type="submit" disabled={busy || items === undefined || !note.trim()}>{busy ? "Saving…" : "Save activity"}</Button>
    </form> : null}
    {error ? <div role="alert"><p className="text-sm text-destructive">{error}</p>{items === undefined ? <Button size="sm" variant="outline" onClick={() => { setError(""); setAttempt((value) => value + 1); }}>Retry</Button> : null}</div> : null}
    {!items && !error ? <p role="status" className="text-sm">Loading activity…</p> : null}
    {items?.length ? <ol className="divide-y divide-border">{items.map((item) => (
      <li className="py-3" key={item.id}>
        <p className="text-xs font-medium text-text-secondary">{item.kind === "follow_up" ? "Follow-up" : "Recommendation"} · {formatDate(item.created_at)}</p>
        <p className="whitespace-pre-wrap break-words text-sm">{item.note}</p>
      </li>
    ))}</ol> : items ? <p className="text-sm text-text-secondary">No activity recorded.</p> : null}
  </DashboardPanel>;
}
