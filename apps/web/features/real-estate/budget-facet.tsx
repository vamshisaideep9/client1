"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  BUDGET_STOPS,
  BUDGET_TOP_INDEX,
  budgetFromSliderCommit,
  budgetStopIndex,
  formatBudget,
  orderBudget,
  parseBudgetInput,
} from "@/lib/property-budget";

type BudgetPatch = { budgetMin: number | undefined; budgetMax: number | undefined };

// Budget slider (₹0 to ₹20 Cr+, stepped) plus optional exact-amount fields.
// The fields accept digits only, so a pasted "₹1,25,00,000" or "1.2 cr" keeps
// only its digits. Either control can set the range; both always reflect the
// committed filter.
export function BudgetFacet({
  budgetMin,
  budgetMax,
  onCommit,
}: {
  budgetMin: number | undefined;
  budgetMax: number | undefined;
  onCommit: (patch: BudgetPatch) => void;
}) {
  const committed = React.useMemo<[number, number]>(
    () => [budgetStopIndex(budgetMin, 0), budgetStopIndex(budgetMax, BUDGET_TOP_INDEX)],
    [budgetMin, budgetMax],
  );
  const [draft, setDraft] = React.useState<[number, number]>(committed);
  React.useEffect(() => setDraft(committed), [committed]);

  function commitSlider(value: number[]) {
    onCommit(budgetFromSliderCommit(committed, [value[0], value[1]], { budgetMin, budgetMax }));
  }

  function commitField(edge: "min" | "max", value: number | undefined) {
    const next =
      edge === "min" ? orderBudget(value, budgetMax) : orderBudget(budgetMin, value);
    if (next.budgetMin === budgetMin && next.budgetMax === budgetMax) return;
    onCommit(next);
  }

  return (
    <div className="grid gap-4">
      <Slider
        value={draft}
        thumbLabels={["Minimum budget", "Maximum budget"]}
        min={0}
        max={BUDGET_TOP_INDEX}
        step={1}
        onValueChange={(value) => setDraft(value as [number, number])}
        onValueCommit={commitSlider}
        className="[&_[data-slot=slider-range]]:bg-brand-cta [&_[data-slot=slider-thumb]]:border-brand-cta"
      />
      <div className="flex justify-between text-xs text-text-secondary" aria-hidden="true">
        <span>{formatBudget(BUDGET_STOPS[draft[0]])}</span>
        <span>
          {draft[1] >= BUDGET_TOP_INDEX
            ? `${formatBudget(BUDGET_STOPS[BUDGET_TOP_INDEX])}+`
            : formatBudget(BUDGET_STOPS[draft[1]])}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <BudgetField
          id="filter-budget-min"
          label="Min ₹ (optional)"
          placeholder="No min"
          value={budgetMin}
          onCommit={(value) => commitField("min", value)}
        />
        <BudgetField
          id="filter-budget-max"
          label="Max ₹ (optional)"
          placeholder="No max"
          value={budgetMax}
          onCommit={(value) => commitField("max", value)}
        />
      </div>
      <p className="text-xs text-text-secondary">
        Numbers only, in rupees. Use exact amounts for monthly rent.
      </p>
    </div>
  );
}

// While focused the field holds raw digits, so the caret never jumps under a
// re-inserted separator. On blur or Enter it commits and shows Indian grouping.
function BudgetField({
  id,
  label,
  placeholder,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: number | undefined;
  onCommit: (value: number | undefined) => void;
}) {
  const [focused, setFocused] = React.useState(false);
  const [text, setText] = React.useState(value != null ? String(value) : "");

  React.useEffect(() => {
    if (!focused) setText(value != null ? String(value) : "");
  }, [value, focused]);

  function commit() {
    const parsed = parseBudgetInput(text);
    setText(parsed != null ? String(parsed) : "");
    onCommit(parsed);
  }

  const shown = !focused && text ? Number(text).toLocaleString("en-IN") : text;

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id} className="text-xs font-medium text-text-primary">
        {label}
      </Label>
      <Input
        id={id}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        autoComplete="off"
        placeholder={placeholder}
        value={shown}
        onFocus={() => setFocused(true)}
        onChange={(event) => setText(event.target.value.replace(/\D/g, ""))}
        onBlur={() => {
          setFocused(false);
          commit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="tabular-nums"
      />
    </div>
  );
}
