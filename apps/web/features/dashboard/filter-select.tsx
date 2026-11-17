"use client";

import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { ALL_FILTER, filterAriaLabel, type FilterOption } from "./filter-options";

/**
 * The one select every dashboard filter uses. While unfiltered the trigger
 * reads the field name ("Status", "Lead source") instead of an "All …" phrase,
 * and the first menu option is "All". The accessible name is always
 * "Filter by <field>" unless a caller has a more specific one.
 */
export function FilterSelect({
  label,
  value,
  onValueChange,
  options = [],
  ariaLabel,
  allValue = ALL_FILTER,
  allLabel = "All",
  className,
  disabled,
  children,
}: {
  /** The field name, shown on the trigger while unfiltered. */
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options?: readonly FilterOption[];
  ariaLabel?: string;
  allValue?: string;
  allLabel?: string;
  className?: string;
  disabled?: boolean;
  /** Extra menu content after the options, e.g. grouped items. */
  children?: ReactNode;
}) {
  const unfiltered = value === allValue;
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger
        aria-label={ariaLabel ?? filterAriaLabel(label)}
        data-active={unfiltered ? undefined : "true"}
        className={cn(
          // Active: a brand border and medium weight (not a fill, which reads
          // as disabled against the dark-mode input surface).
          "w-full data-[active=true]:border-brand-cta data-[active=true]:font-medium",
          className,
        )}
      >
        {/* While unfiltered the field name stands in for the selected "All". */}
        <SelectValue>{unfiltered ? label : undefined}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={allValue}>{allLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
        {children}
      </SelectContent>
    </Select>
  );
}

/**
 * A From / To pair of date inputs with visible labels. The accessible names
 * (`fromLabel`, `toLabel`) must contain the words "from" and "to" so the
 * visible text stays part of each name.
 */
export function DateRangeFields({
  from,
  to,
  onFromChange,
  onToChange,
  fromLabel = "From date",
  toLabel = "To date",
}: {
  from: string;
  to: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  fromLabel?: string;
  toLabel?: string;
}) {
  return (
    <>
      <DateField visible="From" ariaLabel={fromLabel} value={from} onChange={onFromChange} />
      <DateField visible="To" ariaLabel={toLabel} value={to} min={from || undefined} onChange={onToChange} />
    </>
  );
}

function DateField({
  visible,
  ariaLabel,
  value,
  min,
  onChange,
}: {
  visible: string;
  ariaLabel: string;
  value: string;
  min?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative min-w-0">
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-xs font-medium text-text-secondary"
      >
        {visible}
      </span>
      <Input
        aria-label={ariaLabel}
        type="date"
        min={min}
        value={value}
        className="pl-12"
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
