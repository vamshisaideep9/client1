"use client";

import * as React from "react";
import { Maximize2, SlidersHorizontal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { CLOSE_BUTTON_CLASS } from "@/components/ui/close-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { optionsFromLabels } from "@/features/dashboard/filter-options";
import { DateRangeFields, FilterSelect } from "@/features/dashboard/filter-select";
import type { AdminPendingItem } from "@/lib/admin-api";
import { PANEL_DIALOG_FILTERED_CLASS } from "@/features/dashboard/workspace-dialog";
import { cn } from "@/lib/utils";

import { filterPendingReview, type PendingReviewFilters } from "./admin-home-pending-review";
import { PendingReviewList, REVIEW_KIND_LABEL, REVIEW_LINE_LABEL } from "./pending-review-list";

/** Shared maker-checker decision surface. The API remains the authorization wall. */
export function PendingDecisionDialog({ title, description, children, onClose, onApprove, onReject }: {
  title: string; description: string; children: React.ReactNode; onClose: () => void;
  onApprove: () => Promise<string | null>; onReject: (note: string) => Promise<string | null>;
}) {
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const noteId = React.useId();
  async function decide(approve: boolean) {
    if (busy) return;
    if (!approve && !note.trim()) { setError("Add feedback before rejecting."); return; }
    setBusy(true); setError(null);
    const message = approve ? await onApprove() : await onReject(note.trim());
    if (message) { setError(message); setBusy(false); }
  }
  return <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
    <DialogContent preventOutsideClose>
      <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
      {children}
      <div className="grid gap-2"><Label htmlFor={noteId}>Feedback (required to reject)</Label>
        <Textarea id={noteId} value={note} onChange={(event) => { setNote(event.target.value); setError(null); }} maxLength={500} />
      </div>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide(false)}>Reject proposal</Button>
        <Button disabled={busy} onClick={() => void decide(true)}>{busy ? "Saving…" : "Approve proposal"}</Button>
      </div>
    </DialogContent>
  </Dialog>;
}

const EMPTY_FILTERS: PendingReviewFilters = {
  search: "",
  kind: "all",
  businessLine: "all",
  submittedFrom: "",
  submittedTo: "",
};

export function PendingReviewDialog({
  items,
  total,
}: {
  items: AdminPendingItem[];
  total: number;
}) {
  const [open, setOpen] = React.useState(false);
  const [filters, setFilters] = React.useState<PendingReviewFilters>(EMPTY_FILTERS);
  const filteredItems = React.useMemo(() => filterPendingReview(items, filters), [filters, items]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Maximize2 className="h-4 w-4" aria-hidden="true" />
          Review filters
        </Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton={false}
        className={PANEL_DIALOG_FILTERED_CLASS}
      >
        <DialogHeader className="pr-12">
          <DialogTitle>Waiting on you</DialogTitle>
          <DialogDescription>
            Filter the {items.length} newest loaded review items. {total > items.length ? `The dashboard preview contains the newest ${items.length} of ${total} pending items.` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 rounded-xl border border-border bg-muted/20 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <Input
            aria-label="Search review items"
            placeholder="Search title"
            value={filters.search}
            maxLength={100}
            onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
          />
          <FilterSelect
            label="Review type"
            ariaLabel="Filter review items by type"
            value={filters.kind ?? "all"}
            options={optionsFromLabels(REVIEW_KIND_LABEL)}
            onValueChange={(kind) => setFilters((current) => ({ ...current, kind: kind as PendingReviewFilters["kind"] }))}
          />
          <FilterSelect
            label="Business line"
            ariaLabel="Filter review items by business line"
            value={filters.businessLine ?? "all"}
            options={optionsFromLabels(REVIEW_LINE_LABEL)}
            onValueChange={(businessLine) => setFilters((current) => ({ ...current, businessLine: businessLine as PendingReviewFilters["businessLine"] }))}
          />
          <DateRangeFields
            from={filters.submittedFrom ?? ""}
            to={filters.submittedTo ?? ""}
            fromLabel="Review items submitted from"
            toLabel="Review items submitted to"
            onFromChange={(submittedFrom) => setFilters((current) => ({ ...current, submittedFrom }))}
            onToChange={(submittedTo) => setFilters((current) => ({ ...current, submittedTo }))}
          />
          <Button className="sm:col-span-2 lg:col-span-3 xl:col-span-5" variant="outline" onClick={() => setFilters(EMPTY_FILTERS)}>
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
            Clear all
          </Button>
        </div>

        <div className="min-h-0 overflow-y-auto pr-1">
          <p className="mb-3 text-sm text-text-secondary">
            {filteredItems.length} {filteredItems.length === 1 ? "item" : "items"} shown
          </p>
          <PendingReviewList items={filteredItems} emptyMessage="No loaded review items match these filters." />
        </div>

        <DialogClose asChild>
          <button
            type="button"
            aria-label="Close review filters"
            className={cn("absolute top-3 right-3", CLOSE_BUTTON_CLASS)}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </DialogClose>
      </DialogContent>
    </Dialog>
  );
}
