"use client";

import { Input } from "@/components/ui/input";
import { AmountRangeFields } from "@/features/dashboard/amount-range-fields";
import { optionsFromLabels } from "@/features/dashboard/filter-options";
import { DateRangeFields, FilterSelect } from "@/features/dashboard/filter-select";
import type { MoreFilterGroup } from "@/features/dashboard/more-filters";
import {
  DEAL_STATUS_LABEL,
  PROPERTY_CATEGORY_LABEL,
  PROPERTY_SUBTYPE_LABEL,
  TRANSACTION_PRESENCE_LABEL,
} from "@/features/dashboard/product-filter-options";

import {
  CALL_STATUS_FILTER_LABEL,
  INTEREST_LABEL,
  LOAN_STATUS_LABEL,
  NO_LEAD_SIGNAL_OPTIONS,
  REFERRER_SOURCE_LABEL,
  type LeadSignalFilters,
  type LeadSignalOptions,
  type LeadSignalScope,
} from "./lead-signal-filters";

const CALL_STATUS_OPTIONS = optionsFromLabels(CALL_STATUS_FILTER_LABEL);
const INTEREST_OPTIONS = optionsFromLabels(INTEREST_LABEL);
const SOURCE_OPTIONS = optionsFromLabels(REFERRER_SOURCE_LABEL);
const LOAN_STATUS_OPTIONS = optionsFromLabels(LOAN_STATUS_LABEL);
const DEAL_STATUS_OPTIONS = optionsFromLabels(DEAL_STATUS_LABEL);
const CATEGORY_OPTIONS = optionsFromLabels(PROPERTY_CATEGORY_LABEL);
const SUBTYPE_OPTIONS = optionsFromLabels(PROPERTY_SUBTYPE_LABEL);
const PRESENCE_OPTIONS = optionsFromLabels(TRANSACTION_PRESENCE_LABEL);

/**
 * The lead filters behind "More filters", shared by the Telecaller leads list,
 * the Employee tasks list and a manager's team work: Lead (call status,
 * interest, source, referred by), Product (loans line: product, bank, loan
 * status) or Property (real estate line: category, type, deal status), and
 * Money (Telecaller transactions: has or none, date range, bank, amount),
 * leaving out any transaction part the Admin hides.
 */
export function leadSignalFilterGroups({
  filters,
  onChange,
  scope,
  options = NO_LEAD_SIGNAL_OPTIONS,
}: {
  filters: LeadSignalFilters;
  onChange: (patch: Partial<LeadSignalFilters>) => void;
  scope: LeadSignalScope;
  options?: LeadSignalOptions;
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
  if (scope.loans) {
    groups.push({
      title: "Product",
      content: (
        <>
          <FilterSelect
            label="Product"
            value={filters.loanTypeId}
            options={options.loanTypes}
            onValueChange={(loanTypeId) => onChange({ loanTypeId })}
          />
          <FilterSelect
            label="Bank"
            value={filters.bankId}
            options={options.banks}
            onValueChange={(bankId) => onChange({ bankId })}
          />
          <FilterSelect
            label="Loan status"
            value={filters.loanStatus}
            options={LOAN_STATUS_OPTIONS}
            onValueChange={(value) => onChange({ loanStatus: value as LeadSignalFilters["loanStatus"] })}
          />
        </>
      ),
    });
  }
  if (scope.property) {
    groups.push({
      title: "Property",
      content: (
        <>
          <FilterSelect
            label="Property category"
            value={filters.propertyCategory}
            options={CATEGORY_OPTIONS}
            onValueChange={(propertyCategory) => onChange({ propertyCategory })}
          />
          <FilterSelect
            label="Property type"
            value={filters.propertySubtype}
            options={SUBTYPE_OPTIONS}
            onValueChange={(propertySubtype) => onChange({ propertySubtype })}
          />
          <FilterSelect
            label="Deal status"
            value={filters.dealStatus}
            options={DEAL_STATUS_OPTIONS}
            onValueChange={(dealStatus) => onChange({ dealStatus })}
          />
        </>
      ),
    });
  }
  if (scope.transactions) {
    const hidden = scope.hiddenTransactionParts ?? new Set<string>();
    groups.push({
      title: "Money",
      content: (
        <>
          <FilterSelect
            label="Transactions"
            value={filters.txnPresence}
            options={PRESENCE_OPTIONS}
            onValueChange={(value) => onChange({ txnPresence: value as LeadSignalFilters["txnPresence"] })}
          />
          {hidden.has("bank_names") ? null : (
            <FilterSelect
              label="Transaction bank"
              value={filters.txnBank}
              options={options.transactionBanks}
              onValueChange={(txnBank) => onChange({ txnBank })}
            />
          )}
          {hidden.has("dates") ? null : (
            <DateRangeFields
              from={filters.txnFrom}
              to={filters.txnTo}
              onFromChange={(txnFrom) => onChange({ txnFrom })}
              onToChange={(txnTo) => onChange({ txnTo })}
              fromLabel="Transaction date from"
              toLabel="Transaction date to"
            />
          )}
          {hidden.has("amount") ? null : (
            <AmountRangeFields
              legend="Transaction amount (₹)"
              name="transaction amount"
              min={filters.txnAmountMin}
              max={filters.txnAmountMax}
              onChange={({ min, max }) => onChange({ txnAmountMin: min, txnAmountMax: max })}
            />
          )}
        </>
      ),
    });
  }
  return groups;
}
