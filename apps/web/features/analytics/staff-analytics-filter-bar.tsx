"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLine } from "@/features/dashboard/line-provider";
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
type FilterSpec = { key: FilterKey; label: string; all: string; options: Record<string, string> };

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
    const banners = filters.content_type !== "offers";
    const offers = filters.content_type !== "banners";
    return [
      { key: "content_type", label: "Content type", all: "Banners and offers", options: CONTENT_TYPE_LABEL },
      { key: "content_status", label: "Review status", all: "Any review status", options: CONTENT_STATUS_LABEL },
      ...(banners
        ? [
            { key: "placement" as const, label: "Placement", all: "Any placement", options: PLACEMENT_LABEL },
            { key: "banner_type" as const, label: "Banner type", all: "Any banner type", options: BANNER_TYPE_LABEL },
          ]
        : []),
      ...(offers
        ? [{ key: "discount_type" as const, label: "Discount type", all: "Any discount", options: DISCOUNT_TYPE_LABEL }]
        : []),
    ];
  }
  if (role === "telecaller") {
    return [
      { key: "call_status", label: "Call status", all: "All call outcomes", options: DISPOSITION_LABEL },
      { key: "interest", label: "Interest", all: "Any interest", options: INTEREST_LABEL },
      ...(line === "loans"
        ? [{ key: "loan_status" as const, label: "Loan status", all: "All loan statuses", options: LOAN_STATUS_LABEL }]
        : []),
      { key: "lead_source", label: "Lead source", all: "Any source", options: REFERRER_SOURCE_LABEL },
    ];
  }
  if (role === "employee") {
    return [{ key: "task_type", label: "Task type", all: "All task types", options: TASK_TYPE_LABEL }];
  }
  if (role === "agent") {
    return [{ key: "lead_status", label: "Lead status", all: "All lead statuses", options: STATUS_LABEL }];
  }
  return [];
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
  const offered = new Set(filtersForRole(role, line, next).map((spec) => spec.key));
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
  const active = Object.values(filters).some(Boolean);

  return (
    <div
      role="group"
      aria-label="Analytics filters"
      className="grid gap-2 rounded-xl border border-border bg-card p-3 sm:grid-cols-2 lg:grid-cols-4"
    >
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
      {specs.map((spec) => (
        <Select
          key={spec.key}
          value={filters[spec.key] ?? "all"}
          onValueChange={(value) =>
            onFiltersChange(withFilter(role, activeLine, filters, spec.key, value === "all" ? undefined : value))
          }
        >
          <SelectTrigger className="w-full" aria-label={spec.label}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{spec.all}</SelectItem>
            {Object.entries(spec.options).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
      {active ? (
        <Button type="button" variant="ghost" className="justify-self-start" onClick={() => onFiltersChange({})}>
          <X className="h-4 w-4" aria-hidden="true" />
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}
