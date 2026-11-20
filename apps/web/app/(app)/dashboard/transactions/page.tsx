"use client";

import * as React from "react";
import { ArrowDownLeft, Coins, Gift, Trophy, Undo2, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useAuth } from "@/components/auth/session-provider";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { AgentTransactionSheet } from "@/features/agent/agent-transaction-sheet";
import { FetchError } from "@/features/dashboard/fetch-error";
import { EMPTY_FILTERS, FilterBar, filtersAreActive, type FilterBarValue } from "@/features/dashboard/filter-bar";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DashboardHeader, DashboardPage, DashboardPanel, MetricCard, MetricGrid } from "@/features/dashboard/dashboard-ui";
import { DASHBOARD_PAGE_SIZE, ListPagination, clampPaginationPage } from "@/features/dashboard/list-pagination";
import { TransactionDetailSheet, TRANSACTION_SOURCE } from "@/features/dashboard/transaction-detail-sheet";
import { formatPaise } from "@/lib/format";
import { rupeesToPaise } from "@/lib/payout-form";
import {
  getTransactions,
  mapTransaction,
  type TransactionPage,
  type TransactionStatus,
  type TransactionType,
} from "@/lib/transactions";
import { cn } from "@/lib/utils";

const TYPE_ICON: Record<TransactionType, LucideIcon> = {
  cashback: ArrowDownLeft,
  referral_bonus: Gift,
  commission: Coins,
  contest_reward: Trophy,
};

const STATUS_STYLE: Record<TransactionStatus, string> = {
  paid: "bg-success/10 text-success",
  processing: "bg-warning/10 text-warning",
  pending: "bg-warning/10 text-warning",
  failed: "bg-destructive/10 text-destructive",
};

const STATUS_LABEL: Record<TransactionStatus, string> = {
  paid: "Paid",
  processing: "Processing",
  pending: "Pending",
  failed: "Failed",
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "-"
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

type Status = "loading" | "ready" | "error";

function amountBound(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (/^-?0(?:\.0{1,2})?$/.test(trimmed)) return 0;
  const paise = rupeesToPaise(trimmed.replace(/^-/, ""));
  return paise === null ? null : trimmed.startsWith("-") ? -paise : paise;
}

export default function TransactionsPage() {
  const [data, setData] = React.useState<TransactionPage | null>(null);
  const [status, setStatus] = React.useState<Status>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [errorStatus, setErrorStatus] = React.useState<number | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [page, setPage] = React.useState(0);
  const [filters, setFilters] = React.useState<FilterBarValue>(EMPTY_FILTERS);
  const [minRupees, setMinRupees] = React.useState("");
  const [maxRupees, setMaxRupees] = React.useState("");
  const { session } = useAuth();
  const isAgent = session?.role === "agent";
  const [openTransactionId, setOpenTransactionId] = React.useState<string | null>(null);
  const detailTrigger = React.useRef<HTMLButtonElement | null>(null);
  const min = amountBound(minRupees);
  const max = amountBound(maxRupees);
  const rangeError =
    min === null || max === null ? "Enter a valid amount in rupees with up to two decimal places." :
    min !== undefined && max !== undefined && min > max ? "Minimum amount must be at or below the maximum." :
    filters.from && filters.to && filters.from > filters.to ? "The start date must be at or before the end date." : null;
  const hasFilters = filtersAreActive(filters) || Boolean(minRupees || maxRupees);

  const retry = React.useCallback(() => {
    setStatus("loading");
    setError(null);
    setErrorStatus(null);
    setReloadKey((k) => k + 1);
  }, []);

  React.useEffect(() => {
    if (rangeError) return;
    let active = true;
    const run = async () => {
      const res = await getTransactions({
        q: filters.search.trim(),
        status_filter: filters.status === "all" ? undefined : filters.status as TransactionStatus,
        type: filters.kind === "all" ? undefined : filters.kind as TransactionType,
        date_from: filters.from,
        date_to: filters.to,
        min_amount_paise: min ?? undefined,
        max_amount_paise: max ?? undefined,
        limit: DASHBOARD_PAGE_SIZE,
        offset: page * DASHBOARD_PAGE_SIZE,
      });
      if (!active) return;
      if (res.ok) {
        const currentPage = clampPaginationPage(page, res.data.total);
        if (currentPage !== page) {
          setPage(currentPage);
          return;
        }
        setData(res.data);
        setStatus("ready");
        return;
      }
      setError(res.error);
      setErrorStatus(res.status);
      setStatus("error");
    };
    const timer = window.setTimeout(() => void run(), 200);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [filters, max, maxRupees, min, minRupees, page, rangeError, reloadKey]);

  function resetPage() {
    setPage(0);
    setStatus("loading");
  }
  function clearAmounts() {
    setMinRupees("");
    setMaxRupees("");
    resetPage();
  }
  const DetailSheet = isAgent ? AgentTransactionSheet : TransactionDetailSheet;

  return (
    <DashboardPage>
      <DashboardHeader
        title="Transactions"
        description="Track cashback, referral bonuses, commissions, and any settlement reversals."
      />
      <FilterBar
        value={filters}
        onChange={(value) => { setFilters(value); resetPage(); }}
        searchLabel="Search transactions"
        searchPlaceholder="Transaction ID or description"
        showLine={false}
        statusLabel="Transaction status"
        kindLabel="Transaction type"
        statusOptions={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))}
        kindOptions={Object.entries(TRANSACTION_SOURCE).map(([value, label]) => ({ value, label }))}
        onClear={() => { setFilters(EMPTY_FILTERS); clearAmounts(); }}
        moreActiveCount={Number(Boolean(minRupees)) + Number(Boolean(maxRupees))}
        onClearMore={clearAmounts}
        chips={[
          ...(minRupees ? [{ id: "min", label: `Minimum ₹${minRupees}`, onRemove: () => { setMinRupees(""); resetPage(); } }] : []),
          ...(maxRupees ? [{ id: "max", label: `Maximum ₹${maxRupees}`, onRemove: () => { setMaxRupees(""); resetPage(); } }] : []),
        ]}
        more={[{
          title: "Amount in rupees",
          content: (
            <>
              <label className="space-y-1 text-sm">Minimum<Input inputMode="decimal" maxLength={14} value={minRupees} onChange={(event) => { setMinRupees(event.target.value); resetPage(); }} /></label>
              <label className="space-y-1 text-sm">Maximum<Input inputMode="decimal" maxLength={14} value={maxRupees} onChange={(event) => { setMaxRupees(event.target.value); resetPage(); }} /></label>
            </>
          ),
        }]}
      />

      {rangeError ? (
        <p role="alert" className="text-sm text-destructive">{rangeError}</p>
      ) : status === "loading" ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : status === "error" ? (
        <FetchError status={errorStatus} message={error} onRetry={retry} />
      ) : !data?.total ? (
        <div className="rounded-2xl border border-dashed border-border bg-card px-6 py-14 text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-text-secondary">
            <Wallet className="h-6 w-6" />
          </span>
          <h2 className="mt-5 text-lg font-semibold text-text-primary">{hasFilters ? "No transactions match these filters" : "No transactions yet"}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
            {hasFilters ? "Clear or adjust the filters to see more transactions." : "Your payouts will appear here once processed."}
          </p>
        </div>
      ) : (
        <>
          <MetricGrid>
            <MetricCard label="Net paid" value={formatPaise(data.paid_amount_paise)} icon={DASHBOARD_ICONS.earnings} />
            <MetricCard label="Transactions" value={data.total} icon={DASHBOARD_ICONS.transactions} />
            <MetricCard label="Processing" value={data.processing_count} icon={Wallet} attention={data.processing_count > 0} />
            <MetricCard label="Referral rewards" value={data.referral_count} icon={DASHBOARD_ICONS.referrals} />
          </MetricGrid>

          <DashboardPanel title="Transaction history" description={hasFilters ? "Totals reflect the current filters." : undefined}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-text-secondary">
                <tr>
                  <th className="px-5 py-3 font-medium">Detail</th>
                  <th className="hidden px-5 py-3 font-medium sm:table-cell">Date</th>
                  <th className="px-5 py-3 font-medium">Amount</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.transactions.map(mapTransaction).map((t) => {
                  // A clawback (post-settlement reversal, e.g. a bank-side
                  // reject days after payout) posts as a negative-amount row
                  // with the same "paid" status as a normal credit — flag it
                  // separately so it never reads as a fresh payout.
                  const isReversal = t.amountPaise < 0;
                  const Icon = isReversal ? Undo2 : TYPE_ICON[t.type];
                  return (
                    <tr key={t.id} className="border-b border-border last:border-0">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <span
                            className={cn(
                              "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                              isReversal
                                ? "bg-destructive/10 text-destructive"
                                : "bg-loans-soft text-brand-link",
                            )}
                          >
                            <Icon className="h-4 w-4" />
                          </span>
                          <button
                            type="button"
                            onClick={(event) => { detailTrigger.current = event.currentTarget; setOpenTransactionId(t.id); }}
                            className="min-h-11 text-left font-medium text-text-primary underline-offset-2 hover:text-brand-link hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                              {t.description}
                              <span className="sr-only">, view payment details</span>
                          </button>
                        </div>
                      </td>
                      <td className="hidden px-5 py-4 text-text-secondary sm:table-cell">
                        {formatDate(t.createdAt)}
                      </td>
                      <td
                        className={cn(
                          "px-5 py-4 font-medium",
                          isReversal ? "text-destructive" : "text-text-primary",
                        )}
                      >
                        {formatPaise(t.amountPaise)}
                      </td>
                      <td className="px-5 py-4">
                        <span
                          className={cn(
                            "inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium",
                            isReversal ? "bg-destructive/10 text-destructive" : STATUS_STYLE[t.status],
                          )}
                        >
                          {isReversal ? "Reversed" : STATUS_LABEL[t.status]}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ListPagination page={page} total={data.total} onPageChange={(value) => { setPage(value); setStatus("loading"); }} label="Transactions pages" />
          </DashboardPanel>
        </>
      )}
      <DetailSheet
          transactionId={openTransactionId}
          onCloseAutoFocus={(event) => { event.preventDefault(); detailTrigger.current?.focus(); }}
          onOpenChange={(open) => {
            if (!open) setOpenTransactionId(null);
          }}
      />
    </DashboardPage>
  );
}
