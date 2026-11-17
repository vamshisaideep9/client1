"use client";

import * as React from "react";
import { History, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  CONTACT_FIELD_LABEL,
  CONTACT_METHOD_LABEL,
  getContactHistory,
  type ContactHistoryEntry,
} from "@/lib/contact-change";

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

// CS-025 permanent contact history (platform Admin only; every open is
// audited server-side). Shows old and new values, how the change was made,
// the proof category and reference, and who approved it.
export function ContactHistoryButton({
  authUserUuid,
  name,
  size = "sm",
}: {
  authUserUuid: string;
  name: string;
  size?: "sm" | "default";
}) {
  const [open, setOpen] = React.useState(false);
  const [entries, setEntries] = React.useState<ContactHistoryEntry[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    let active = true;
    setEntries(null);
    setError(null);
    void getContactHistory(authUserUuid).then((res) => {
      if (!active) return;
      if (res.ok) setEntries(res.data);
      else setError(res.error);
    });
    return () => {
      active = false;
    };
  }, [open, authUserUuid]);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size={size}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
      >
        <History className="h-4 w-4" aria-hidden="true" />
        Contact history
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Contact history</DialogTitle>
            <DialogDescription>
              {name || "This account"}: every phone and email change. Visible to platform Admins
              only; opening it is recorded in the audit log.
            </DialogDescription>
          </DialogHeader>
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : entries === null ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-brand-link" aria-label="Loading" />
            </div>
          ) : entries.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-5 text-sm text-text-secondary">
              No phone or email changes recorded.
            </p>
          ) : (
            <ol className="max-h-[60vh] space-y-2 overflow-y-auto overscroll-contain pr-1">
              {entries.map((entry) => (
                <li key={entry.id} className="rounded-xl border border-border bg-card p-3 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium text-text-primary">
                      {CONTACT_FIELD_LABEL[entry.field]}
                    </span>
                    <time className="text-xs tabular-nums text-text-secondary" dateTime={entry.changed_at}>
                      {formatWhen(entry.changed_at)}
                    </time>
                  </div>
                  <p className="mt-1 break-all text-text-primary">
                    <span className="text-text-secondary">{entry.old_value ?? "None"}</span>
                    {" → "}
                    {entry.new_value}
                  </p>
                  <p className="mt-1 text-xs text-text-secondary">
                    {CONTACT_METHOD_LABEL[entry.method]}
                    {entry.proof_category ? ` · proof: ${entry.proof_category.replaceAll("_", " ")}` : ""}
                    {entry.proof_reference ? ` · ref: ${entry.proof_reference}` : ""}
                    {entry.approved_by_name ? ` · approved by ${entry.approved_by_name}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
