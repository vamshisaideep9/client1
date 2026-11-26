"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listAdminLoanTypes, type AdminLoanType } from "@/lib/loan-config-api";

type ProductCategory = AdminLoanType["category"];

/** Catalogue order and the group headings in the specialty picker. */
export const SPECIALTY_CATEGORIES: { value: ProductCategory; label: string }[] = [
  { value: "loan", label: "Loans" },
  { value: "credit_card", label: "Credit cards" },
  { value: "insurance", label: "Insurance" },
];

/** Active products of every category, grouped in catalogue order (empty groups dropped). */
export function specialtyGroups(products: readonly AdminLoanType[]) {
  return SPECIALTY_CATEGORIES.map((category) => ({
    ...category,
    products: products.filter((product) => product.active && product.category === category.value),
  })).filter((group) => group.products.length > 0);
}

/**
 * One optional product specialty for a Loans or dual-line Telecaller or
 * Officer: any active loan, credit card or insurance product. The API and the
 * database re-check the role, line and product.
 */
export function ProductSpecialtySelect({ id, value, onChange, disabled, currentLabel }: {
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
      if (response.ok) { setProducts(response.data.filter((product) => product.active)); setError(null); }
      else setError(response.error);
    });
    return () => { active = false; };
  }, [retry]);
  const groups = specialtyGroups(products);
  const missing = !!value && !products.some((product) => product.id === value);
  return <div className="space-y-2">
    <Label htmlFor={id}>Product specialty (optional)</Label>
    <Select value={value || "none"} onValueChange={(next) => onChange(next === "none" ? "" : next)} disabled={disabled || loading}>
      <SelectTrigger id={id} aria-describedby={`${id}-help`}><SelectValue placeholder="No specialty" /></SelectTrigger>
      <SelectContent>
        <SelectItem value="none">No specialty</SelectItem>
        {missing && <SelectItem value={value} disabled>{currentLabel ?? "Current specialty"}{loading ? "" : " (unavailable)"}</SelectItem>}
        {groups.map((group) => <SelectGroup key={group.value}>
          <SelectLabel>{group.label}</SelectLabel>
          {group.products.map((product) => <SelectItem key={product.id} value={product.id}>{product.label}</SelectItem>)}
        </SelectGroup>)}
      </SelectContent>
    </Select>
    <p id={`${id}-help`} aria-live="polite" className="text-xs leading-5 text-text-secondary">{loading ? "Loading products…" : !error && products.length === 0 ? "No active products are available. You can leave this blank." : "New work for this product goes to its specialists first. Existing work stays where it is."}</p>
    {error && <div role="alert" className="space-y-2 text-sm text-error"><p>Could not load products. {error}</p><Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => { setLoading(true); setRetry((key) => key + 1); }}>Retry products</Button></div>}
  </div>;
}
