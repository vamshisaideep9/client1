"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/session-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { PendingDecisionDialog } from "@/features/admin/pending-review-dialog";
import { commissionRateLabel, parseCommissionRate } from "@/lib/commission-rate";
import {
  approveCommissionRate, listCommissionRates, rejectCommissionRate, setCommissionRate, withdrawCommissionRate,
  type CommissionRate, type ProductCommissionRates,
} from "@/lib/commission-rates-api";

function RateSummary({ rate }: { rate: CommissionRate | null }) {
  if (!rate) return <p className="text-sm text-text-secondary">No approved rate yet.</p>;
  return <div className="space-y-1 text-sm">
    <p className="font-semibold">{commissionRateLabel(rate)}</p>
    {rate.note ? <p className="whitespace-pre-wrap break-words text-text-secondary">{rate.note}</p> : null}
    <p className="text-xs text-text-secondary">Entered by {rate.created_by_name ?? "staff"}{rate.checker_name ? ` · Approved by ${rate.checker_name}` : ""}</p>
  </div>;
}

function RateForm({ product, admin, onClose, onSaved }: {
  product: ProductCommissionRates; admin: boolean; onClose: () => void; onSaved: () => void;
}) {
  const source = product.pending?.is_mine ? product.pending : product.current;
  const [kind, setKind] = React.useState<"percent" | "fixed">(source?.kind ?? "percent");
  const [value, setValue] = React.useState(() => source ? String((source.kind === "percent" ? source.percent_bps ?? 0 : source.amount_paise ?? 0) / 100) : "");
  const [note, setNote] = React.useState(source?.note ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    const body = parseCommissionRate(kind, value, note);
    if (!body) { setError(kind === "percent" ? "Enter a percentage from 0.01 to 100, with at most two decimals." : "Enter an amount from ₹0.01 to ₹10 crore, with at most two decimals."); return; }
    setBusy(true); setError(null);
    const response = await setCommissionRate(product.loan_type_id, body);
    setBusy(false);
    if (!response.ok) setError(response.error);
    else { onSaved(); onClose(); }
  }
  return <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
    <DialogContent preventOutsideClose>
      <DialogHeader><DialogTitle>{admin ? "Set agent commission" : "Propose agent commission"}</DialogTitle>
        <DialogDescription>{product.product_label}. {admin ? "This entry applies immediately." : "A different Admin must approve your proposal."}</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={(event) => void save(event)} noValidate>
        <div className="grid gap-2"><Label htmlFor="rate-kind">Commission type</Label>
          <Select value={kind} onValueChange={(next) => { setKind(next as "percent" | "fixed"); setValue(""); setError(null); }}>
            <SelectTrigger id="rate-kind"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="percent">Percentage</SelectItem><SelectItem value="fixed">Fixed amount</SelectItem></SelectContent>
          </Select>
        </div>
        <div className="grid gap-2"><Label htmlFor="rate-value">{kind === "percent" ? "Percent of disbursed amount (%)" : "Fixed commission (₹)"}</Label>
          <Input id="rate-value" inputMode="decimal" value={value} onChange={(event) => { setValue(event.target.value); setError(null); }} maxLength={16} autoFocus
            aria-invalid={!!error} aria-describedby={error ? "rate-error" : undefined} />
        </div>
        <div className="grid gap-2"><Label htmlFor="rate-note">Note for agents (optional)</Label>
          <Textarea id="rate-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={280} rows={3} />
        </div>
        {error ? <p id="rate-error" role="alert" className="text-sm text-destructive">{error}</p> : null}
        <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : admin ? "Set commission" : "Submit for approval"}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}

export function CommissionRatesView({ productId, embedded = false }: { productId?: string; embedded?: boolean }) {
  const { session } = useAuth();
  const admin = session?.role === "admin";
  const [products, setProducts] = React.useState<ProductCommissionRates[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<ProductCommissionRates | null>(null);
  const [reviewing, setReviewing] = React.useState<ProductCommissionRates | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [onlyPending, setOnlyPending] = React.useState(false);
  const request = React.useRef(0);
  const reload = React.useCallback(async () => {
    const current = ++request.current;
    const response = await listCommissionRates();
    if (current !== request.current) return;
    setLoading(false);
    if (response.ok) { setProducts(response.data.products); setError(null); }
    else setError(response.error);
  }, []);
  React.useEffect(() => { void reload(); }, [reload]);
  async function withdraw(product: ProductCommissionRates) {
    if (!product.pending || busy) return;
    setBusy(product.loan_type_id);
    const response = await withdrawCommissionRate(product.pending.id);
    setBusy(null);
    if (!response.ok) setError(response.error);
    else void reload();
  }
  const shown = products.filter((product) => (!productId || product.loan_type_id === productId) && (!onlyPending || product.pending));
  const content = <>
    {!embedded ? <DashboardHeader title="Agent commission rates" description="Approved loan-product rates for agents. Proposals need a different Admin's approval." /> : null}
    {!embedded ? <Button variant={onlyPending ? "default" : "outline"} onClick={() => setOnlyPending((value) => !value)}>
      {onlyPending ? "Show all products" : `Awaiting approval (${products.filter((product) => product.pending).length})`}
    </Button> : null}
    {error ? <FetchError status={null} message={error} onRetry={() => void reload()} /> : null}
    {loading ? <ListLoadingState rows={4} /> : shown.length === 0 ? <p className="p-4 text-sm text-text-secondary">No matching loan products.</p> : shown.map((product) => (
      <DashboardPanel key={product.loan_type_id} title={product.product_label} description={product.product_active ? "Agent commission" : "Inactive product · rates are hidden from agents"}
        action={<Button variant="outline" size="sm" disabled={!!busy || (!admin && !!product.pending && !product.pending.is_mine)}
          onClick={() => setEditing(product)}>{admin ? "Set rate" : product.pending?.is_mine ? "Replace proposal" : "Propose rate"}</Button>}>
        <RateSummary rate={product.current} />
        {product.pending ? <div className="mt-4 space-y-3 rounded-xl border border-border bg-surface p-4">
          <StatusBadge tone="warning">Awaiting approval</StatusBadge>
          <RateSummary rate={product.pending} />
          {admin && !product.pending.is_mine ? <Button size="sm" onClick={() => setReviewing(product)}>Review proposal</Button> : null}
          {!admin && product.pending.is_mine ? <Button variant="outline" size="sm" disabled={!!busy} onClick={() => void withdraw(product)}>Withdraw proposal</Button> : null}
          {admin && product.pending.is_mine ? <p className="text-sm">Another Admin must review your proposal.</p> : null}
        </div> : null}
        {product.history.length ? <details className="mt-4 text-sm"><summary className="cursor-pointer font-medium">Earlier rates ({product.history.length})</summary>
          <ul className="mt-3 space-y-3">{product.history.map((rate) => <li key={rate.id} className="border-t border-border pt-3">
            <p className="mb-1 capitalize text-text-secondary">{rate.status.replaceAll("_", " ")}</p>
            <RateSummary rate={rate} />{rate.review_note ? <p className="mt-1">Review: {rate.review_note}</p> : null}
          </li>)}</ul></details> : null}
      </DashboardPanel>
    ))}
    {editing ? <RateForm product={editing} admin={admin} onClose={() => setEditing(null)} onSaved={() => void reload()} /> : null}
    {reviewing?.pending ? <PendingDecisionDialog title={`Review commission · ${reviewing.product_label}`}
      description="Approval replaces the current rate. Rejection needs feedback for the maker."
      onClose={() => setReviewing(null)}
      onApprove={async () => {
        const response = await approveCommissionRate(reviewing.pending!.id);
        if (response.ok) { setReviewing(null); void reload(); return null; }
        return response.error;
      }}
      onReject={async (note) => {
        const response = await rejectCommissionRate(reviewing.pending!.id, note);
        if (response.ok) { setReviewing(null); void reload(); return null; }
        return response.error;
      }}>
      <RateSummary rate={reviewing.pending} />
    </PendingDecisionDialog> : null}
  </>;
  return embedded ? <div className="space-y-4">{content}</div> : <DashboardPage>{content}</DashboardPage>;
}
