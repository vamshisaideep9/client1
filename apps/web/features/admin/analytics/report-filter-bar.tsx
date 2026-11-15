"use client";

import * as React from "react";
import { ChevronDownIcon } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DateRangePicker } from "@/features/analytics/date-range-picker";
import {
  EMPTY_FILTERS,
  FilterBar,
  type FilterBarValue,
} from "@/features/dashboard/filter-bar";
import {
  INTEREST_LABEL,
  LOAN_STATUS_LABEL,
  REFERRER_SOURCE_LABEL,
} from "@/features/telecaller/lead-signal-filters";
import { DISPOSITION_LABEL, STATUS_LABEL } from "@/features/telecaller/telecaller-lead-status";
import { listAdminBanks, listAdminLoanTypes } from "@/lib/loan-config-api";
import { activeDetailCount, resolveDatePreset, type ReportDetailFilters } from "@/lib/reports";
import {
  getReportTelecallers,
  type ReportBucket,
  type ReportBusinessLine,
  type ReportKind,
} from "@/lib/reports-api";
import { cn } from "@/lib/utils";
import { useAgentOptions } from "./use-agent-options";

const BUCKET_OPTIONS: { value: ReportBucket; label: string }[] = [
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
];

const DEAL_STATUS_LABEL: Record<string, string> = {
  new: "New",
  contacted: "Contacted",
  site_visit_done: "Site visit done",
  negotiation: "Negotiation",
  booked: "Booked",
  agreement_signed: "Agreement signed",
  closed: "Closed",
  rejected: "Rejected",
  on_hold: "On hold",
};

const PROPERTY_CATEGORY_LABEL: Record<string, string> = {
  houses: "Houses",
  apartments: "Apartments",
  villas: "Villas",
  plots: "Plots",
  commercial: "Commercial",
};

export type ReportFilterValue = {
  dateFrom: string;
  dateTo: string;
  bucket: ReportBucket;
  businessLine: ReportBusinessLine | undefined;
  agentProfileUuids: string[];
  detail: ReportDetailFilters;
};

function baselineFilters(): ReportFilterValue {
  const { dateFrom, dateTo } = resolveDatePreset("this_month", new Date());
  return {
    dateFrom,
    dateTo,
    bucket: "week",
    businessLine: undefined,
    agentProfileUuids: [],
    detail: {},
  };
}

type Option = { value: string; label: string };

function useOptions(load: () => Promise<Option[] | null>, deps: React.DependencyList): Option[] {
  const [options, setOptions] = React.useState<Option[]>([]);
  React.useEffect(() => {
    let active = true;
    void load().then((next) => {
      if (active && next) setOptions(next);
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return options;
}

function DetailSelect({
  label,
  all,
  value,
  options,
  onChange,
}: {
  label: string;
  all: string;
  value: string | undefined;
  options: Option[] | Record<string, string>;
  onChange: (value: string | undefined) => void;
}) {
  const list = Array.isArray(options)
    ? options
    : Object.entries(options).map(([optionValue, optionLabel]) => ({ value: optionValue, label: optionLabel }));
  return (
    <Select value={value ?? "all"} onValueChange={(next) => onChange(next === "all" ? undefined : next)}>
      <SelectTrigger className="w-full" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{all}</SelectItem>
        {list.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Types into a local box and applies after a pause, so each keystroke isn't a fetch. */
function CityInput({ value, onChange }: { value: string | undefined; onChange: (value: string | undefined) => void }) {
  const [draft, setDraft] = React.useState(value ?? "");
  React.useEffect(() => setDraft(value ?? ""), [value]);
  React.useEffect(() => {
    const handle = window.setTimeout(() => {
      const next = draft.trim() || undefined;
      if (next !== (value ?? undefined)) onChange(next);
    }, 400);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);
  return (
    <Input
      aria-label="Property city"
      placeholder="Property city"
      value={draft}
      maxLength={120}
      onChange={(event) => setDraft(event.target.value)}
    />
  );
}

// Date range (calendar picker), business line, grouping and agents for every
// report, plus the report's own filters: lead source, telecaller, latest call
// outcome and interest for leads/loans/deals; lead status for leads; loan
// status, type and bank for loans; deal status and property city/category for
// deals. Every value is applied server-side and carried into CSV/Excel exports.
export function ReportFilterBar({
  kind,
  value,
  onChange,
}: {
  kind: ReportKind;
  value: ReportFilterValue;
  onChange: (next: ReportFilterValue) => void;
}) {
  const [agentQuery, setAgentQuery] = React.useState("");
  const [agentPopoverOpen, setAgentPopoverOpen] = React.useState(false);
  const { options: agentOptions, loading: agentsLoading } = useAgentOptions(value.businessLine);
  const journey = kind !== "agents";
  const telecallers = useOptions(
    async () => {
      if (!journey) return [];
      const res = await getReportTelecallers(value.businessLine);
      return res.ok
        ? res.data.map((t) => ({ value: t.staff_profile_uuid, label: `${t.name} (${t.staff_code})` }))
        : null;
    },
    [journey, value.businessLine],
  );
  const loanTypes = useOptions(
    async () => {
      if (kind !== "loans") return [];
      const res = await listAdminLoanTypes();
      return res.ok ? res.data.map((t) => ({ value: t.id, label: t.label })) : null;
    },
    [kind],
  );
  const banks = useOptions(
    async () => {
      if (kind !== "loans") return [];
      const res = await listAdminBanks();
      return res.ok ? res.data.map((b) => ({ value: b.id, label: b.name })) : null;
    },
    [kind],
  );

  const baseline = baselineFilters();
  const filters: FilterBarValue = { ...EMPTY_FILTERS, line: value.businessLine ?? "all" };
  const detailCount = activeDetailCount(value.detail);
  const filtersCustomized =
    value.dateFrom !== baseline.dateFrom ||
    value.dateTo !== baseline.dateTo ||
    value.bucket !== baseline.bucket ||
    value.businessLine !== baseline.businessLine ||
    value.agentProfileUuids.length > 0 ||
    detailCount > 0;

  function updateSharedFilters(next: FilterBarValue) {
    const businessLine = next.line === "all" ? undefined : (next.line as ReportBusinessLine);
    // A telecaller picked on one line is meaningless after switching lines.
    const detail =
      businessLine !== value.businessLine ? { ...value.detail, telecallerProfileUuid: undefined } : value.detail;
    onChange({ ...value, businessLine, detail });
  }

  function setDetail<K extends keyof ReportDetailFilters>(key: K, next: ReportDetailFilters[K]) {
    onChange({ ...value, detail: { ...value.detail, [key]: next } });
  }

  function toggleAgent(id: string) {
    const agentProfileUuids = value.agentProfileUuids.includes(id)
      ? value.agentProfileUuids.filter((agentId) => agentId !== id)
      : [...value.agentProfileUuids, id];
    onChange({ ...value, agentProfileUuids });
  }

  const filteredAgentOptions = agentOptions.filter((option) =>
    option.label.toLowerCase().includes(agentQuery.trim().toLowerCase()),
  );

  return (
    <FilterBar
      value={filters}
      onChange={updateSharedFilters}
      onClear={() => onChange(baseline)}
      searchLabel="Search report"
      showSearch={false}
      showStatus={false}
      showDates={false}
      showClear={filtersCustomized}
      extra={
        <>
          <DateRangePicker
            value={{ dateFrom: value.dateFrom, dateTo: value.dateTo }}
            onChange={(range) => onChange({ ...value, ...range })}
            className="sm:w-full"
          />
          {journey ? (
            <Select
              value={value.bucket}
              onValueChange={(bucket) => onChange({ ...value, bucket: bucket as ReportBucket })}
            >
              <SelectTrigger className="w-full" aria-label="Report grouping">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BUCKET_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}

          <Popover open={agentPopoverOpen} onOpenChange={setAgentPopoverOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="Filter by agents"
                className={cn(
                  "flex h-9 min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  value.agentProfileUuids.length === 0 && "text-muted-foreground",
                )}
              >
                <span className="truncate">
                  {value.agentProfileUuids.length === 0
                    ? "All agents"
                    : `${value.agentProfileUuids.length} selected`}
                </span>
                <ChevronDownIcon className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[280px] p-2">
              <Input
                aria-label="Search agents"
                placeholder="Search agents"
                value={agentQuery}
                maxLength={100}
                onChange={(event) => setAgentQuery(event.target.value)}
                className="mb-2"
              />
              {value.agentProfileUuids.length > 0 ? (
                <button
                  type="button"
                  onClick={() => onChange({ ...value, agentProfileUuids: [] })}
                  className="mb-1 w-full rounded-md px-2 py-1.5 text-left text-xs font-medium text-brand-link hover:bg-muted"
                >
                  Clear selected agents
                </button>
              ) : null}
              <div className="max-h-56 overflow-y-auto">
                {agentsLoading ? (
                  <p className="p-2 text-xs text-text-secondary">Loading agents…</p>
                ) : filteredAgentOptions.length === 0 ? (
                  <p className="p-2 text-xs text-text-secondary">No agents found.</p>
                ) : (
                  filteredAgentOptions.map((option) => (
                    <label
                      key={option.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                    >
                      <Checkbox
                        checked={value.agentProfileUuids.includes(option.id)}
                        onCheckedChange={() => toggleAgent(option.id)}
                      />
                      <span className="truncate">{option.label}</span>
                    </label>
                  ))
                )}
              </div>
            </PopoverContent>
          </Popover>

          {journey ? (
            <>
              <DetailSelect
                label="Lead source"
                all="Any lead source"
                value={value.detail.leadSource}
                options={REFERRER_SOURCE_LABEL}
                onChange={(next) => setDetail("leadSource", next as ReportDetailFilters["leadSource"])}
              />
              <DetailSelect
                label="Telecaller"
                all="All telecallers"
                value={value.detail.telecallerProfileUuid}
                options={telecallers}
                onChange={(next) => setDetail("telecallerProfileUuid", next)}
              />
              <DetailSelect
                label="Latest call status"
                all="Any call outcome"
                value={value.detail.callStatus}
                options={DISPOSITION_LABEL}
                onChange={(next) => setDetail("callStatus", next)}
              />
              <DetailSelect
                label="Interest"
                all="Any interest"
                value={value.detail.interest}
                options={INTEREST_LABEL}
                onChange={(next) => setDetail("interest", next)}
              />
            </>
          ) : null}
          {kind === "leads" ? (
            <DetailSelect
              label="Lead status"
              all="All lead statuses"
              value={value.detail.leadStatus}
              options={STATUS_LABEL}
              onChange={(next) => setDetail("leadStatus", next)}
            />
          ) : null}
          {kind === "loans" ? (
            <>
              <DetailSelect
                label="Loan status"
                all="All loan statuses"
                value={value.detail.loanStatus}
                options={LOAN_STATUS_LABEL}
                onChange={(next) => setDetail("loanStatus", next)}
              />
              <DetailSelect
                label="Loan type"
                all="All loan types"
                value={value.detail.loanTypeId}
                options={loanTypes}
                onChange={(next) => setDetail("loanTypeId", next)}
              />
              <DetailSelect
                label="Bank"
                all="All banks"
                value={value.detail.bankId}
                options={banks}
                onChange={(next) => setDetail("bankId", next)}
              />
            </>
          ) : null}
          {kind === "deals" ? (
            <>
              <DetailSelect
                label="Deal status"
                all="All deal statuses"
                value={value.detail.dealStatus}
                options={DEAL_STATUS_LABEL}
                onChange={(next) => setDetail("dealStatus", next)}
              />
              <DetailSelect
                label="Property category"
                all="All categories"
                value={value.detail.propertyCategory}
                options={PROPERTY_CATEGORY_LABEL}
                onChange={(next) => setDetail("propertyCategory", next)}
              />
              <CityInput value={value.detail.propertyCity} onChange={(next) => setDetail("propertyCity", next)} />
            </>
          ) : null}
        </>
      }
    />
  );
}
