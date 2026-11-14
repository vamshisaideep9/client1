/** How many times a year interest is added to the balance. */
export type CompoundingFrequency = 1 | 2 | 4 | 12;

export interface CompoundInterestYear {
  year: number;
  /** Principal plus every contribution made up to the end of this year. */
  invested: number;
  /** Interest earned during this year alone. */
  interest: number;
  /** Balance at the end of this year. */
  balance: number;
}

export interface CompoundInterestResult {
  maturity: number;
  invested: number;
  interest: number;
  schedule: CompoundInterestYear[];
}

/**
 * Compound interest on a lump sum with an optional monthly contribution.
 *
 * The lump sum compounds `frequency` times a year:
 *
 *   A = P x (1 + r/f)^(f x t)
 *
 * Monthly contributions are added at the end of each month and earn the
 * equivalent monthly rate implied by the chosen compounding frequency, so a
 * contribution never earns more than the same rupee in the lump sum would.
 * The balance is simulated month by month, which keeps the yearly schedule and
 * the closed form in agreement; values are rounded to whole rupees only for
 * display.
 */
export function compoundInterest(
  principal: number,
  annualRatePct: number,
  years: number,
  frequency: CompoundingFrequency,
  monthlyContribution = 0,
): CompoundInterestResult {
  const p = Math.max(0, principal);
  const contribution = Math.max(0, monthlyContribution);
  const wholeYears = Math.max(0, Math.floor(years));
  const rate = Math.max(0, annualRatePct) / 100;
  // Equivalent monthly growth factor for the chosen compounding frequency.
  const monthlyFactor = Math.pow(1 + rate / frequency, frequency / 12);

  let balance = p;
  let invested = p;
  const schedule: CompoundInterestYear[] = [];

  for (let year = 1; year <= wholeYears; year += 1) {
    const startBalance = balance;
    let contributedThisYear = 0;
    for (let month = 0; month < 12; month += 1) {
      balance = balance * monthlyFactor + contribution;
      contributedThisYear += contribution;
    }
    invested += contributedThisYear;
    schedule.push({
      year,
      invested: Math.round(invested),
      interest: Math.round(balance - startBalance - contributedThisYear),
      balance: Math.round(balance),
    });
  }

  const maturity = Math.round(balance);
  const totalInvested = Math.round(invested);
  return {
    maturity,
    invested: totalInvested,
    interest: maturity - totalInvested,
    schedule,
  };
}
