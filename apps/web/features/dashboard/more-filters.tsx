"use client";

import * as React from "react";
import { SlidersHorizontal, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

import type { ActiveFilterChip } from "./filter-options";

/** One titled section inside "More filters", e.g. Lead / Product / Money. */
export type MoreFilterGroup = { title: string; content: React.ReactNode };

/** "More filters" or "More filters (2)": the count is the active hidden filters. */
export function moreFiltersLabel(activeCount: number): string {
  return activeCount > 0 ? `More filters (${activeCount})` : "More filters";
}

function GroupList({ groups }: { groups: readonly MoreFilterGroup[] }) {
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <fieldset key={group.title} className="min-w-0 space-y-2">
          <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">
            {group.title}
          </legend>
          <div className="grid gap-2 sm:grid-cols-2 [&_[data-slot=select-trigger]]:w-full">{group.content}</div>
        </fieldset>
      ))}
    </div>
  );
}

/**
 * The secondary filters of a bar, behind one "More filters (n)" button: a
 * popover from the sm breakpoint and a bottom sheet on phones, so the first
 * row keeps only search, dates, status and business line. Active values stay
 * visible outside as `ActiveFilterChips`.
 */
export function MoreFilters({
  groups,
  activeCount,
  onClear,
  className,
}: {
  groups: readonly MoreFilterGroup[];
  activeCount: number;
  /** Resets only the filters inside this control. */
  onClear?: () => void;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const wide = useMediaQuery("(min-width: 40rem)");
  const titleId = React.useId();
  if (groups.length === 0) return null;

  const trigger = (
    <Button
      type="button"
      variant="outline"
      className={cn("w-full justify-start gap-2 font-normal", activeCount > 0 && "border-brand-cta/60", className)}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={wide ? undefined : () => setOpen(true)}
    >
      <SlidersHorizontal className="h-4 w-4 shrink-0" aria-hidden="true" />
      {moreFiltersLabel(activeCount)}
    </Button>
  );

  const footer = (
    <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
      {onClear && activeCount > 0 ? (
        <Button type="button" variant="ghost" size="sm" onClick={onClear}>
          <X className="h-4 w-4" aria-hidden="true" />
          Clear these
        </Button>
      ) : (
        <span />
      )}
      <Button type="button" size="sm" onClick={() => setOpen(false)}>
        Done
      </Button>
    </div>
  );

  if (wide) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent
          align="end"
          role="dialog"
          aria-labelledby={titleId}
          className="w-[min(36rem,calc(100vw-2rem))] space-y-4 p-4"
        >
          <h2 id={titleId} className="text-sm font-semibold text-text-primary">
            More filters
          </h2>
          <GroupList groups={groups} />
          {footer}
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <>
      {trigger}
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="bottom" className="max-h-[85dvh] space-y-4 overflow-y-auto rounded-t-2xl p-4 pb-6">
          <SheetHeader className="pr-10 text-left">
            <SheetTitle className="text-base">More filters</SheetTitle>
            <SheetDescription>Results update as you choose.</SheetDescription>
          </SheetHeader>
          <GroupList groups={groups} />
          {footer}
        </SheetContent>
      </Sheet>
    </>
  );
}

/** Removable chips for active filters, plus one "Clear all" for the whole bar. */
export function ActiveFilterChips({
  chips,
  onClearAll,
  className,
}: {
  chips: readonly ActiveFilterChip[];
  onClearAll?: () => void;
  className?: string;
}) {
  if (chips.length === 0 && !onClearAll) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {chips.length > 0 ? (
        <ul aria-label="Active filters" className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <li key={chip.id}>
              <button
                type="button"
                onClick={chip.onRemove}
                aria-label={`Remove filter ${chip.label}`}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-brand-cta/40 bg-brand-cta-tint px-3 text-xs font-medium text-brand-link transition-colors hover:border-brand-cta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-10 motion-reduce:transition-none"
              >
                {chip.label}
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {onClearAll ? (
        <Button type="button" variant="ghost" size="sm" className="w-fit shrink-0" onClick={onClearAll}>
          <X className="h-4 w-4" aria-hidden="true" />
          Clear all
        </Button>
      ) : null}
    </div>
  );
}
