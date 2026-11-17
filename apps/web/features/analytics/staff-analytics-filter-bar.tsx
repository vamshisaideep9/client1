"use client";

import type * as React from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AmountRangeFields } from "@/features/dashboard/amount-range-fields";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import {
  compactChips,
  optionsFromLabels,
  selectFilterChip,
  type ActiveFilterChip,
  type FilterOption,
} from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { useLine } from "@/features/dashboard/line-provider";
import type { MoreFilterGroup } from "@/features/dashboard/more-filters";
import {
  COMMISSION_STATUS_LABEL,
  DEAL_STATUS_LABEL,
  PROPERTY_CATEGORY_LABEL,
  PROPERTY_SUBTYPE_LABEL,
  amountRangeInverted,
  amountRangeLabel,
  parseRupees,
} from "@/features/dashboard/product-filter-options";
import {
  INTEREST_LABEL,
  LOAN_STATUS_LABEL,
  REFERRER_SOURCE_LABEL,
} from "@/features/telecaller/lead-signal-filters";
import { DISPOSITION_LABEL, STATUS_LABEL } from "@/features/telecaller/telecaller-lead-status";
import type { DateRangeValue } from "@/lib/analytics-range";
import type { StaffAnalyticsFilterValues } from "@/lib/staff-analytics-api";

import { DateRangePicker } from "./date-range-picker";

const LINE_LABEL: Record<string, string> = { loans: "Loans", real_estate: "Real estate" };
const TASK_TYPE_LABEL: Record<string, string> = {
  document_collection: "Document collection",
  property_visit: "Property visit",
  background_check: "Background check",
};

// Sub Admin content filters. The words match the Sub Admin's banner and offer
// lists; for offers the API folds scheduled into Approved, active into Live
// and expired into Archived.
const CONTENT_TYPE_LABEL: Record<string, string> = { banners: "Banners", offers: "Offers" };
const CONTENT_STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  live: "Live",
  rejected: "Changes requested",
  archived: "Archived",
};
const PLACEMENT_LABEL: Record<string, string> = {
  homepage: "Homepage",
  homepage_ad: "Homepage sponsor",
  financial_services: "Financial Services",
  properties: "Properties",
  dashboard: "Signed-in dashboard",
};
const BANNER_TYPE_LABEL: Record<string, string> = {
  default: "Standard",
  personalized: "Targeted",
  action: "Action",
};
const DISCOUNT_TYPE_LABEL: Record<string, string> = {
  percentage: "Percentage",
  flat: "Flat amount",
  "cashback-tie": "Cashback",
};

type FilterKey = keyof StaffAnalyticsFilterValues;
type SelectKey = Exclude<FilterKey, "amount_min" | "amount_max">;

/**
 * One role filter. `group` is the "More filters" section it belongs to, or
 * null for a filter that stays in the first row (the role's status filter).
 * An "amount" spec is the Min / Max pair behind `amount_min` / `amount_max`.
 */
export type FilterSpec =
  | {
      kind?: "select";
      key: SelectKey;
      label: string;
      options: Readonly<Record<string, string>> | readonly FilterOption[];
      group: string | null;
    }
  | { kind: "amount"; key: "amount"; label: string; name: string; group: string };

/** What a role's filters need besides the role and line (CS-023). */
export type RoleFilterContext = {
  /** Lending products and banks from the catalogue. */
  loanTypes?: readonly FilterOption[];
  banks?: readonly FilterOption[];
  /** Filters the API reports the Admin's field rules rule out. */
  hiddenFilters?: readonly string[];
};

function toOptions(options: Readonly<Record<string, string>> | readonly FilterOption[]): FilterOption[] {
  return Array.isArray(options)
    ? [...(options as readonly FilterOption[])]
    : optionsFromLabels(options as Readonly<Record<string, string>>);
}

/** Product (loans line) or Property (real estate line) filters for a role. */
function productSpecs(line: string, context: RoleFilterContext): FilterSpec[] {
  if (line === "loans") {
    return [
      { key: "loan_type_id", label: "Product", options: context.loanTypes ?? [], group: "Product" },
      { key: "bank_id", label: "Bank", options: context.banks ?? [], group: "Product" },
      { key: "loan_status", label: "Loan status", options: LOAN_STATUS_LABEL, group: "Product" },
    ];
  }
  if (line === "real_estate") {
    return [
      { key: "property_category", label: "Property category", options: PROPERTY_CATEGORY_LABEL, group: "Property" },
      { key: "property_subtype", label: "Property type", options: PROPERTY_SUBTYPE_LABEL, group: "Property" },
      { key: "deal_status", label: "Deal status", options: DEAL_STATUS_LABEL, group: "Property" },
    ];
  }
  return [];
}

/**
 * Which filters each role's analytics understand (mirrors the API, CS-023):
 * Telecaller and Employee get product or property filters for the line, the
 * Telecaller an amount range (requested loan amount or quoted price) unless
 * the Admin hides it, and the Agent finance filters (product or property,
 * commission status, commission amount). The current filters only matter for
 * the Sub Admin: banner-only filters hide while Content type is Offers, and
 * the offer-only one while it is Banners.
 */
export function filtersForRole(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues = {},
  context: RoleFilterContext = {},
): FilterSpec[] {
  const amountShown = !(context.hiddenFilters ?? []).some((key) => key === "amount_min" || key === "amount_max");
  if (role === "sub_admin") {
    // A banner-only filter (placement, banner type) rules out offers and the
    // offer-only one (discount type) rules out banners, as in the API, so a
    // combination that could never match is never offered.
    const banners = filters.content_type !== "offers" && !filters.discount_type;
    const offers = filters.content_type !== "banners" && !filters.placement && !filters.banner_type;
    return [
      { key: "content_type", label: "Content type", options: CONTENT_TYPE_LABEL, group: "Content" },
      { key: "content_status", label: "Review status", options: CONTENT_STATUS_LABEL, group: null },
      ...(banners
        ? [
            { key: "placement" as const, label: "Placement", options: PLACEMENT_LABEL, group: "Content" },
            { key: "banner_type" as const, label: "Banner type", options: BANNER_TYPE_LABEL, group: "Content" },
          ]
        : []),
      ...(offers
        ? [{ key: "discount_type" as const, label: "Discount type", options: DISCOUNT_TYPE_LABEL, group: "Money" }]
        : []),
    ];
  }
  if (role === "telecaller") {
    return [
      { key: "call_status", label: "Call status", options: DISPOSITION_LABEL, group: "Lead" },
      { key: "interest", label: "Lead interest", options: INTEREST_LABEL, group: "Lead" },
      { key: "lead_source", label: "Lead source", options: REFERRER_SOURCE_LABEL, group: "Lead" },
      ...productSpecs(line, context),
      ...(amountShown && (line === "loans" || line === "real_estate")
        ? [
            {
              kind: "amount" as const,
              key: "amount" as const,
              label: line === "loans" ? "Loan amount" : "Quoted price",
              name: line === "loans" ? "loan amount" : "quoted price",
              group: "Money",
            },
          ]
        : []),
    ];
  }
  if (role === "employee") {
    return [{ key: "task_type", label: "Task type", options: TASK_TYPE_LABEL, group: null }, ...productSpecs(line, context)];
  }
  if (role === "agent") {
    return [
      { key: "lead_status", label: "Lead status", options: STATUS_LABEL, group: null },
      ...productSpecs(line, context),
      { key: "commission_status", label: "Commission status", options: COMMISSION_STATUS_LABEL, group: "Money" },
      { kind: "amount", key: "amount", label: "Commission", name: "commission", group: "Money" },
    ];
  }
  return [];
}

/** Groups the specs that belong behind "More filters", keeping their order. */
export function moreFilterSpecGroups(specs: readonly FilterSpec[]): { title: string; specs: FilterSpec[] }[] {
  const groups: { title: string; specs: FilterSpec[] }[] = [];
  for (const spec of specs) {
    if (!spec.group) continue;
    const existing = groups.find((group) => group.title === spec.group);
    if (existing) existing.specs.push(spec);
    else groups.push({ title: spec.group, specs: [spec] });
  }
  return groups;
}

function specKeys(spec: FilterSpec): FilterKey[] {
  return spec.kind === "amount" ? ["amount_min", "amount_max"] : [spec.key];
}

/** True when the filter behind a spec is set. */
function specActive(spec: FilterSpec, values: StaffAnalyticsFilterValues): boolean {
  if (spec.kind === "amount") {
    return parseRupees(values.amount_min ?? "") !== null || parseRupees(values.amount_max ?? "") !== null;
  }
  return Boolean(values[spec.key]);
}

/** More-filter groups, active count and chips for a set of role filter specs. */
export function roleFilterControls(
  specs: readonly FilterSpec[],
  values: StaffAnalyticsFilterValues,
  setFilters: (patch: StaffAnalyticsFilterValues) => void,
): { inline: React.ReactNode; more: MoreFilterGroup[]; activeCount: number; chips: ActiveFilterChip[] } {
  const control = (spec: FilterSpec) =>
    spec.kind === "amount" ? (
      <AmountRangeFields
        key={spec.key}
        legend={`${spec.label} (₹)`}
        name={spec.name}
        min={values.amount_min ?? ""}
        max={values.amount_max ?? ""}
        invertedNote="The minimum is above the maximum, so the amount is not applied."
        onChange={({ min, max }) => setFilters({ amount_min: min || undefined, amount_max: max || undefined })}
      />
    ) : (
      <FilterSelect
        key={spec.key}
        label={spec.label}
        value={(values[spec.key] as string | undefined) ?? "all"}
        options={toOptions(spec.options)}
        onValueChange={(value) => setFilters({ [spec.key]: value === "all" ? undefined : value })}
      />
    );
  const hidden = specs.filter((spec) => spec.group);
  return {
    inline: specs.filter((spec) => !spec.group).map(control),
    more: moreFilterSpecGroups(specs).map((group) => ({ title: group.title, content: group.specs.map(control) })),
    activeCount: hidden.filter((spec) => specActive(spec, values)).length,
    chips: compactChips(
      hidden.map((spec) => {
        if (spec.kind === "amount") {
          const text = amountRangeLabel(values.amount_min ?? "", values.amount_max ?? "");
          return text
            ? {
                id: "amount",
                label: `${spec.label}: ${text}`,
                onRemove: () => setFilters({ amount_min: undefined, amount_max: undefined }),
              }
            : null;
        }
        return selectFilterChip(
          spec.key,
          spec.label,
          values[spec.key] as string | undefined,
          toOptions(spec.options),
          () => setFilters({ [spec.key]: undefined }),
        );
      }),
    ),
  };
}

/** Only the filters `specs` offer, without empty values. */
function keepOffered(filters: StaffAnalyticsFilterValues, specs: readonly FilterSpec[]): StaffAnalyticsFilterValues {
  const offered = new Set(specs.flatMap(specKeys));
  return Object.fromEntries(
    Object.entries(filters).filter(([name, current]) => current && offered.has(name as FilterKey)),
  ) as StaffAnalyticsFilterValues;
}

/**
 * Applies `patch` and drops any other filter the new combination no longer
 * offers (picking Offers clears Placement and Banner type, say), so a hidden
 * control never keeps narrowing the numbers.
 */
export function withFilters(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues,
  patch: StaffAnalyticsFilterValues,
  context: RoleFilterContext = {},
): StaffAnalyticsFilterValues {
  const next = { ...filters, ...patch } as StaffAnalyticsFilterValues;
  // The content type and the filter just picked decide what stays, so the
  // newest choice wins over an older one it rules out.
  const deciding = { content_type: next.content_type, ...patch } as StaffAnalyticsFilterValues;
  return keepOffered(next, filtersForRole(role, line, deciding, context));
}

/** `withFilters` for one key (kept for the single-select callers and tests). */
export function withFilter(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues,
  key: FilterKey,
  value: string | undefined,
): StaffAnalyticsFilterValues {
  return withFilters(role, line, filters, { [key]: value } as StaffAnalyticsFilterValues);
}

/**
 * The filters to send: only those the role offers on this line (a filter of
 * the other line, or one the Admin now hides, is never sent — the API would
 * refuse it), amounts normalised to plain rupees, and an inverted amount
 * range left out.
 */
export function requestFilters(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues,
  context: RoleFilterContext = {},
): StaffAnalyticsFilterValues {
  const offered = keepOffered(filters, filtersForRole(role, line, filters, context));
  const min = parseRupees(offered.amount_min ?? "");
  const max = parseRupees(offered.amount_max ?? "");
  const inverted = amountRangeInverted(offered.amount_min ?? "", offered.amount_max ?? "");
  const { amount_min: _min, amount_max: _max, ...rest } = offered;
  return {
    ...rest,
    ...(min !== null && !inverted ? { amount_min: String(min) } : {}),
    ...(max !== null && !inverted ? { amount_max: String(max) } : {}),
  };
}

// Period + business line + role filters for "My analytics". The business-line
// control switches the dashboard's active line, so every screen (and the API's
// line-scoped access) stays on the same line.
export function StaffAnalyticsFilterBar({
  role,
  range,
  onRangeChange,
  filters,
  onFiltersChange,
  context,
}: {
  role: string | undefined;
  range: DateRangeValue;
  onRangeChange: (range: DateRangeValue) => void;
  filters: StaffAnalyticsFilterValues;
  onFiltersChange: (filters: StaffAnalyticsFilterValues) => void;
  context?: RoleFilterContext;
}) {
  const { activeLine, setActiveLine, lines, canSwitch } = useLine();
  const specs = filtersForRole(role, activeLine, filters, context);
  const shown = keepOffered(filters, specs);
  const controls = roleFilterControls(specs, shown, (patch) =>
    onFiltersChange(withFilters(role, activeLine, filters, patch, context)),
  );
  const active = Object.values(shown).some(Boolean);

  return (
    <div role="group" aria-label="Analytics filters">
      <FilterBar
        value={EMPTY_FILTERS}
        onChange={() => undefined}
        searchLabel="Search analytics"
        showSearch={false}
        showStatus={false}
        showLine={false}
        showDates={false}
        extra={
          <>
            <DateRangePicker value={range} onChange={onRangeChange} className="sm:w-full" />
            {canSwitch && lines.length > 1 ? (
              <Select value={activeLine} onValueChange={(value) => setActiveLine(value as typeof activeLine)}>
                <SelectTrigger className="w-full" aria-label="Business line">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {lines.map((line) => (
                    <SelectItem key={line} value={line}>
                      {LINE_LABEL[line] ?? line}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            {controls.inline}
          </>
        }
        more={controls.more}
        moreActiveCount={controls.activeCount}
        chips={controls.chips}
        hasExternalFilters={active}
        onClear={() => onFiltersChange({})}
        onClearMore={() =>
          onFiltersChange(
            Object.fromEntries(
              Object.entries(filters).filter(([name]) =>
                specs.some((spec) => !spec.group && specKeys(spec).includes(name as FilterKey)),
              ),
            ) as StaffAnalyticsFilterValues,
          )
        }
      />
    </div>
  );
}
