"use client";

import type * as React from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import {
  compactChips,
  optionsFromLabels,
  selectFilterChip,
  type ActiveFilterChip,
} from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { useLine } from "@/features/dashboard/line-provider";
import type { MoreFilterGroup } from "@/features/dashboard/more-filters";
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
/**
 * One role filter. `group` is the "More filters" section it belongs to, or
 * null for a filter that stays in the first row (the role's status filter).
 */
export type FilterSpec = {
  key: FilterKey;
  label: string;
  options: Record<string, string>;
  group: string | null;
};

/**
 * Which filters each role's analytics understand (mirrors the API). The
 * current filters only matter for the Sub Admin: banner-only filters hide
 * while Content type is Offers, and the offer-only one while it is Banners.
 */
export function filtersForRole(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues = {},
): FilterSpec[] {
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
      ...(line === "loans"
        ? [{ key: "loan_status" as const, label: "Loan status", options: LOAN_STATUS_LABEL, group: "Loan" }]
        : []),
      { key: "lead_source", label: "Lead source", options: REFERRER_SOURCE_LABEL, group: "Lead" },
    ];
  }
  if (role === "employee") {
    return [{ key: "task_type", label: "Task type", options: TASK_TYPE_LABEL, group: null }];
  }
  if (role === "agent") {
    return [{ key: "lead_status", label: "Lead status", options: STATUS_LABEL, group: null }];
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

/** More-filter groups, active count and chips for a set of role filter specs. */
export function roleFilterControls(
  specs: readonly FilterSpec[],
  values: Partial<Record<FilterKey, string | undefined>>,
  setFilter: (key: FilterKey, value: string | undefined) => void,
): { inline: React.ReactNode; more: MoreFilterGroup[]; activeCount: number; chips: ActiveFilterChip[] } {
  const control = (spec: FilterSpec) => (
    <FilterSelect
      key={spec.key}
      label={spec.label}
      value={values[spec.key] ?? "all"}
      options={optionsFromLabels(spec.options)}
      onValueChange={(value) => setFilter(spec.key, value === "all" ? undefined : value)}
    />
  );
  const hidden = specs.filter((spec) => spec.group);
  return {
    inline: specs.filter((spec) => !spec.group).map(control),
    more: moreFilterSpecGroups(specs).map((group) => ({ title: group.title, content: group.specs.map(control) })),
    activeCount: hidden.filter((spec) => Boolean(values[spec.key])).length,
    chips: compactChips(
      hidden.map((spec) =>
        selectFilterChip(spec.key, spec.label, values[spec.key], spec.options, () => setFilter(spec.key, undefined)),
      ),
    ),
  };
}

/**
 * Sets one filter and drops any other filter the new combination no longer
 * offers (picking Offers clears Placement and Banner type, say), so a hidden
 * control never keeps narrowing the numbers.
 */
export function withFilter(
  role: string | undefined,
  line: string,
  filters: StaffAnalyticsFilterValues,
  key: FilterKey,
  value: string | undefined,
): StaffAnalyticsFilterValues {
  const next = { ...filters, [key]: value } as StaffAnalyticsFilterValues;
  // The content type and the filter just picked decide what stays, so the
  // newest choice wins over an older one it rules out.
  const deciding = { content_type: next.content_type, [key]: value } as StaffAnalyticsFilterValues;
  const offered = new Set(filtersForRole(role, line, deciding).map((spec) => spec.key));
  return Object.fromEntries(
    Object.entries(next).filter(([name, current]) => current && offered.has(name as FilterKey)),
  ) as StaffAnalyticsFilterValues;
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
}: {
  role: string | undefined;
  range: DateRangeValue;
  onRangeChange: (range: DateRangeValue) => void;
  filters: StaffAnalyticsFilterValues;
  onFiltersChange: (filters: StaffAnalyticsFilterValues) => void;
}) {
  const { activeLine, setActiveLine, lines, canSwitch } = useLine();
  const specs = filtersForRole(role, activeLine, filters);
  const controls = roleFilterControls(specs, filters, (key, value) =>
    onFiltersChange(withFilter(role, activeLine, filters, key, value)),
  );
  const active = Object.values(filters).some(Boolean);

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
      />
    </div>
  );
}
