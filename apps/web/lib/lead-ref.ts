// Lead references (`LD-00000123`) are formatted by the API as `lead_ref`; the
// web only shows them and matches searches against them. The tolerant forms
// mirror the API's `lead_ref` filter (apps/api/app/core/lead_reference.py):
// `LD-00000123`, `ld-123`, `LD 123`, `LD123` and a bare `123`, with leading
// zeros ignored. Digits are compared as strings, so numbers past 2^53 stay exact.

const SEARCH_PATTERN = /^(?:LD[\s-]?)?0*(\d{1,18})$/i;
const MAX_INPUT = 32;

/** The canonical lead number a search term names (`"123"`), or null. */
export function leadRefDigits(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  if (!text || text.length > MAX_INPUT) return null;
  const digits = SEARCH_PATTERN.exec(text)?.[1];
  if (!digits || /^0+$/.test(digits)) return null;
  return digits;
}

/** True when `search` names exactly this reference. */
export function matchesLeadRef(search: string, leadRef: string | null | undefined): boolean {
  const wanted = leadRefDigits(search);
  return wanted !== null && wanted === leadRefDigits(leadRef);
}

/** True when `search` names exactly one of these references. */
export function matchesAnyLeadRef(
  search: string,
  leadRefs: readonly (string | null | undefined)[] | null | undefined,
): boolean {
  const wanted = leadRefDigits(search);
  return wanted !== null && (leadRefs ?? []).some((ref) => leadRefDigits(ref) === wanted);
}
