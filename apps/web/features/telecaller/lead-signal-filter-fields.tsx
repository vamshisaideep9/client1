"use client";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import {
  INTEREST_LABEL,
  LOAN_STATUS_LABEL,
  LOAN_STATUS_OPTIONS,
  REFERRER_SOURCE_LABEL,
  type LeadSignalFilters,
  type ReferrerSource,
} from "./lead-signal-filters";
import { DISPOSITION_LABEL } from "./telecaller-lead-status";

const CALL_STATUS_OPTIONS = Object.keys(DISPOSITION_LABEL);
const INTEREST_OPTIONS = Object.keys(INTEREST_LABEL) as (keyof typeof INTEREST_LABEL)[];
const SOURCE_OPTIONS = Object.keys(REFERRER_SOURCE_LABEL) as ReferrerSource[];

// The loan status / call status / interest / referred-by controls, rendered as
// grid cells so each list places them inside its own filter grid. Loan status
// only applies to the Loans line, so callers hide it on Real Estate.
export function LeadSignalFilterFields({
  filters,
  onChange,
  showLoanStatus,
}: {
  filters: LeadSignalFilters;
  onChange: (patch: Partial<LeadSignalFilters>) => void;
  showLoanStatus: boolean;
}) {
  return (
    <>
      {showLoanStatus ? (
        <Select
          value={filters.loanStatus}
          onValueChange={(value) => onChange({ loanStatus: value as LeadSignalFilters["loanStatus"] })}
        >
          <SelectTrigger className="w-full" aria-label="Filter by loan status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All loan statuses</SelectItem>
            {LOAN_STATUS_OPTIONS.map((value) => (
              <SelectItem key={value} value={value}>
                {LOAN_STATUS_LABEL[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
      <Select
        value={filters.callStatus}
        onValueChange={(value) => onChange({ callStatus: value as LeadSignalFilters["callStatus"] })}
      >
        <SelectTrigger className="w-full" aria-label="Filter by call status">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All call statuses</SelectItem>
          <SelectItem value="not_called">Not called yet</SelectItem>
          {CALL_STATUS_OPTIONS.map((value) => (
            <SelectItem key={value} value={value}>
              {DISPOSITION_LABEL[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={filters.interest}
        onValueChange={(value) => onChange({ interest: value as LeadSignalFilters["interest"] })}
      >
        <SelectTrigger className="w-full" aria-label="Filter by interest">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Any interest</SelectItem>
          {INTEREST_OPTIONS.map((value) => (
            <SelectItem key={value} value={value}>
              {INTEREST_LABEL[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={filters.source}
        onValueChange={(value) => onChange({ source: value as LeadSignalFilters["source"] })}
      >
        <SelectTrigger className="w-full" aria-label="Filter by referral">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Any referral</SelectItem>
          {SOURCE_OPTIONS.map((value) => (
            <SelectItem key={value} value={value}>
              {REFERRER_SOURCE_LABEL[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
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
  );
}
