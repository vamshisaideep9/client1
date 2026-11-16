"use client";

import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DateRangePicker } from "@/features/analytics/date-range-picker";
import { filtersForRole, roleFilterControls } from "@/features/analytics/staff-analytics-filter-bar";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
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
  // Unfiltered, the trigger names the field like every other filter.
  const label =
    selected.length === 0
      ? "Members"
      : selected.length === 1
        ? personName(team.members.find((m) => m.staff_profile_uuid === selected[0]) ?? team.members[0])
        : `${selected.length} members`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="w-full justify-between font-normal"
          aria-label={selected.length === 0 ? "Members" : `Members: ${label}`}
        >
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
  const controls = roleFilterControls(specs, filters, (key, value) =>
    onFiltersChange({ ...filters, [key]: value }),
  );
  const active = Object.entries(filters).some(([, value]) =>
    Array.isArray(value) ? value.length > 0 : Boolean(value),
  );
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
            {withMembers ? (
              <MemberPicker
                team={team}
                selected={filters.members ?? []}
                onChange={(members) => onFiltersChange({ ...filters, members })}
              />
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
