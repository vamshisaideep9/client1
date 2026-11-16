// Pure helpers behind every dashboard filter control (FilterSelect, the
// "More filters" control and its active-filter chips). Framework-free so the
// naming and counting rules are unit-tested once and shared by every bar.

/** The not-filtering sentinel. Radix Select treats "" as "no value", so lists use "all". */
export const ALL_FILTER = "all";

export type FilterOption = { value: string; label: string };

/** A removable chip for one active filter, e.g. "Lead source: Direct lead". */
export type ActiveFilterChip = { id: string; label: string; onRemove: () => void };

/** `{ hot: "Hot" }` -> `[{ value: "hot", label: "Hot" }]`, keeping key order. */
export function optionsFromLabels(labels: Readonly<Record<string, string>>): FilterOption[] {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

/**
 * "Filter by lead source" for a field named "Lead source". The first letter is
 * lowered only for an ordinary word, so "RERA review" keeps its acronym.
 */
export function filterAriaLabel(label: string): string {
  const lowered =
    label.length > 1 && label[1] === label[1].toLocaleLowerCase()
      ? label[0].toLocaleLowerCase() + label.slice(1)
      : label;
  return `Filter by ${lowered}`;
}

/** The label of `value` in `options`, or the raw value when it is not listed. */
export function optionLabel(options: readonly FilterOption[], value: string): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

/**
 * The chip for a select filter, or null while it is unfiltered. The chip names
 * the field because the value alone ("Hot", "Busy") is ambiguous out of context.
 */
export function selectFilterChip(
  id: string,
  label: string,
  value: string | undefined,
  options: readonly FilterOption[] | Readonly<Record<string, string>>,
  onRemove: () => void,
): ActiveFilterChip | null {
  if (!value || value === ALL_FILTER) return null;
  const list = Array.isArray(options)
    ? (options as readonly FilterOption[])
    : optionsFromLabels(options as Readonly<Record<string, string>>);
  return { id, label: `${label}: ${optionLabel(list, value)}`, onRemove };
}

/** The chip for a free-text filter, or null while it is blank. */
export function textFilterChip(
  id: string,
  label: string,
  value: string | undefined,
  onRemove: () => void,
): ActiveFilterChip | null {
  const trimmed = value?.trim() ?? "";
  return trimmed ? { id, label: `${label}: ${trimmed}`, onRemove } : null;
}

/** Drops the nulls a list of `*FilterChip` calls produces. */
export function compactChips(chips: readonly (ActiveFilterChip | null)[]): ActiveFilterChip[] {
  return chips.filter((chip): chip is ActiveFilterChip => chip !== null);
}
