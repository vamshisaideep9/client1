"use client";

import * as React from "react";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableSelect } from "@/components/ui/searchable-select";
import {
  cityLabel,
  isValidPincode,
  listDistricts,
  type PincodeDistrict,
} from "@/lib/pincodes";

export const MAX_PINCODE_TARGETS = 100;
export const MAX_CITY_TARGETS = 50;

type City = { district: string; state: string };

// CS-026: pincode and city targets for a Client-only campaign. They match a
// consenting Client's profile pincode; a city is a district from the built-in
// pincode list.
export function PlaceTargets({
  pincodes,
  cities,
  onChange,
  disabled = false,
}: {
  pincodes: string[];
  cities: City[];
  onChange: (next: { pincodes: string[]; cities: City[] }) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = React.useState("");
  const [draftError, setDraftError] = React.useState<string | null>(null);
  const [districts, setDistricts] = React.useState<PincodeDistrict[] | null>(null);
  const [districtsError, setDistrictsError] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    void listDistricts().then((result) => {
      if (!active) return;
      if (result.ok) setDistricts(result.data);
      else setDistrictsError(true);
    });
    return () => {
      active = false;
    };
  }, []);

  function addPincodes() {
    const values = draft.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
    if (values.length === 0) return;
    const invalid = values.find((item) => !isValidPincode(item));
    if (invalid) {
      setDraftError(`${invalid} is not a valid pincode (six digits, not starting with 0).`);
      return;
    }
    const next = [...pincodes];
    for (const value of values) if (!next.includes(value)) next.push(value);
    if (next.length > MAX_PINCODE_TARGETS) {
      setDraftError(`Up to ${MAX_PINCODE_TARGETS} pincodes.`);
      return;
    }
    setDraftError(null);
    setDraft("");
    onChange({ pincodes: next, cities });
  }

  const cityOptions = (districts ?? [])
    .filter((option) => !cities.some((city) => sameCity(city, option)))
    .map(cityLabel);

  function addCity(label: string | undefined) {
    if (!label || !districts) return;
    const match = districts.find((option) => cityLabel(option) === label);
    if (!match || cities.length >= MAX_CITY_TARGETS) return;
    onChange({ pincodes, cities: [...cities, { district: match.district, state: match.state }] });
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="audience-pincodes">Pincodes</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="audience-pincodes"
            value={draft}
            inputMode="numeric"
            placeholder="e.g. 500001, 500032"
            disabled={disabled || pincodes.length >= MAX_PINCODE_TARGETS}
            onChange={(event) => {
              setDraft(event.target.value);
              setDraftError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addPincodes();
              }
            }}
            aria-invalid={Boolean(draftError)}
            aria-describedby={draftError ? "audience-pincodes-error" : "audience-pincodes-help"}
          />
          <Button
            type="button"
            variant="outline"
            onClick={addPincodes}
            disabled={disabled || !draft.trim()}
          >
            <Plus className="h-4 w-4" aria-hidden="true" /> Add pincodes
          </Button>
        </div>
        {draftError ? (
          <p id="audience-pincodes-error" role="alert" className="text-sm text-destructive">
            {draftError}
          </p>
        ) : (
          <p id="audience-pincodes-help" className="text-xs text-text-secondary">
            Separate several with commas. Each must be on the built-in pincode list.
          </p>
        )}
        <Chips
          label="Targeted pincodes"
          items={pincodes.map((pincode) => ({ key: pincode, label: pincode }))}
          disabled={disabled}
          onRemove={(key) => onChange({ pincodes: pincodes.filter((p) => p !== key), cities })}
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium text-text-primary">Cities</p>
        <SearchableSelect
          value={undefined}
          onChange={addCity}
          options={cityOptions}
          placeholder={
            districtsError
              ? "City list unavailable"
              : districts === null
                ? "Loading cities…"
                : cities.length >= MAX_CITY_TARGETS
                  ? `Up to ${MAX_CITY_TARGETS} cities`
                  : "Search for a city (district)"
          }
          disabled={disabled || !districts || cities.length >= MAX_CITY_TARGETS}
        />
        <Chips
          label="Targeted cities"
          items={cities.map((city) => ({ key: cityLabel(city), label: cityLabel(city) }))}
          disabled={disabled}
          onRemove={(key) =>
            onChange({ pincodes, cities: cities.filter((city) => cityLabel(city) !== key) })
          }
        />
      </div>
    </div>
  );
}

function sameCity(a: City, b: City): boolean {
  return (
    a.district.toLowerCase() === b.district.toLowerCase() &&
    a.state.toLowerCase() === b.state.toLowerCase()
  );
}

function Chips({
  label,
  items,
  onRemove,
  disabled,
}: {
  label: string;
  items: { key: string; label: string }[];
  onRemove: (key: string) => void;
  disabled: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <ul aria-label={label} className="flex flex-wrap gap-2">
      {items.map((item) => (
        <li
          key={item.key}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 py-1 pl-3 pr-1 text-sm text-text-primary"
        >
          {item.label}
          <button
            type="button"
            disabled={disabled}
            onClick={() => onRemove(item.key)}
            className="inline-flex h-7 w-7 items-center justify-center rounded-full text-text-secondary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Remove ${item.label}`}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}
