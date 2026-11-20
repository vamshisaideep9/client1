"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listAdminLoanTypes, type AdminLoanType } from "@/lib/loan-config-api";

export function LoanSpecialtySelect({ id, value, onChange, disabled, currentLabel }: {
  id: string; value: string; onChange: (value: string) => void; disabled?: boolean; currentLabel?: string | null;
}) {
  const [products, setProducts] = React.useState<AdminLoanType[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let active = true;
    void listAdminLoanTypes().then((response) => {
      if (!active) return;
      setLoading(false);
      if (response.ok) { setProducts(response.data.filter((product) => product.active && product.category === "loan")); setError(null); }
      else setError(response.error);
    });
    return () => { active = false; };
  }, [retry]);
  const missing = !!value && !products.some((product) => product.id === value);
  return <div className="space-y-2">
    <Label htmlFor={id}>Loan specialty (optional)</Label>
    <Select value={value || "none"} onValueChange={(next) => onChange(next === "none" ? "" : next)} disabled={disabled || loading}>
      <SelectTrigger id={id} aria-describedby={`${id}-help`}><SelectValue placeholder="No specialty" /></SelectTrigger>
      <SelectContent>
        <SelectItem value="none">No specialty</SelectItem>
        {missing && <SelectItem value={value} disabled>{currentLabel ?? "Current specialty"}{loading ? "" : " (unavailable)"}</SelectItem>}
        {products.map((product) => <SelectItem key={product.id} value={product.id}>{product.label}</SelectItem>)}
      </SelectContent>
    </Select>
    <p id={`${id}-help`} aria-live="polite" className="text-xs leading-5 text-text-secondary">{loading ? "Loading loan products…" : !error && products.length === 0 ? "No active loan products are available. You can leave this blank." : "New matching leads go to specialists first. Existing assignments stay with their Telecaller."}</p>
    {error && <div role="alert" className="space-y-2 text-sm text-error"><p>Could not load loan products. {error}</p><Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => { setLoading(true); setRetry((key) => key + 1); }}>Retry loan products</Button></div>}
  </div>;
}
