"use client";

import * as React from "react";
import { IndianRupee } from "lucide-react";

import { LeadRefText } from "@/features/dashboard/lead-ref";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { DASHBOARD_PAGE_SIZE, ListPagination, clampPaginationPage } from "@/features/dashboard/list-pagination";
import { ListEmptyState, ListLoadingState } from "@/features/dashboard/list-states";
import {
  createBulkCommissionPayout,
  listPendingCommissionGroups,
  listPendingGroupCommissions,
  type CommissionPayoutGroup,
  type CommissionRead,
} from "@/lib/admin-commissions-api";
import { buildCommissionPayoutPayload } from "@/lib/commission-payout-form";
import { formatDate, formatPaise } from "@/lib/format";
import { MoneyPayoutDialog } from "./money-payout-dialog";

const PAGE_SIZE = DASHBOARD_PAGE_SIZE;
const SELECTION_LIMIT = 200;

function lineLabel(line: string) {
  return line === "loans" ? "Loans" : "Real Estate";
}

function commissionLabel(row: CommissionRead) {
  return row.deal_type === "loan_application" ? "Loan commission" : "Property commission";
}

export function CommissionPayoutGroups({ onCreated, revision }: { onCreated: () => void; revision: number }) {
  const [group, setGroup] = React.useState<CommissionPayoutGroup | null>(null);
  const [groupPage, setGroupPage] = React.useState(0);
  const [itemPage, setItemPage] = React.useState(0);
  const [attempt, setAttempt] = React.useState(0);
  const [groups, setGroups] = React.useState<Awaited<ReturnType<typeof listPendingCommissionGroups>> | null>(null);
  const [items, setItems] = React.useState<Awaited<ReturnType<typeof listPendingGroupCommissions>> | null>(null);
  const [selected, setSelected] = React.useState<CommissionRead[]>([]);
  const [payoutRows, setPayoutRows] = React.useState<CommissionRead[]>([]);
  const [staleSelection, setStaleSelection] = React.useState(false);

  React.useEffect(() => {
    if (group) return;
    let active = true;
    setGroups(null);
    void listPendingCommissionGroups(PAGE_SIZE, groupPage * PAGE_SIZE).then((result) => {
      if (!active) return;
      if (result.ok) {
        const validPage = clampPaginationPage(groupPage, result.data.total);
        if (validPage !== groupPage) {
          setGroupPage(validPage);
          return;
        }
      }
      setGroups(result);
    });
    return () => { active = false; };
  }, [group, groupPage, revision, attempt]);

  React.useEffect(() => {
    if (!group) return;
    let active = true;
    setItems(null);
    void listPendingGroupCommissions(group, PAGE_SIZE, itemPage * PAGE_SIZE).then((result) => {
      if (!active) return;
      if (result.ok) {
        const validPage = clampPaginationPage(itemPage, result.data.total);
        if (validPage !== itemPage) {
          setItemPage(validPage);
          return;
        }
      }
      setItems(result);
    });
    return () => { active = false; };
  }, [group, itemPage, revision, attempt]);

  function leaveGroup() {
    setGroup(null);
    setItems(null);
    setSelected([]);
  }

  function changeSelection(row: CommissionRead, checked: boolean) {
    setSelected((previous) => checked ? [...previous, row] : previous.filter((item) => item.id !== row.id));
  }

  function closePayout() {
    setPayoutRows([]);
    if (staleSelection) {
      setSelected([]);
      setAttempt((value) => value + 1);
      setStaleSelection(false);
    }
  }

  const totalSelected = selected.reduce((sum, row) => sum + row.agreed_amount_paise, 0);
  const payoutTotal = payoutRows.reduce((sum, row) => sum + row.agreed_amount_paise, 0);
  const current = group ? items : groups;
  const groupName = group ? group.agent_name ?? group.agent_code : "";

  return (
    <DashboardPanel title="Pending commission payouts" description="Select commissions for one Agent and business line." bodyClassName="space-y-3">
      {group ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold">{groupName} · {lineLabel(group.business_line)}</h3>
          <Button variant="outline" onClick={leaveGroup}>Back to Agents</Button>
        </div>
      ) : null}

      {!current ? <ListLoadingState rows={3} /> : !current.ok ? (
        <FetchError status={current.status} message={current.error} onRetry={() => setAttempt((value) => value + 1)} />
      ) : group && items?.ok ? (
        <>
          {items.data.commissions.length ? (
            <ul aria-label="Pending commissions for this Agent" className="divide-y divide-border">
              {items.data.commissions.map((row) => {
                const checked = selected.some((item) => item.id === row.id);
                const label = `${commissionLabel(row)} · ${formatDate(row.created_at)} · ${formatPaise(row.agreed_amount_paise)}`;
                return (
                  <li key={row.id}>
                    <label className="flex min-h-12 items-center gap-3 py-2">
                      <Checkbox
                        aria-label={`${label} · ${row.deal_uuid}`}
                        checked={checked}
                        disabled={!checked && selected.length >= SELECTION_LIMIT}
                        onCheckedChange={(value) => changeSelection(row, value === true)}
                      />
                      <span className="min-w-0 flex-1 text-sm">
                        {commissionLabel(row)}
                        {row.lead_ref ? (
                          <span className="block"><LeadRefText value={row.lead_ref} /></span>
                        ) : null}
                        <span className="block break-all text-xs text-text-secondary">{formatDate(row.created_at)} · Deal {row.deal_uuid}</span>
                      </span>
                      <span className="shrink-0 text-sm font-semibold tabular-nums">{formatPaise(row.agreed_amount_paise)}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-sm text-text-secondary">No payable commissions remain in this group.</p>}
          {items.data.total > 0 ? <ListPagination page={itemPage} total={items.data.total} onPageChange={setItemPage} label="Pending commission pages" /> : null}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <p className="text-sm tabular-nums" aria-live="polite">{selected.length} selected · {formatPaise(totalSelected)}</p>
            <div className="flex flex-wrap gap-2">
              {selected.length ? <Button variant="ghost" onClick={() => setSelected([])}>Clear selection</Button> : null}
              <Button disabled={!selected.length} onClick={() => setPayoutRows(selected)}>Review payout</Button>
            </div>
            {selected.length === SELECTION_LIMIT ? <p className="w-full text-xs text-text-secondary">A payout can cover up to {SELECTION_LIMIT} commissions.</p> : null}
          </div>
        </>
      ) : groups?.ok && groups.data.groups.length ? (
        <>
          <ul className="divide-y divide-border">
            {groups.data.groups.map((row) => (
              <li key={`${row.agent_profile_uuid}:${row.business_line}`} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="break-words text-sm font-semibold">{row.agent_name ?? row.agent_code}</p>
                  <p className="text-xs text-text-secondary">{row.agent_code} · {lineLabel(row.business_line)}</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <div>
                    <p className="text-sm font-semibold tabular-nums">{formatPaise(row.pending_amount_paise)}</p>
                    <p className="text-xs text-text-secondary">{row.pending_count} pending</p>
                  </div>
                  <Button variant="outline" onClick={() => { setItems(null); setItemPage(0); setGroup(row); }}>
                    Select commissions<span className="sr-only"> for {row.agent_name ?? row.agent_code}</span>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
          <ListPagination page={groupPage} total={groups.data.total} onPageChange={setGroupPage} label="Agent payout pages" />
        </>
      ) : (
        <ListEmptyState icon={IndianRupee} title="No pending payouts" description="Unlinked pending commissions will appear here." />
      )}

      <MoneyPayoutDialog
        open={payoutRows.length > 0}
        onOpenChange={(open) => { if (!open) closePayout(); }}
        title={`Review payout · ${formatPaise(payoutTotal)}`}
        description={`${payoutRows.length} selected · ${groupName}`}
        idPrefix="group-commission-payout"
        lockedCopy="The selected commissions determine the recipient and amount. Choose the payment destination."
        submitLabel="Raise payout"
        conflictTitle="One or more commissions are no longer payable"
        successDescription="Check the payout ledger for approval or settlement status."
        savedDestinationTarget={group ? { agentProfileUuid: group.agent_profile_uuid } : null}
        summary={(
          <details className="rounded-lg border border-border p-3 text-sm">
            <summary className="cursor-pointer font-medium">Covered commissions</summary>
            <ul className="mt-2 max-h-40 divide-y divide-border overflow-y-auto">
              {payoutRows.map((row) => (
                <li key={row.id} className="flex flex-wrap justify-between gap-x-3 py-2">
                  <span>{commissionLabel(row)} · {formatDate(row.created_at)}</span>
                  <span className="tabular-nums">{formatPaise(row.agreed_amount_paise)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        onSubmit={async (form) => {
          const result = await createBulkCommissionPayout({
            ...buildCommissionPayoutPayload(form),
            commission_ids: payoutRows.map((row) => row.id),
          });
          if (result.ok) {
            leaveGroup();
            onCreated();
          } else if (result.status === 409) {
            setStaleSelection(true);
          }
          return result;
        }}
      />
    </DashboardPanel>
  );
}
