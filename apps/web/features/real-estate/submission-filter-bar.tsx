"use client";

import * as React from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FilterBar, type FilterBarValue, type FilterOption } from "@/features/dashboard/filter-bar";
import { BHK_OPTIONS } from "@/lib/property-facets";
import {
  CONSTRUCTION_OPTIONS,
  FURNISHING_OPTIONS,
  LISTING_INTENT_OPTIONS,
} from "@/lib/property-submit";
import { PROPERTY_SUBTYPE_GROUPS } from "@/lib/property-taxonomy";
import { cn } from "@/lib/utils";

import {
  CATEGORY_OPTIONS,
  EMPTY_SUBMISSION_FILTERS,
  RERA_REVIEW_OPTIONS,
  SUBMISSION_SORT_OPTIONS,
  SUBMISSION_STATUS_OPTIONS,
  countActiveSubmissionFilters,
  countAdvancedSubmissionFilters,
  normalizeSubmissionFilters,
  type SubmissionFilters,
} from "./submission-filters";

const PRESENCE_OPTIONS = (noun: string): readonly FilterOption[] => [
  { value: "yes", label: `With ${noun}` },
  { value: "no", label: `Without ${noun}` },
];

function FacetSelect({
  label,
  allLabel,
  value,
  options,
  onValueChange,
  children,
}: {
  label: string;
  /** Omit for a control with no "all" choice, such as sort order. */
  allLabel?: string;
  value: string;
  options?: readonly FilterOption[];
  onValueChange: (value: string) => void;
  children?: React.ReactNode;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {allLabel ? <SelectItem value="all">{allLabel}</SelectItem> : null}
        {options?.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
        {children}
      </SelectContent>
    </Select>
  );
}

function digitsOnly(value: string): string {
  return value.replace(/\D/g, "").slice(0, 13);
}

function RangeField({
  id,
  legend,
  unit,
  min,
  max,
  onChange,
}: {
  id: string;
  legend: string;
  unit: string;
  min: string;
  max: string;
  onChange: (min: string, max: string) => void;
}) {
  const inverted = min !== "" && max !== "" && Number(min) > Number(max);
  const hintId = `${id}-hint`;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 text-xs font-medium text-text-secondary">
        {legend} ({unit})
      </legend>
      <div className="grid grid-cols-2 gap-2">
        <Input
          aria-label={`Minimum ${legend.toLowerCase()} (${unit})`}
          aria-describedby={inverted ? hintId : undefined}
          aria-invalid={inverted || undefined}
          inputMode="numeric"
          placeholder="Min"
          value={min}
          onChange={(event) => onChange(digitsOnly(event.target.value), max)}
        />
        <Input
          aria-label={`Maximum ${legend.toLowerCase()} (${unit})`}
          aria-describedby={inverted ? hintId : undefined}
          aria-invalid={inverted || undefined}
          inputMode="numeric"
          placeholder="Max"
          value={max}
          onChange={(event) => onChange(min, digitsOnly(event.target.value))}
        />
      </div>
      {inverted ? (
        <p id={hintId} className="mt-1 text-xs text-error">
          The minimum is above the maximum.
        </p>
      ) : null}
    </fieldset>
  );
}

/**
 * Filters for an author's own listings: the shared FilterBar (search, status,
 * category, submitted dates) plus sale/rent and sort, with the less common
 * facets behind a "More filters" disclosure so the bar stays compact on phones.
 */
export function SubmissionFilterBar({
  value,
  onChange,
  cityOptions,
}: {
  value: SubmissionFilters;
  onChange: (value: SubmissionFilters) => void;
  cityOptions: readonly FilterOption[];
}) {
  const advancedCount = countAdvancedSubmissionFilters(value);
  // Opened on arrival when a shared link already narrows an advanced field.
  const [open, setOpen] = React.useState(() => advancedCount > 0);
  const panelId = React.useId();
  const set = (patch: Partial<SubmissionFilters>) =>
    onChange(normalizeSubmissionFilters({ ...value, ...patch }));

  const barValue: FilterBarValue = {
    search: value.search,
    status: value.status,
    line: "all",
    kind: value.category,
    from: value.from,
    to: value.to,
  };

  const subtypeGroups = PROPERTY_SUBTYPE_GROUPS.map((group) => ({
    heading: group.heading,
    items: group.items.filter(
      (item) => value.category === "all" || item.category === value.category,
    ),
  })).filter((group) => group.items.length > 0);

  return (
    <FilterBar
      value={barValue}
      onChange={(next) =>
        set({
          search: next.search,
          status: next.status as SubmissionFilters["status"],
          category: next.kind as SubmissionFilters["category"],
          from: next.from,
          to: next.to,
        })
      }
      searchLabel="Search your listings"
      searchPlaceholder="Title, locality, pincode or RERA"
      statusOptions={SUBMISSION_STATUS_OPTIONS}
      statusLabel="statuses"
      kindOptions={CATEGORY_OPTIONS}
      kindLabel="Categories"
      showLine={false}
      dateFromLabel="Submitted from"
      dateToLabel="Submitted to"
      hasExternalFilters={countActiveSubmissionFilters(value) > 0}
      onClear={() => onChange(EMPTY_SUBMISSION_FILTERS)}
      extra={
        <>
          <FacetSelect
            label="Sale or rent"
            allLabel="Sale and rent"
            value={value.intent}
            options={LISTING_INTENT_OPTIONS}
            onValueChange={(intent) => set({ intent: intent as SubmissionFilters["intent"] })}
          />
          <FacetSelect
            label="Sort listings"
            value={value.sort}
            options={SUBMISSION_SORT_OPTIONS}
            onValueChange={(sort) => set({ sort: sort as SubmissionFilters["sort"] })}
          />
        </>
      }
      advanced={
        <div className="mt-3 border-t border-border pt-3">
          <Button
            type="button"
            variant="ghost"
            className="-ml-2 gap-2"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((current) => !current)}
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
            More filters
            {advancedCount > 0 ? (
              <span className="grid h-5 min-w-5 place-items-center rounded-full bg-brand-cta px-1.5 text-xs font-semibold text-white tabular-nums">
                {advancedCount}
                <span className="sr-only"> active</span>
              </span>
            ) : null}
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform duration-150 motion-reduce:transition-none",
                open && "rotate-180",
              )}
              aria-hidden="true"
            />
          </Button>
          <div
            id={panelId}
            hidden={!open}
            className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] items-end gap-2 [&_[data-slot=select-trigger]]:w-full"
          >
            <FacetSelect
              label="Property type"
              allLabel="All property types"
              value={value.subtype}
              onValueChange={(subtype) => set({ subtype: subtype as SubmissionFilters["subtype"] })}
            >
              {subtypeGroups.map((group) => (
                <SelectGroup key={group.heading}>
                  <SelectLabel>{group.heading}</SelectLabel>
                  {group.items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </FacetSelect>
            <FacetSelect
              label="City"
              allLabel="All cities"
              value={value.city}
              options={cityOptions}
              onValueChange={(city) => set({ city })}
            />
            <FacetSelect
              label="Bedrooms"
              allLabel="Any BHK"
              value={value.bhk}
              options={BHK_OPTIONS.map((option) => ({ value: String(option.value), label: option.label }))}
              onValueChange={(bhk) => set({ bhk })}
            />
            <FacetSelect
              label="Furnishing"
              allLabel="Any furnishing"
              value={value.furnishing}
              options={FURNISHING_OPTIONS}
              onValueChange={(furnishing) =>
                set({ furnishing: furnishing as SubmissionFilters["furnishing"] })
              }
            />
            <FacetSelect
              label="Construction status"
              allLabel="Any construction status"
              value={value.construction}
              options={CONSTRUCTION_OPTIONS}
              onValueChange={(construction) =>
                set({ construction: construction as SubmissionFilters["construction"] })
              }
            />
            <FacetSelect
              label="RERA review"
              allLabel="Any RERA review"
              value={value.rera}
              options={RERA_REVIEW_OPTIONS}
              onValueChange={(rera) => set({ rera: rera as SubmissionFilters["rera"] })}
            />
            <FacetSelect
              label="360° images"
              allLabel="Any 360° images"
              value={value.panorama}
              options={PRESENCE_OPTIONS("360° images")}
              onValueChange={(panorama) =>
                set({ panorama: panorama as SubmissionFilters["panorama"] })
              }
            />
            <FacetSelect
              label="Documents"
              allLabel="Any documents"
              value={value.documents}
              options={PRESENCE_OPTIONS("documents")}
              onValueChange={(documents) =>
                set({ documents: documents as SubmissionFilters["documents"] })
              }
            />
            <RangeField
              id={`${panelId}-price`}
              legend="Price"
              unit="₹"
              min={value.priceMin}
              max={value.priceMax}
              onChange={(priceMin, priceMax) => set({ priceMin, priceMax })}
            />
            <RangeField
              id={`${panelId}-area`}
              legend="Area"
              unit="sq ft"
              min={value.areaMin}
              max={value.areaMax}
              onChange={(areaMin, areaMax) => set({ areaMin, areaMax })}
            />
          </div>
        </div>
      }
    />
  );
}
