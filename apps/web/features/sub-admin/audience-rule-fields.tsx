"use client";

import * as React from "react";
import { MapPin, Plus, Trash2 } from "lucide-react";

import type { components } from "@contracts/generated/schema";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DashboardFormSection } from "@/features/dashboard/dashboard-ui";

import { PlaceTargets } from "./place-targets";

type Schemas = components["schemas"];
export type AudienceRules = Schemas["AudienceRules"];
type UserType = NonNullable<AudienceRules["user_types"]>[number];
type ClientStage = NonNullable<AudienceRules["client_journey_stages"]>[number];
type AgentSignal = NonNullable<AudienceRules["agent_signals"]>[number];
type LocationCircle = Schemas["AudienceLocationCircle"];
type AudienceCity = Schemas["AudienceCity"];

const CLIENT_STAGES: { value: ClientStage; label: string }[] = [
  { value: "not_started", label: "Not started" },
  { value: "in_progress", label: "In progress" },
  { value: "on_hold", label: "On hold" },
  { value: "completed", label: "Completed" },
  { value: "rejected", label: "Rejected" },
  { value: "closed", label: "Closed enquiry" },
];

const AGENT_SIGNALS: { value: AgentSignal; label: string }[] = [
  { value: "no_leads", label: "No leads yet" },
  { value: "has_active_leads", label: "Has active leads" },
  { value: "has_converted_leads", label: "Has converted leads" },
  { value: "has_pending_commission", label: "Has pending commission" },
  { value: "has_paid_commission", label: "Has paid commission" },
];
const USER_TYPE_LABEL: Record<UserType, string> = {
  client: "Clients",
  agent: "Agents",
  employee: "Officers",
  telecaller: "Telecallers",
};

export function emptyAudienceRules(): AudienceRules {
  return {
    version: 1,
    user_types: [],
    client_journey_stages: [],
    agent_signals: [],
    locations: [],
    pincodes: [],
    cities: [],
  };
}

// CS-026: version 2 adds pincode and city targets. A rule is sent as the
// lowest version that can express it, so rules without them stay version 1.
export function normalizeAudienceRules(rules?: AudienceRules | null): AudienceRules {
  const pincodes = rules?.pincodes ?? [];
  const cities = rules?.cities ?? [];
  return {
    version: pincodes.length > 0 || cities.length > 0 ? 2 : 1,
    user_types: rules?.user_types ?? [],
    client_journey_stages: rules?.client_journey_stages ?? [],
    agent_signals: rules?.agent_signals ?? [],
    locations: rules?.locations ?? [],
    pincodes,
    cities,
  };
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function audienceSummary(rules?: AudienceRules | null): string {
  const normalized = normalizeAudienceRules(rules);
  const types = normalized.user_types ?? [];
  if (types.length === 0) return "Everyone";
  const details: string[] = [types.map((type) => USER_TYPE_LABEL[type]).join(" + ")];
  const signals =
    (normalized.client_journey_stages?.length ?? 0) + (normalized.agent_signals?.length ?? 0);
  if (signals > 0) details.push(`${signals} workflow ${signals === 1 ? "signal" : "signals"}`);
  if (normalized.locations?.length) {
    details.push(plural(normalized.locations.length, "area", "areas"));
  }
  if (normalized.cities?.length) details.push(plural(normalized.cities.length, "city", "cities"));
  if (normalized.pincodes?.length) {
    details.push(plural(normalized.pincodes.length, "pincode", "pincodes"));
  }
  return details.join(" · ");
}

/** Pincode and city targets reach consenting Clients only, so they make the audience Client-only. */
export function withPlaceTargets(
  rules: AudienceRules,
  places: { pincodes: string[]; cities: AudienceCity[] },
): AudienceRules {
  const normalized = normalizeAudienceRules(rules);
  const targeted = places.pincodes.length > 0 || places.cities.length > 0;
  return normalizeAudienceRules({
    ...normalized,
    user_types: targeted ? ["client"] : normalized.user_types,
    agent_signals: targeted ? [] : normalized.agent_signals,
    pincodes: places.pincodes,
    cities: places.cities,
  });
}

function toggleValue<T extends string>(values: T[], value: T, checked: boolean): T[] {
  return checked ? [...values, value] : values.filter((item) => item !== value);
}

export function withClientJourneyStages(
  rules: AudienceRules,
  stages: ClientStage[],
): AudienceRules {
  const normalized = normalizeAudienceRules(rules);
  return {
    ...normalized,
    user_types: stages.length > 0 ? ["client"] : normalized.user_types,
    client_journey_stages: stages,
    agent_signals: stages.length > 0 ? [] : normalized.agent_signals,
  };
}

export function withAgentSignals(
  rules: AudienceRules,
  signals: AgentSignal[],
): AudienceRules {
  const normalized = normalizeAudienceRules(rules);
  return normalizeAudienceRules({
    ...normalized,
    user_types: signals.length > 0 ? ["agent"] : normalized.user_types,
    client_journey_stages: signals.length > 0 ? [] : normalized.client_journey_stages,
    agent_signals: signals,
    // Place targets reach Clients only.
    pincodes: signals.length > 0 ? [] : normalized.pincodes,
    cities: signals.length > 0 ? [] : normalized.cities,
  });
}

export function AudienceRuleFields({
  value,
  onChange,
  required = false,
  disabled = false,
  allowedUserTypes = ["client", "agent"],
}: {
  value: AudienceRules;
  onChange: (next: AudienceRules) => void;
  required?: boolean;
  disabled?: boolean;
  allowedUserTypes?: UserType[];
}) {
  const rules = normalizeAudienceRules(value);
  const userTypes = rules.user_types ?? [];
  const clientStages = rules.client_journey_stages ?? [];
  const agentSignals = rules.agent_signals ?? [];
  const locations = rules.locations ?? [];
  const pincodes = rules.pincodes ?? [];
  const cities = rules.cities ?? [];
  const clientOnly = userTypes.length === 1 && userTypes[0] === "client";

  function setUserType(type: UserType, checked: boolean) {
    const nextTypes = toggleValue(userTypes, type, checked);
    const nextClientOnly = nextTypes.length === 1 && nextTypes[0] === "client";
    onChange(
      normalizeAudienceRules({
        ...rules,
        user_types: nextTypes,
        client_journey_stages: nextClientOnly ? clientStages : [],
        agent_signals:
          nextTypes.length === 1 && nextTypes[0] === "agent" ? agentSignals : [],
        locations: nextTypes.length === 0 ? [] : locations,
        pincodes: nextClientOnly ? pincodes : [],
        cities: nextClientOnly ? cities : [],
      }),
    );
  }

  function updateLocation(index: number, patch: Partial<LocationCircle>) {
    onChange({
      ...rules,
      locations: locations.map((circle, circleIndex) =>
        circleIndex === index ? { ...circle, ...patch } : circle,
      ),
    });
  }

  return (
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="sr-only">Audience targeting</legend>
      <DashboardFormSection
        title="Audience targeting"
        description={`Different sections are combined. Multiple choices inside one section are alternatives.${required ? " Select at least one user type." : " Leave user types empty for everyone."}`}
      >

      <div className="space-y-2">
        <p className="text-sm font-medium text-text-primary">User type</p>
        <div className="flex flex-wrap gap-4">
          {allowedUserTypes.map((type) => (
            <Label key={type} className="flex cursor-pointer items-center gap-2 font-normal">
              <Checkbox
                checked={userTypes.includes(type)}
                onCheckedChange={(checked) => setUserType(type, checked === true)}
              />
              {USER_TYPE_LABEL[type]}
            </Label>
          ))}
        </div>
        {required && userTypes.length === 0 ? (
          <p className="text-xs text-destructive">A personalized banner needs a user type.</p>
        ) : null}
      </div>

      {userTypes.includes("client") ? (
        <RuleCheckboxes
          label="Client journey"
          options={CLIENT_STAGES}
          values={clientStages}
          onChange={(next) => onChange(withClientJourneyStages(rules, next))}
        />
      ) : null}

      {userTypes.includes("agent") ? (
        <RuleCheckboxes
          label="Agent activity"
          options={AGENT_SIGNALS}
          values={agentSignals}
          onChange={(next) => onChange(withAgentSignals(rules, next))}
        />
      ) : null}

      <div className="space-y-3 border-t border-border pt-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-text-primary">Geographic areas</p>
            <p className="text-xs text-text-secondary">Optional circles, from 5 to 500 km.</p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={userTypes.length === 0 || locations.length >= 10}
            onClick={() =>
              onChange({
                ...rules,
                locations: [
                  ...locations,
                  { label: `Area ${locations.length + 1}`, latitude: 0, longitude: 0, radius_km: 25 },
                ],
              })
            }
          >
            <Plus className="h-4 w-4" /> Add area
          </Button>
        </div>

        {locations.map((circle, index) => (
          <div key={index} className="space-y-3 rounded-lg border border-border bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                <MapPin className="h-4 w-4" /> Area {index + 1}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove area ${index + 1}`}
                onClick={() =>
                  onChange({ ...rules, locations: locations.filter((_, item) => item !== index) })
                }
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Label htmlFor={`audience-area-${index}-label`}>Label</Label>
                <Input
                  id={`audience-area-${index}-label`}
                  value={circle.label}
                  maxLength={80}
                  onChange={(event) => updateLocation(index, { label: event.target.value })}
                />
              </div>
              <NumberField
                id={`audience-area-${index}-latitude`}
                label="Latitude"
                value={circle.latitude}
                min={-90}
                max={90}
                onChange={(latitude) => updateLocation(index, { latitude })}
              />
              <NumberField
                id={`audience-area-${index}-longitude`}
                label="Longitude"
                value={circle.longitude}
                min={-180}
                max={180}
                onChange={(longitude) => updateLocation(index, { longitude })}
              />
              <NumberField
                id={`audience-area-${index}-radius`}
                label="Radius (km)"
                value={circle.radius_km}
                min={5}
                max={500}
                onChange={(radius_km) => updateLocation(index, { radius_km })}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-3 border-t border-border pt-4">
        <div>
          <p className="text-sm font-medium text-text-primary">Pincodes and cities</p>
          <p className="text-xs text-text-secondary">
            {clientOnly
              ? "Optional. Reaches Clients whose profile pincode is listed or lies in a listed city, only while they have turned on personalized content and offers for their area. Any listed area, pincode or city counts."
              : "Available for a Clients-only audience: only Clients can turn on personalized content."}
          </p>
        </div>
        {clientOnly ? (
          <PlaceTargets
            pincodes={pincodes}
            cities={cities}
            disabled={disabled}
            onChange={(next) => onChange(withPlaceTargets(rules, next))}
          />
        ) : null}
      </div>
      </DashboardFormSection>
    </fieldset>
  );
}

function RuleCheckboxes<T extends string>({
  label,
  options,
  values,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  values: T[];
  onChange: (next: T[]) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-text-primary">{label}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <Label key={option.value} className="flex cursor-pointer items-center gap-2 font-normal">
            <Checkbox
              checked={values.includes(option.value)}
              onCheckedChange={(checked) =>
                onChange(toggleValue(values, option.value, checked === true))
              }
            />
            {option.label}
          </Label>
        ))}
      </div>
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        step="any"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}
