import { CalculatorCard } from "@/components/calculators/calculator-card";
import { DashboardHeader, DashboardPage } from "@/features/dashboard/dashboard-ui";
import { CALCULATORS } from "@/lib/calculators/registry";
import type { CalculatorGroup } from "@/lib/calculators/types";

// The public calculator suite inside the signed-in dashboard, so Clients and
// Telecallers (often mid-call) can run numbers without leaving their workspace.
// Same registry and islands as /calculators; only the chrome and links differ.
const GROUPS: { key: CalculatorGroup; title: string }[] = [
  { key: "loans", title: "Loans" },
  { key: "real_estate", title: "Property" },
  { key: "credit_cards", title: "Credit cards" },
  { key: "insurance", title: "Insurance" },
];

export default function DashboardCalculatorsPage() {
  return (
    <DashboardPage>
      <DashboardHeader
        title="Calculators"
        description="EMI, eligibility, stamp duty, rent vs buy and more. Nothing you enter is saved."
      />
      {GROUPS.map((group) => {
        const items = CALCULATORS.filter((c) => c.group === group.key);
        if (items.length === 0) return null;
        return (
          <section key={group.key} aria-labelledby={`calc-group-${group.key}`} className="space-y-3">
            <h2 id={`calc-group-${group.key}`} className="text-lg font-semibold text-text-primary">
              {group.title}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((def) => (
                <CalculatorCard
                  key={def.slug}
                  def={def}
                  compact
                  href={`/dashboard/calculators/${def.slug}`}
                />
              ))}
            </div>
          </section>
        );
      })}
    </DashboardPage>
  );
}
