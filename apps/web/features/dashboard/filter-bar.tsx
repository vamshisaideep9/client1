"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { ActiveFilterChip, FilterOption } from "./filter-options";
import { DateRangeFields, FilterSelect } from "./filter-select";
import { ActiveFilterChips, MoreFilters, type MoreFilterGroup } from "./more-filters";

/**
 * The filter bar for every staff list.
 *
 * Grown out of `features/sub-admin`'s `CmsFilterBar`, which was the most
 * complete of the five near-identical copies in the codebase (the others were
 * inline `grid … lg:grid-cols-4` blocks in the agent, vehicle-arrangement, loan
 * and property-deal queues). Everything the CMS version did is preserved;
 * what is new is that each control can be switched off independently and a
 * surface can drop its own controls in through `extra`, which is what let the
 * admin queues stop hand-rolling their own bars.
 *
 * Every filtered surface uses `"all"` as the not-filtering sentinel rather than
 * an empty string, because Radix `Select` treats `""` as "no value". Each
 * select is a `FilterSelect`: unfiltered, its trigger reads the field name
 * (`statusLabel`, `kindLabel`) and its first option is "All".
 *
 * The first row keeps search, status, business line, type and the From / To
 * dates; anything else a surface needs goes into `more` ("More filters (n)",
 * a popover or a phone bottom sheet) with its active values listed as
 * removable `chips` next to "Clear all".
 */
export type FilterBarValue = {
  search: string;
  status: string;
  line: string;
  kind: string;
  from: string;
  to: string;
};

export type { FilterOption } from "./filter-options";

export const EMPTY_FILTERS: FilterBarValue = {
  search: "",
  status: "all",
  line: "all",
  kind: "all",
  from: "",
  to: "",
};

export const DEFAULT_LINE_OPTIONS: readonly FilterOption[] = [
  { value: "loans", label: "Loans" },
  { value: "real_estate", label: "Real Estate" },
  { value: "both", label: "Both lines" },
];

export function filtersAreActive(value: FilterBarValue): boolean {
  return (
    value.search !== "" ||
    value.status !== "all" ||
    value.line !== "all" ||
    value.kind !== "all" ||
    value.from !== "" ||
    value.to !== ""
  );
}

/** `YYYY-MM-DD` bounds, both optional. Mirrors `lib/date-range.isInDateRange`. */
export function matchesSearch(haystack: string, search: string): boolean {
  return haystack.toLowerCase().includes(search.trim().toLowerCase());
}

export function FilterBar({
  value,
  onChange,
  searchLabel,
  searchPlaceholder = "Search",
  statusOptions,
  statusLabel = "Status",
  kindOptions,
  kindLabel = "Type",
  lineLabel = "Business line",
  lineOptions = DEFAULT_LINE_OPTIONS,
  showSearch = true,
  showStatus = true,
  showLine = true,
  showDates = true,
  showClear = true,
  dateFromLabel = "From date",
  dateToLabel = "To date",
  note,
  actions,
  extra,
  advanced,
  more,
  moreActiveCount = 0,
  onClearMore,
  chips,
  onClear,
  hasExternalFilters = false,
  className,
}: {
  value: FilterBarValue;
  onChange: (value: FilterBarValue) => void;
  searchLabel: string;
  searchPlaceholder?: string;
  statusOptions?: readonly FilterOption[];
  /** Field name of the status select, e.g. "Payout status". */
  statusLabel?: string;
  kindOptions?: readonly FilterOption[];
  /** Field name of the type select, e.g. "Category". */
  kindLabel?: string;
  lineLabel?: string;
  lineOptions?: readonly FilterOption[];
  showSearch?: boolean;
  showStatus?: boolean;
  showLine?: boolean;
  showDates?: boolean;
  showClear?: boolean;
  /** Accessible names of the date pair; they must contain "from" / "to". */
  dateFromLabel?: string;
  dateToLabel?: string;
  note?: string;
  /** Compact presets or scope controls rendered above the filter grid. */
  actions?: ReactNode;
  /** Surface-specific controls, rendered in the same grid as the built-ins. */
  extra?: ReactNode;
  /** Secondary content rendered below the grid. */
  advanced?: ReactNode;
  /** Grouped secondary filters behind the "More filters (n)" control. */
  more?: readonly MoreFilterGroup[];
  /** How many filters inside `more` are active. */
  moreActiveCount?: number;
  /** Resets only the filters inside `more`. */
  onClearMore?: () => void;
  /** Removable chips for the active filters inside `more`. */
  chips?: readonly ActiveFilterChip[];
  /** Override the default all-empty reset when a surface has a meaningful baseline. */
  onClear?: () => void;
  /** Include filters rendered through `extra` in Clear-button visibility. */
  hasExternalFilters?: boolean;
  className?: string;
}) {
  const set = (patch: Partial<FilterBarValue>) => onChange({ ...value, ...patch });
  const active = filtersAreActive(value) || hasExternalFilters || moreActiveCount > 0;
  const hasChips = Boolean(chips && chips.length > 0);

  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-3", className)}
      aria-label="Filters"
    >
      {actions ? <div className="mb-3 flex flex-wrap gap-2">{actions}</div> : null}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-2 [&_[data-slot=select-trigger]]:w-full">
        {showSearch ? (
          <Input
            aria-label={searchLabel}
            placeholder={searchPlaceholder}
            value={value.search}
            maxLength={100}
            onChange={(event) => set({ search: event.target.value })}
          />
        ) : null}

        {showStatus && statusOptions ? (
          <FilterSelect
            label={statusLabel}
            value={value.status}
            options={statusOptions}
            onValueChange={(status) => set({ status })}
          />
        ) : null}

        {showLine ? (
          <FilterSelect
            label={lineLabel}
            value={value.line}
            options={lineOptions}
            onValueChange={(line) => set({ line })}
          />
        ) : null}

        {kindOptions ? (
          <FilterSelect
            label={kindLabel}
            value={value.kind}
            options={kindOptions}
            onValueChange={(kind) => set({ kind })}
          />
        ) : null}

        {extra}

        {showDates ? (
          <DateRangeFields
            from={value.from}
            to={value.to}
            fromLabel={dateFromLabel}
            toLabel={dateToLabel}
            onFromChange={(from) => set({ from })}
            onToChange={(to) => set({ to })}
          />
        ) : null}

        {more && more.length > 0 ? (
          <MoreFilters groups={more} activeCount={moreActiveCount} onClear={onClearMore} />
        ) : null}
      </div>

      {advanced}

      {note || (active && showClear) || hasChips ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            {hasChips && chips ? <ActiveFilterChips chips={chips} /> : null}
            {note ? <p className="text-xs text-text-secondary">{note}</p> : null}
          </div>
          {active && showClear ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-fit shrink-0 whitespace-nowrap"
              onClick={() => (onClear ? onClear() : onChange(EMPTY_FILTERS))}
            >
              <X className="h-4 w-4" aria-hidden="true" />
              Clear all
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
