"use client";

import * as React from "react";

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
import {
  compactChips,
  selectFilterChip,
  type ActiveFilterChip,
} from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { BHK_OPTIONS } from "@/lib/property-facets";
import {
  CONSTRUCTION_OPTIONS,
  FURNISHING_OPTIONS,
  LISTING_INTENT_OPTIONS,
} from "@/lib/property-submit";
import { PROPERTY_SUBTYPE_GROUPS, PROPERTY_SUBTYPE_OPTIONS } from "@/lib/property-taxonomy";

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

const BEDROOM_OPTIONS: readonly FilterOption[] = BHK_OPTIONS.map((option) => ({
  value: String(option.value),
  label: option.label,
}));

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

/** "Price (₹): 10000 – 50000", "Area (sq ft): from 900" or null while both are blank. */
function rangeChip(
  id: string,
  label: string,
  min: string,
  max: string,
  onRemove: () => void,
): ActiveFilterChip | null {
  if (!min && !max) return null;
  const text = min && max ? `${min} – ${max}` : min ? `from ${min}` : `up to ${max}`;
  return { id, label: `${label}: ${text}`, onRemove };
}

/**
 * Filters for an author's own listings: the shared FilterBar (search, status,
 * category, sort, submitted From / To) with sale or rent, property facets,
 * review state and price/area behind "More filters", whose active values show
 * as removable chips.
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

  const moreActiveCount = countAdvancedSubmissionFilters(value) + (value.intent !== "all" ? 1 : 0);
  const chips = compactChips([
    selectFilterChip("intent", "Sale or rent", value.intent, LISTING_INTENT_OPTIONS, () => set({ intent: "all" })),
    selectFilterChip("subtype", "Property type", value.subtype, PROPERTY_SUBTYPE_OPTIONS, () =>
      set({ subtype: "all" }),
    ),
    selectFilterChip("city", "City", value.city, cityOptions, () => set({ city: "all" })),
    selectFilterChip("bhk", "Bedrooms", value.bhk, BEDROOM_OPTIONS, () => set({ bhk: "all" })),
    selectFilterChip("furnishing", "Furnishing", value.furnishing, FURNISHING_OPTIONS, () =>
      set({ furnishing: "all" }),
    ),
    selectFilterChip("construction", "Construction status", value.construction, CONSTRUCTION_OPTIONS, () =>
      set({ construction: "all" }),
    ),
    selectFilterChip("rera", "RERA review", value.rera, RERA_REVIEW_OPTIONS, () => set({ rera: "all" })),
    selectFilterChip("panorama", "360° images", value.panorama, PRESENCE_OPTIONS("360° images"), () =>
      set({ panorama: "all" }),
    ),
    selectFilterChip("documents", "Documents", value.documents, PRESENCE_OPTIONS("documents"), () =>
      set({ documents: "all" }),
    ),
    rangeChip("price", "Price (₹)", value.priceMin, value.priceMax, () => set({ priceMin: "", priceMax: "" })),
    rangeChip("area", "Area (sq ft)", value.areaMin, value.areaMax, () => set({ areaMin: "", areaMax: "" })),
  ]);

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
      statusLabel="Status"
      kindOptions={CATEGORY_OPTIONS}
      kindLabel="Category"
      showLine={false}
      dateFromLabel="Submitted from"
      dateToLabel="Submitted to"
      hasExternalFilters={countActiveSubmissionFilters(value) > 0}
      onClear={() => onChange(EMPTY_SUBMISSION_FILTERS)}
      extra={
        <Select value={value.sort} onValueChange={(sort) => set({ sort: sort as SubmissionFilters["sort"] })}>
          <SelectTrigger aria-label="Sort listings">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SUBMISSION_SORT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
      more={[
        {
          title: "Property",
          content: (
            <>
              <FilterSelect
                label="Sale or rent"
                value={value.intent}
                options={LISTING_INTENT_OPTIONS}
                onValueChange={(intent) => set({ intent: intent as SubmissionFilters["intent"] })}
              />
              <FilterSelect
                label="Property type"
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
              </FilterSelect>
              <FilterSelect label="City" value={value.city} options={cityOptions} onValueChange={(city) => set({ city })} />
              <FilterSelect
                label="Bedrooms"
                value={value.bhk}
                options={BEDROOM_OPTIONS}
                onValueChange={(bhk) => set({ bhk })}
              />
              <FilterSelect
                label="Furnishing"
                value={value.furnishing}
                options={FURNISHING_OPTIONS}
                onValueChange={(furnishing) => set({ furnishing: furnishing as SubmissionFilters["furnishing"] })}
              />
              <FilterSelect
                label="Construction status"
                value={value.construction}
                options={CONSTRUCTION_OPTIONS}
                onValueChange={(construction) =>
                  set({ construction: construction as SubmissionFilters["construction"] })
                }
              />
            </>
          ),
        },
        {
          title: "Review",
          content: (
            <>
              <FilterSelect
                label="RERA review"
                value={value.rera}
                options={RERA_REVIEW_OPTIONS}
                onValueChange={(rera) => set({ rera: rera as SubmissionFilters["rera"] })}
              />
              <FilterSelect
                label="360° images"
                value={value.panorama}
                options={PRESENCE_OPTIONS("360° images")}
                onValueChange={(panorama) => set({ panorama: panorama as SubmissionFilters["panorama"] })}
              />
              <FilterSelect
                label="Documents"
                value={value.documents}
                options={PRESENCE_OPTIONS("documents")}
                onValueChange={(documents) => set({ documents: documents as SubmissionFilters["documents"] })}
              />
            </>
          ),
        },
        {
          title: "Price and area",
          content: (
            <>
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
            </>
          ),
        },
      ]}
      moreActiveCount={moreActiveCount}
      onClearMore={() =>
        set({
          intent: "all",
          subtype: "all",
          city: "all",
          bhk: "all",
          furnishing: "all",
          construction: "all",
          rera: "all",
          panorama: "all",
          documents: "all",
          priceMin: "",
          priceMax: "",
          areaMin: "",
          areaMax: "",
        })
      }
      chips={chips}
    />
  );
}
