// Budget facet for property search. Values are whole rupees so one control
// serves both a ₹1.2 Cr sale price and a ₹25,000 monthly rent.
//
// The slider tops out at ₹20 Cr. Its scale is stepped rather than linear: a
// linear 0–20 Cr track would squeeze every sub-crore home (most of the
// catalogue) into the first 5% of the bar. The stops are 5 L apart up to
// 1 Cr, 25 L apart up to 5 Cr, then 1 Cr apart up to 20 Cr. The top stop means
// "no upper limit", so listings above 20 Cr stay reachable.

const LAKH = 100_000;
const CRORE = 100 * LAKH;

export const BUDGET_MAX_RUPEES = 20 * CRORE;

function buildStops(): number[] {
  const lakhs: number[] = [0];
  for (let v = 5; v <= 100; v += 5) lakhs.push(v);
  for (let v = 125; v <= 500; v += 25) lakhs.push(v);
  for (let v = 600; v <= 2000; v += 100) lakhs.push(v);
  return lakhs.map((l) => l * LAKH);
}

/** Slider stops in rupees, ascending, from 0 to ₹20 Cr. */
export const BUDGET_STOPS: readonly number[] = buildStops();
export const BUDGET_TOP_INDEX = BUDGET_STOPS.length - 1;

/** Nearest slider stop for a rupee amount; amounts past the scale pin to its ends. */
export function budgetStopIndex(rupees: number | undefined, fallback: number): number {
  if (rupees == null) return fallback;
  let best = 0;
  for (let i = 1; i < BUDGET_STOPS.length; i += 1) {
    if (Math.abs(BUDGET_STOPS[i] - rupees) < Math.abs(BUDGET_STOPS[best] - rupees)) best = i;
  }
  return best;
}

/**
 * Maps committed slider positions to filter values. The bottom stop means no
 * minimum and the top stop means no maximum, so an untouched end never hides
 * a listing.
 */
export function budgetFromStops(minIndex: number, maxIndex: number): {
  budgetMin: number | undefined;
  budgetMax: number | undefined;
} {
  return {
    budgetMin: minIndex <= 0 ? undefined : BUDGET_STOPS[minIndex],
    budgetMax: maxIndex >= BUDGET_TOP_INDEX ? undefined : BUDGET_STOPS[maxIndex],
  };
}

/**
 * Commits a slider drag without disturbing the edge the user did not move. An
 * exact amount typed into a field (₹25,000 rent, ₹52 L) sits between stops;
 * rebuilding both edges from stops would silently round or drop it.
 */
export function budgetFromSliderCommit(
  committedIndex: readonly [number, number],
  nextIndex: readonly [number, number],
  current: { budgetMin: number | undefined; budgetMax: number | undefined },
): { budgetMin: number | undefined; budgetMax: number | undefined } {
  const fromStops = budgetFromStops(nextIndex[0], nextIndex[1]);
  return {
    budgetMin: nextIndex[0] === committedIndex[0] ? current.budgetMin : fromStops.budgetMin,
    budgetMax: nextIndex[1] === committedIndex[1] ? current.budgetMax : fromStops.budgetMax,
  };
}

/**
 * Keeps digits only (typed, pasted or autofilled) and clamps to the ₹20 Cr
 * ceiling. Returns undefined for an empty field, which means "no constraint".
 */
export function parseBudgetInput(raw: string): number | undefined {
  const digits = raw.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  if (!digits) return undefined;
  // Bound the string before Number() so a pasted 40-digit value cannot lose
  // precision; anything longer than the ceiling's digits is over the ceiling.
  if (digits.length > String(BUDGET_MAX_RUPEES).length) return BUDGET_MAX_RUPEES;
  return Math.min(Number(digits), BUDGET_MAX_RUPEES);
}

/** Orders a min/max pair so a reversed entry still means the same range. */
export function orderBudget(
  min: number | undefined,
  max: number | undefined,
): { budgetMin: number | undefined; budgetMax: number | undefined } {
  if (min != null && max != null && min > max) return { budgetMin: max, budgetMax: min };
  return { budgetMin: min, budgetMax: max };
}

function trimDecimal(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
}

/** "₹25,000", "₹50 L", "₹1.25 Cr". */
export function formatBudget(rupees: number): string {
  if (rupees >= CRORE) return `₹${trimDecimal(rupees / CRORE)} Cr`;
  if (rupees >= LAKH) return `₹${trimDecimal(rupees / LAKH)} L`;
  return `₹${rupees.toLocaleString("en-IN")}`;
}

/** Summary for a chip or collapsed facet heading. */
export function formatBudgetRange(min: number | undefined, max: number | undefined): string {
  const low = min != null ? formatBudget(min) : "₹0";
  const high = max != null ? formatBudget(max) : `${formatBudget(BUDGET_MAX_RUPEES)}+`;
  return `${low} - ${high}`;
}

/** Rupee value of a listing whose API price was normalised to lakhs. */
export function listingPriceRupees(priceLakhs: number): number {
  return Math.round(priceLakhs * LAKH);
}
