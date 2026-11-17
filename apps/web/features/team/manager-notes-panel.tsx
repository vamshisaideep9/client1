import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { formatDateTime } from "@/features/telecaller/telecaller-lead-status";
import type { components } from "@contracts/generated/schema";

export type ManagerNote = components["schemas"]["ManagerNoteRead"];

/** Read-only notes a Sub Admin manager left on this lead or task (CS-020). */
export function ManagerNotesList({ notes }: { notes: readonly ManagerNote[] }) {
  if (notes.length === 0) return <p className="text-sm text-text-secondary">No notes yet.</p>;
  return (
    <ol className="space-y-3" aria-label="Manager notes">
      {notes.map((note) => (
        <li key={note.id} className="rounded-lg border border-border bg-background p-3">
          <p className="whitespace-pre-line text-sm text-text-primary">{note.body}</p>
          <p className="mt-1.5 text-xs text-text-secondary">
            {note.author_name} · {formatDateTime(note.created_at)}
            {note.follow_up_at ? (
              <span className="ml-1 font-medium text-warning">
                · Follow up by {formatDateTime(note.follow_up_at)}
              </span>
            ) : null}
          </p>
        </li>
      ))}
    </ol>
  );
}

/** Shown on the member's own lead or task page; hidden when there are none. */
export function ManagerNotesPanel({ notes }: { notes: readonly ManagerNote[] | undefined }) {
  if (!notes || notes.length === 0) return null;
  return (
    <DashboardPanel
      title="Notes from your manager"
      description="Read-only. Reply by calling the client or updating the work as usual."
    >
      <ManagerNotesList notes={notes} />
    </DashboardPanel>
  );
}
