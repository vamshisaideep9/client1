import { formatPaise } from "@/lib/format";
import { rupeesToPaise } from "@/lib/payout-form";
import type { AgentCommissionRate, CommissionRateInput } from "./commission-rates-api";

type RateTerms = Pick<AgentCommissionRate, "kind" | "percent_bps" | "amount_paise">;
export function commissionRateLabel(rate: RateTerms): string {
  return rate.kind === "percent"
    ? `${(rate.percent_bps ?? 0) / 100}% of disbursed amount`
    : `${formatPaise(rate.amount_paise ?? 0)} per completed loan`;
}

export function parseCommissionRate(kind: "percent" | "fixed", raw: string, note: string): CommissionRateInput | null {
  // The shared money parser preserves two decimal places without float rounding.
  const value = rupeesToPaise(raw);
  if (value === null || (kind === "percent" ? value > 10_000 : value > 10_000_000_000) || note.trim().length > 280) return null;
  return {
    kind,
    percent_bps: kind === "percent" ? value : null,
    amount_paise: kind === "fixed" ? value : null,
    note: note.trim() || null,
  };
}
