"use client";

import * as React from "react";
import { CalendarDays } from "lucide-react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  formatRangeLabel,
  isoToLocalDate,
  localDateToIso,
  matchingPreset,
  RANGE_PRESETS,
  rangeError,
  resolveRangePreset,
  todayIST,
  type DateRangeValue,
} from "@/lib/analytics-range";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

function toDraft(value: DateRangeValue): DateRange {
  return { from: isoToLocalDate(value.dateFrom), to: isoToLocalDate(value.dateTo) };
}

function fromDraft(draft: DateRange | undefined): DateRangeValue {
  return {
    dateFrom: draft?.from ? localDateToIso(draft.from) : "",
    dateTo: draft?.to ? localDateToIso(draft.to) : draft?.from ? localDateToIso(draft.from) : "",
  };
}

/** Open on the range's end month; with two months the previous month sits left of it. */
function defaultMonth(draft: DateRange | undefined, today: Date, twoMonths: boolean): Date {
  const anchor = draft?.to ?? draft?.from ?? today;
  return twoMonths ? new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1) : anchor;
}

// Calendar range picker used by every analytics dashboard. Quick presets on
// the left, a range calendar on the right (two months from the sm breakpoint),
// and Apply/Cancel so a half-picked range never triggers a fetch. Dates are
// India Standard Time calendar days; future days are disabled.
export function DateRangePicker({
  value,
  onChange,
  className,
}: {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<DateRange | undefined>(() => toDraft(value));
  const twoMonths = useMediaQuery("(min-width: 40rem)");
  const now = new Date();
  const today = todayIST(now);
  const draftValue = fromDraft(draft);
  const error = draft?.from ? rangeError(draftValue, now) : "Choose a start date.";
  const activePreset = matchingPreset(value, now);
  const label = formatRangeLabel(value);

  function onOpenChange(next: boolean) {
    if (next) setDraft(toDraft(value));
    setOpen(next);
  }

  function apply(next: DateRangeValue) {
    onChange(next);
    setOpen(false);
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label={`Date range: ${label}. Change date range`}
          className={cn("w-full justify-start gap-2 font-normal sm:w-auto", className)}
        >
          <CalendarDays className="h-4 w-4 shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="truncate">
            {activePreset ? `${RANGE_PRESETS.find((p) => p.key === activePreset)?.label} · ` : ""}
            {label}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto max-w-[calc(100vw-2rem)]" align="start">
        <div className="flex flex-col sm:flex-row">
          <div
            role="group"
            aria-label="Quick ranges"
            className="flex gap-1 overflow-x-auto border-b border-border p-2 sm:w-40 sm:flex-col sm:overflow-visible sm:border-b-0 sm:border-r"
          >
            {RANGE_PRESETS.map((preset) => {
              const range = resolveRangePreset(preset.key, now);
              const selected = activePreset === preset.key;
              return (
                <Button
                  key={preset.key}
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-pressed={selected}
                  onClick={() => apply(range)}
                  className={cn(
                    "shrink-0 justify-start font-normal",
                    selected && "bg-brand-cta-tint font-medium text-brand-link",
                  )}
                >
                  {preset.label}
                </Button>
              );
            })}
          </div>
          <div>
            <Calendar
              mode="range"
              selected={draft}
              onSelect={setDraft}
              numberOfMonths={twoMonths ? 2 : 1}
              defaultMonth={defaultMonth(draft, isoToLocalDate(today), twoMonths)}
              disabled={{ after: isoToLocalDate(today) }}
              endMonth={isoToLocalDate(today)}
            />
            <div className="flex flex-col gap-2 border-t border-border p-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-text-secondary" aria-live="polite">
                {error ? (
                  <span className={draft?.from ? "text-destructive" : undefined}>{error}</span>
                ) : (
                  formatRangeLabel(draftValue)
                )}
              </p>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button type="button" size="sm" disabled={Boolean(error)} onClick={() => apply(draftValue)}>
                  Apply
                </Button>
              </div>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
