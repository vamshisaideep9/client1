"use client";

import { Input } from "@/components/ui/input";
import { optionsFromLabels } from "@/features/dashboard/filter-options";
import { FilterSelect } from "@/features/dashboard/filter-select";
import type { MoreFilterGroup } from "@/features/dashboard/more-filters";

import {
  CALL_STATUS_FILTER_LABEL,
  INTEREST_LABEL,
  LOAN_STATUS_LABEL,
  REFERRER_SOURCE_LABEL,
  type LeadSignalFilters,
} from "./lead-signal-filters";

const CALL_STATUS_OPTIONS = optionsFromLabels(CALL_STATUS_FILTER_LABEL);
const INTEREST_OPTIONS = optionsFromLabels(INTEREST_LABEL);
const SOURCE_OPTIONS = optionsFromLabels(REFERRER_SOURCE_LABEL);
const LOAN_STATUS_OPTIONS = optionsFromLabels(LOAN_STATUS_LABEL);

/**
 * The call status / lead interest / lead source / referred-by controls (and
 * loan status on the Loans line) as "More filters" groups, shared by the
 * Telecaller leads list, the Employee tasks list and a manager's team work.
 */
export function leadSignalFilterGroups({
  filters,
  onChange,
  showLoanStatus,
}: {
  filters: LeadSignalFilters;
  onChange: (patch: Partial<LeadSignalFilters>) => void;
  showLoanStatus: boolean;
}): MoreFilterGroup[] {
  const groups: MoreFilterGroup[] = [
    {
      title: "Lead",
      content: (
        <>
          <FilterSelect
            label="Call status"
            value={filters.callStatus}
            options={CALL_STATUS_OPTIONS}
            onValueChange={(value) => onChange({ callStatus: value as LeadSignalFilters["callStatus"] })}
          />
          <FilterSelect
            label="Lead interest"
            value={filters.interest}
            options={INTEREST_OPTIONS}
            onValueChange={(value) => onChange({ interest: value as LeadSignalFilters["interest"] })}
          />
          <FilterSelect
            label="Lead source"
            value={filters.source}
            options={SOURCE_OPTIONS}
            onValueChange={(value) => onChange({ source: value as LeadSignalFilters["source"] })}
          />
          <Input
            aria-label="Referred by ID"
            placeholder="Referred by ID"
            value={filters.referredBy}
            maxLength={40}
            autoCapitalize="characters"
            spellCheck={false}
            onChange={(event) => onChange({ referredBy: event.target.value })}
          />
        </>
      ),
    },
  ];
  if (showLoanStatus) {
    groups.push({
      title: "Loan",
      content: (
        <FilterSelect
          label="Loan status"
          value={filters.loanStatus}
          options={LOAN_STATUS_OPTIONS}
          onValueChange={(value) => onChange({ loanStatus: value as LeadSignalFilters["loanStatus"] })}
        />
      ),
    });
  }
  return groups;
}
