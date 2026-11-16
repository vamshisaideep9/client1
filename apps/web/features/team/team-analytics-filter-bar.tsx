"use client";

import { ChevronDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DateRangePicker } from "@/features/analytics/date-range-picker";
import { filtersForRole } from "@/features/analytics/staff-analytics-filter-bar";
import type { DateRangeValue } from "@/lib/analytics-range";
import { personName, type StaffTeam, type TeamAnalyticsFilters } from "@/lib/staff-teams-api";

function MemberPicker({
  team,
  selected,
  onChange,
}: {
  team: StaffTeam;
  selected: string[];
  onChange: (members: string[]) => void;
}) {
  const label =
    selected.length === 0
      ? "All members"
      : selected.length === 1
        ? personName(team.members.find((m) => m.staff_profile_uuid === selected[0]) ?? team.members[0])
        : `${selected.length} members`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" className="w-full justify-between" aria-label="Members">
          <span className="truncate">{label}</span>
          <ChevronDown aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2" align="start">
        <ul className="max-h-64 space-y-1 overflow-y-auto" aria-label="Choose members">
          {team.members.map((member) => {
            const id = member.staff_profile_uuid;
            const checked = selected.includes(id);
            return (
              <li key={id}>
                <Label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md px-2 font-normal hover:bg-background">
                  <Checkbox
                    checked={checked}
                    onCheckedChange={(value) =>
                      onChange(value ? [...selected, id] : selected.filter((item) => item !== id))
                    }
                  />
                  {personName(member)}
                </Label>
              </li>
            );
          })}
        </ul>
        {selected.length > 0 ? (
          <Button type="button" variant="ghost" size="sm" className="mt-1 w-full" onClick={() => onChange([])}>
            Show all members
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Period, members and role filters for a manager's team or member analytics.
 * The role filters are the same ones the member's own "My analytics" offers
 * (Telecaller: call status, interest, loan status on Loans, lead source;
 * Employee: task type), and the API rejects any the team's role lacks.
 */
export function TeamAnalyticsFilterBar({
  team,
  range,
  onRangeChange,
  filters,
  onFiltersChange,
  withMembers,
}: {
  team: StaffTeam;
  range: DateRangeValue;
  onRangeChange: (range: DateRangeValue) => void;
  filters: TeamAnalyticsFilters;
  onFiltersChange: (filters: TeamAnalyticsFilters) => void;
  withMembers: boolean;
}) {
  const specs = filtersForRole(team.member_role, team.business_line);
  const active = Object.entries(filters).some(([, value]) =>
    Array.isArray(value) ? value.length > 0 : Boolean(value),
  );
  return (
    <div
      className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
      role="group"
      aria-label="Analytics filters"
    >
      <DateRangePicker value={range} onChange={onRangeChange} className="sm:w-full" />
      {withMembers ? (
        <MemberPicker
          team={team}
          selected={filters.members ?? []}
          onChange={(members) => onFiltersChange({ ...filters, members })}
        />
      ) : null}
      {specs.map((spec) => (
        <Select
          key={spec.key}
          value={filters[spec.key] ?? "all"}
          onValueChange={(value) =>
            onFiltersChange({ ...filters, [spec.key]: value === "all" ? undefined : value })
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
        <Button
          type="button"
          variant="ghost"
          className="justify-self-start"
          onClick={() => onFiltersChange({})}
        >
          <X aria-hidden="true" /> Clear filters
        </Button>
      ) : null}
    </div>
  );
}
