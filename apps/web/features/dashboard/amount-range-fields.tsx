"use client";

import { Input } from "@/components/ui/input";

import { amountRangeInverted } from "./product-filter-options";

/** Digits, one decimal point and up to two decimals: rupees as typed. */
export function rupeesInput(value: string): string {
  const cleaned = value.replace(/[^\d.]/g, "");
  const [whole, ...rest] = cleaned.split(".");
  return rest.length ? `${whole}.${rest.join("").slice(0, 2)}` : whole;
}

/**
 * A Min / Max rupee pair inside "More filters" (the Money group), with a
 * visible legend and a note when the minimum is above the maximum.
 */
export function AmountRangeFields({
  legend,
  name,
  min,
  max,
  onChange,
  invertedNote = "The minimum is above the maximum, so nothing matches.",
}: {
  legend: string;
  /** Read in the accessible names: "Minimum <name> (₹)". */
  name: string;
  min: string;
  max: string;
  onChange: (next: { min: string; max: string }) => void;
  /** What an inverted range does on this screen. */
  invertedNote?: string;
}) {
  const inverted = amountRangeInverted(min, max);
  return (
    <fieldset className="min-w-0 sm:col-span-2">
      <legend className="mb-1 text-xs font-medium text-text-secondary">{legend}</legend>
      <div className="grid grid-cols-2 gap-2">
        <Input
          aria-label={`Minimum ${name} (₹)`}
          inputMode="decimal"
          placeholder="Min"
          value={min}
          aria-invalid={inverted || undefined}
          onChange={(event) => onChange({ min: rupeesInput(event.target.value), max })}
        />
        <Input
          aria-label={`Maximum ${name} (₹)`}
          inputMode="decimal"
          placeholder="Max"
          value={max}
          aria-invalid={inverted || undefined}
          onChange={(event) => onChange({ min, max: rupeesInput(event.target.value) })}
        />
      </div>
      {inverted ? (
        <p className="mt-1 text-xs text-error" role="status">
          {invertedNote}
        </p>
      ) : null}
    </fieldset>
  );
}
