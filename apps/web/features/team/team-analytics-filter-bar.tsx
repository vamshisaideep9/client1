"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { sameList } from "@/features/analytics/analytics-format";
import { DateRangePicker } from "@/features/analytics/date-range-picker";
import {
  filtersForRole,
  requestFilters,
  roleFilterControls,
  withFilters,
  type RoleFilterContext,
} from "@/features/analytics/staff-analytics-filter-bar";
import { EMPTY_FILTERS, FilterBar } from "@/features/dashboard/filter-bar";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import type { DateRangeValue } from "@/lib/analytics-range";
import { personName, type StaffTeam, type TeamAnalyticsFilters } from "@/lib/staff-teams-api";
import { useDebouncedValue } from "@/lib/use-debounced-value";

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
 * The catalogue options, Admin-hidden filters and the settled request for a
 * team's analytics: only filters the member role offers on the team's line,
 * typed amounts debounced and normalised (CS-023).
 */
export function useTeamAnalyticsRequest(
  team: StaffTeam,
  filters: TeamAnalyticsFilters,
  hiddenFilters: readonly string[],
): { context: RoleFilterContext; sent: TeamAnalyticsFilters } {
  const catalogue = useProductCatalogue(team.business_line === "loans");
  const context = React.useMemo(
    () => ({ loanTypes: catalogue.loanTypes, banks: catalogue.banks, hiddenFilters }),
    [catalogue, hiddenFilters],
  );
  const settled = useDebouncedValue(filters);
  const sent = React.useMemo(() => {
    const { members, ...roleFilters } = settled;
    return {
      ...requestFilters(team.member_role, team.business_line, roleFilters, context),
      ...(members?.length ? { members } : {}),
    };
  }, [settled, team.member_role, team.business_line, context]);
  return { context, sent };
}

/**
 * The Admin-hidden filters the last analytics response reported, and the
 * setter to report a response's list (an equal list keeps the same value, so
 * the request does not change).
 */
export function useHiddenFilters(): [readonly string[], (reported: readonly string[] | undefined) => void] {
  const [hidden, setHidden] = React.useState<readonly string[]>([]);
  const report = React.useCallback((reported: readonly string[] | undefined) => {
    if (reported) setHidden((current) => (sameList(current, reported) ? current : reported));
  }, []);
  return [hidden, report];
}

/**
 * Period, members and role filters for a manager's team or member analytics.
 * The role filters are the same ones the member's own "My analytics" offers
 * (Telecaller: call status, interest, lead source, product or property and
 * amount; Employee: task type, product or property), and the API rejects any
 * the team's role or line lacks.
 */
export function TeamAnalyticsFilterBar({
  team,
  range,
  onRangeChange,
  filters,
  onFiltersChange,
  withMembers,
  context,
}: {
  team: StaffTeam;
  range: DateRangeValue;
  onRangeChange: (range: DateRangeValue) => void;
  filters: TeamAnalyticsFilters;
  onFiltersChange: (filters: TeamAnalyticsFilters) => void;
  withMembers: boolean;
  context?: RoleFilterContext;
}) {
  const specs = filtersForRole(team.member_role, team.business_line, {}, context);
  const { members, ...roleFilters } = filters;
  const controls = roleFilterControls(specs, roleFilters, (patch) =>
    onFiltersChange({
      ...withFilters(team.member_role, team.business_line, roleFilters, patch, context),
      ...(members ? { members } : {}),
    }),
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
        onClearMore={() => {
          const firstRow = new Set<string>(specs.filter((spec) => !spec.group).map((spec) => spec.key));
          onFiltersChange({
            ...Object.fromEntries(Object.entries(roleFilters).filter(([name]) => firstRow.has(name))),
            ...(members ? { members } : {}),
          });
        }}
      />
    </div>
  );
}
