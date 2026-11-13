"use client";

import * as React from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Slider } from "@/components/ui/slider";
import { formatBudgetRange } from "@/lib/property-budget";
import { BudgetFacet } from "./budget-facet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { subtypeGroupsFor, visibleFacets } from "@/lib/property-facet-map";
import { LISTING_INTENT_OPTIONS } from "@/lib/property-submit";
import {
  AMENITIES,
  BHK_OPTIONS,
  FURNISHING_OPTIONS,
  STATUS_OPTIONS,
  type SuggestionIndex,
} from "@/lib/property-facets";
import {
  RE_CATEGORIES,
  type Furnishing,
  type ListingStatus,
  type PropertyFilters,
  type RECategory,
  type RESubtype,
} from "@/lib/real-estate";

// Sections that carry the most intent are open on mount; the long tail
// (amenities, city, locality) starts collapsed so the sheet stays scannable at
// 390px instead of running to several screens of scroll.
const DEFAULT_OPEN = ["name", "intent", "type", "subtype", "budget", "bedrooms"];

// Shell-agnostic grouped facet controls. Rendered inside PropertyFilterSheet;
// kept separate so the facet set can be reused (e.g. in a future desktop
// popover shell) without pulling in the Sheet chrome.
//
// Which sections appear is decided by lib/property-facet-map.ts rather than by
// a residential-or-not boolean, so a plot never offers bedrooms and a
// commercial unit never offers a bedroom count while keeping its fit-out state.
export function PropertyFilterBody({
  filters,
  setFilters,
  lockedCategory,
  suggestionIndex,
}: {
  filters: PropertyFilters;
  setFilters: (patch: Partial<PropertyFilters>) => void;
  // When the page is pinned to one category, hide the Property-type facet and
  // scope the subtype options and facet visibility to that category.
  lockedCategory?: RECategory;
  suggestionIndex: SuggestionIndex;
}) {
  const areaRange = suggestionIndex.areaBounds;
  const [areaDraft, setAreaDraft] = React.useState<[number, number]>([
    filters.areaMin ?? areaRange.min,
    filters.areaMax ?? areaRange.max,
  ]);

  React.useEffect(() => {
    setAreaDraft([filters.areaMin ?? areaRange.min, filters.areaMax ?? areaRange.max]);
  }, [filters.areaMin, filters.areaMax, areaRange.min, areaRange.max]);

  function toggleArrayValue<T extends string>(current: T[] | undefined, value: T): T[] | undefined {
    const set = new Set(current ?? []);
    if (set.has(value)) set.delete(value);
    else set.add(value);
    return set.size > 0 ? Array.from(set) : undefined;
  }

  const activeCategories = lockedCategory ? [lockedCategory] : filters.categories;
  const facets = visibleFacets(activeCategories, filters.subtypes);
  const subtypeGroups = subtypeGroupsFor(activeCategories, suggestionIndex.subtypes);

  const localityOptions = filters.city
    ? Array.from(
        new Set(
          suggestionIndex.properties
            .filter((property) => property.city === filters.city)
            .map((property) => property.locality),
        ),
      ).sort()
    : suggestionIndex.localities;

  return (
    <Accordion type="multiple" defaultValue={DEFAULT_OPEN} className="w-full">
      {/* Name first: buyers often know the project or the developer brand
          ("My Home", "Sattva") and want every listing that carries it. */}
      <FacetSection
        value="name"
        heading="Property or developer"
        count={(filters.q?.trim() ? 1 : 0) + (filters.developer ? 1 : 0)}
      >
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="filter-property-name" className="text-text-primary">
              Property or project name
            </Label>
            <Input
              id="filter-property-name"
              value={filters.q ?? ""}
              maxLength={100}
              onChange={(event) => setFilters({ q: event.target.value.slice(0, 100) || undefined })}
              placeholder="e.g. My Home Bhooja"
            />
          </div>
          {suggestionIndex.developers.length > 0 ? (
            <div className="grid gap-1.5">
              <span className="text-sm font-medium text-text-primary">Developer / builder</span>
              <SearchableSelect
                value={filters.developer}
                onChange={(v) => setFilters({ developer: v })}
                options={suggestionIndex.developers}
                placeholder="Any developer"
              />
            </div>
          ) : null}
        </div>
      </FacetSection>

      {/* First facet: sale and rent listings price on different scales, so
          narrowing intent is what makes the price facet below meaningful. */}
      <FacetSection value="intent" heading="Listing for" count={filters.intent?.length ?? 0}>
        <ToggleGroup
          type="multiple"
          value={filters.intent ?? []}
          onValueChange={(value) =>
            setFilters({
              intent: value.length ? (value as NonNullable<PropertyFilters["intent"]>) : undefined,
            })
          }
        >
          {LISTING_INTENT_OPTIONS.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </FacetSection>

      {lockedCategory ? null : (
        <FacetSection value="type" heading="Property type" count={filters.categories?.length ?? 0}>
          <ToggleGroup
            type="multiple"
            value={filters.categories ?? []}
            onValueChange={(value) =>
              setFilters({ categories: value.length ? (value as RECategory[]) : undefined })
            }
          >
            {RE_CATEGORIES.map((c) => (
              <ToggleGroupItem key={c.key} value={c.key}>
                {c.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </FacetSection>
      )}

      {facets.has("subtype") && subtypeGroups.length > 0 ? (
        <FacetSection
          value="subtype"
          heading="Property subtype"
          count={filters.subtypes?.length ?? 0}
        >
          <div className="space-y-4">
            {subtypeGroups.map((group) => (
              <div key={group.heading} className="space-y-2">
                {/* The group heading only earns its place when more than one
                    group is on screen; pinned to a single category it would
                    just restate the section. */}
                {subtypeGroups.length > 1 ? (
                  <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">
                    {group.heading}
                  </p>
                ) : null}
                <ToggleGroup
                  type="multiple"
                  value={filters.subtypes ?? []}
                  onValueChange={(value) =>
                    setFilters({ subtypes: value.length ? (value as RESubtype[]) : undefined })
                  }
                >
                  {group.items.map((item) => (
                    <ToggleGroupItem key={item.value} value={item.value}>
                      {item.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
            ))}
          </div>
        </FacetSection>
      ) : null}

      {facets.has("bhk") ? (
        <FacetSection value="bedrooms" heading="Bedrooms" count={filters.bhk?.length ?? 0}>
          <ToggleGroup
            type="multiple"
            value={(filters.bhk ?? []).map(String)}
            onValueChange={(value) =>
              setFilters({ bhk: value.length ? value.map(Number) : undefined })
            }
          >
            {BHK_OPTIONS.map((b) => (
              <ToggleGroupItem key={b.value} value={String(b.value)}>
                {b.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </FacetSection>
      ) : null}

      {facets.has("price") ? (
        <FacetSection
          value="budget"
          heading="Budget"
          summary={
            filters.budgetMin != null || filters.budgetMax != null
              ? formatBudgetRange(filters.budgetMin, filters.budgetMax)
              : undefined
          }
        >
          <BudgetFacet
            budgetMin={filters.budgetMin}
            budgetMax={filters.budgetMax}
            onCommit={(patch) => setFilters(patch)}
          />
        </FacetSection>
      ) : null}

      {facets.has("area") ? (
        <FacetSection
          value="area"
          heading="Area (sqft)"
          summary={`${areaDraft[0].toLocaleString("en-IN")} - ${areaDraft[1].toLocaleString("en-IN")} sqft`}
        >
          <Slider
            value={areaDraft}
            thumbLabels={["Minimum area in square feet", "Maximum area in square feet"]}
            min={areaRange.min}
            max={areaRange.max}
            step={50}
            onValueChange={(value) => setAreaDraft(value as [number, number])}
            onValueCommit={(value) => setFilters({ areaMin: value[0], areaMax: value[1] })}
            className="[&_[data-slot=slider-range]]:bg-brand-cta [&_[data-slot=slider-thumb]]:border-brand-cta"
          />
        </FacetSection>
      ) : null}

      {facets.has("status") ? (
        <FacetSection
          value="status"
          heading="Construction status"
          count={filters.status?.length ?? 0}
        >
          <div className="flex flex-col gap-2.5">
            {STATUS_OPTIONS.map((s) => (
              <label key={s.value} className="flex cursor-pointer items-center gap-2.5">
                <Checkbox
                  checked={(filters.status ?? []).includes(s.value)}
                  onCheckedChange={() =>
                    setFilters({ status: toggleArrayValue<ListingStatus>(filters.status, s.value) })
                  }
                  className="data-[state=checked]:border-brand-cta data-[state=checked]:bg-brand-cta"
                />
                <Label className="font-normal text-text-primary">{s.label}</Label>
              </label>
            ))}
          </div>
        </FacetSection>
      ) : null}

      {facets.has("furnishing") ? (
        <FacetSection
          value="furnishing"
          heading="Furnishing"
          count={filters.furnishing?.length ?? 0}
        >
          <ToggleGroup
            type="multiple"
            value={filters.furnishing ?? []}
            onValueChange={(value) =>
              setFilters({ furnishing: value.length ? (value as Furnishing[]) : undefined })
            }
          >
            {FURNISHING_OPTIONS.map((f) => (
              <ToggleGroupItem key={f.value} value={f.value}>
                {f.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </FacetSection>
      ) : null}

      {facets.has("amenities") ? (
        <FacetSection value="amenities" heading="Amenities" count={filters.amenities?.length ?? 0}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
            {AMENITIES.map((a) => (
              <label key={a.value} className="flex cursor-pointer items-center gap-2.5">
                <Checkbox
                  checked={(filters.amenities ?? []).includes(a.value)}
                  onCheckedChange={() =>
                    setFilters({ amenities: toggleArrayValue(filters.amenities, a.value) })
                  }
                  className="data-[state=checked]:border-brand-cta data-[state=checked]:bg-brand-cta"
                />
                <Label className="font-normal text-text-primary">{a.label}</Label>
              </label>
            ))}
          </div>
        </FacetSection>
      ) : null}

      <FacetSection value="city" heading="City" summary={filters.city ?? undefined}>
        <SearchableSelect
          value={filters.city}
          onChange={(v) => setFilters({ city: v })}
          options={suggestionIndex.cities}
          placeholder="Any city"
        />
      </FacetSection>

      <FacetSection
        value="locality"
        heading="Area / Locality"
        summary={filters.locality ?? undefined}
      >
        <SearchableSelect
          value={filters.locality}
          onChange={(v) => setFilters({ locality: v })}
          options={localityOptions}
          placeholder="Any locality"
        />
      </FacetSection>
    </Accordion>
  );
}

// One collapsible facet group. The trigger carries a summary of what is set so
// a collapsed section still tells the user it is constraining their results.
function FacetSection({
  value,
  heading,
  count,
  summary,
  children,
}: {
  value: string;
  heading: string;
  count?: number;
  summary?: string;
  children: React.ReactNode;
}) {
  return (
    <AccordionItem value={value}>
      <AccordionTrigger className="py-4 hover:no-underline">
        <span className="flex flex-1 items-center justify-between gap-3 pr-2">
          <span className="text-sm font-semibold text-text-primary">{heading}</span>
          {summary ? (
            <span className="text-sm font-normal text-text-secondary">{summary}</span>
          ) : count ? (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-cta-tint px-1.5 text-xs font-medium text-brand-link">
              {count}
            </span>
          ) : null}
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-5">{children}</AccordionContent>
    </AccordionItem>
  );
}
