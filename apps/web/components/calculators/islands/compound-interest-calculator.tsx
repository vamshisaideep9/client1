"use client";

import { useMemo } from "react";
import { parseAsFloat, parseAsInteger, parseAsNumberLiteral, useQueryStates } from "nuqs";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { INFO } from "@/lib/calculators/glossary";
import { compoundInterest, type CompoundingFrequency } from "@/lib/finance";
import { formatCompactINR, formatINR } from "@/lib/format";
import { InfoHint } from "../info-hint";
import { ResultCard } from "../result-card";
import { SliderField } from "../slider-field";

const FREQUENCIES: { value: CompoundingFrequency; label: string }[] = [
  { value: 1, label: "Yearly" },
  { value: 2, label: "Half-yearly" },
  { value: 4, label: "Quarterly" },
  { value: 12, label: "Monthly" },
];

export const CI_LIMITS = {
  principalMin: 1000,
  principalMax: 100000000,
  rateMax: 34,
  yearsMax: 40,
  monthlyMax: 1000000,
} as const;

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function yearsLabel(years: number): string {
  return years === 1 ? "1 year" : `${years} years`;
}

// Compound interest: grow a lump sum (plus optional monthly additions) at a
// chosen compounding frequency. All state lives in the URL through nuqs so a
// result can be shared, like every other calculator island.
export function CompoundInterestCalculator() {
  const [state, setState] = useQueryStates(
    {
      principal: parseAsInteger.withDefault(100000),
      rate: parseAsFloat.withDefault(8),
      years: parseAsInteger.withDefault(10),
      freq: parseAsNumberLiteral([1, 2, 4, 12] as const).withDefault(4),
      monthly: parseAsInteger.withDefault(0),
    },
    { history: "replace", clearOnDefault: true },
  );

  const principal = clamp(state.principal, CI_LIMITS.principalMin, CI_LIMITS.principalMax);
  const rate = clamp(state.rate, 0, CI_LIMITS.rateMax);
  const years = clamp(state.years, 1, CI_LIMITS.yearsMax);
  const monthly = clamp(state.monthly, 0, CI_LIMITS.monthlyMax);
  const frequency = state.freq as CompoundingFrequency;

  const result = useMemo(
    () => compoundInterest(principal, rate, years, frequency, monthly),
    [principal, rate, years, frequency, monthly],
  );

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      {/* Inputs */}
      <div className="grid content-start gap-6">
        <SliderField
          id="ci-principal"
          label="Principal amount"
          info={INFO.ciPrincipal}
          prefix="₹"
          value={principal}
          min={CI_LIMITS.principalMin}
          max={CI_LIMITS.principalMax}
          step={1000}
          onChange={(v) => setState({ principal: Math.round(v) })}
          helper={formatCompactINR(principal)}
        />
        <SliderField
          id="ci-rate"
          label="Annual interest rate"
          info={INFO.ciRate}
          suffix="% p.a."
          value={rate}
          min={0}
          max={CI_LIMITS.rateMax}
          step={0.1}
          onChange={(v) => setState({ rate: v })}
          helper={`${rate.toFixed(2)}% per year`}
        />
        <SliderField
          id="ci-years"
          label="Time period"
          info={INFO.ciYears}
          suffix="years"
          value={years}
          min={1}
          max={CI_LIMITS.yearsMax}
          step={1}
          onChange={(v) => setState({ years: Math.round(v) })}
          helper={yearsLabel(years)}
        />
        <div className="grid gap-2">
          <div className="flex items-center gap-1.5">
            <label htmlFor="ci-frequency" className="text-sm text-[var(--nav-text)]">
              Compounding frequency
            </label>
            <InfoHint label="Compounding frequency" text={INFO.ciFrequency} />
          </div>
          <Select
            value={String(frequency)}
            onValueChange={(next) => setState({ freq: Number(next) as CompoundingFrequency })}
          >
            <SelectTrigger id="ci-frequency" className="w-full">
              <SelectValue placeholder="Choose how often" />
            </SelectTrigger>
            <SelectContent>
              {FREQUENCIES.map((option) => (
                <SelectItem key={option.value} value={String(option.value)}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <SliderField
          id="ci-monthly"
          label="Monthly addition (optional)"
          info={INFO.ciMonthly}
          prefix="₹"
          value={monthly}
          min={0}
          max={CI_LIMITS.monthlyMax}
          step={500}
          onChange={(v) => setState({ monthly: Math.round(v) })}
          helper={monthly > 0 ? `${formatCompactINR(monthly)} every month` : "No monthly additions"}
        />
      </div>

      {/* Results */}
      <div className="grid content-start gap-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <ResultCard
            emphasis
            label="Maturity value"
            info={INFO.ciMaturity}
            value={formatCompactINR(result.maturity)}
          />
          <ResultCard
            label="Total invested"
            info={INFO.ciInvested}
            value={formatCompactINR(result.invested)}
          />
          <ResultCard
            label="Interest earned"
            info={INFO.ciInterest}
            value={formatCompactINR(result.interest)}
          />
        </div>
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[28rem] text-sm">
            <caption className="sr-only">Year by year growth</caption>
            <thead className="bg-surface text-left text-xs text-text-secondary">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Year</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Invested</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Interest that year</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Balance</th>
              </tr>
            </thead>
            <tbody>
              {result.schedule.map((row) => (
                <tr key={row.year} className="border-t border-border">
                  <th scope="row" className="px-3 py-2 text-left font-medium">{row.year}</th>
                  <td className="px-3 py-2 text-right tabular-nums">{formatINR(row.invested)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatINR(row.interest)}</td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">{formatINR(row.balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
