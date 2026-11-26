"use client";

import * as React from "react";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { setStaffLoanSpecialty } from "@/lib/admin-users-api";
import type { ProductStaffPerson, ProductStaffingRow } from "@/lib/product-dashboards-api";

import {
  ROLE_LABEL,
  addSpecialistHref,
  assignableFor,
  personLabel,
  type SpecialistRole,
} from "./product-coverage";

/**
 * Gives an unspecialised Loans or dual-line Telecaller or Officer this product
 * as their specialty, through the existing Admin specialty endpoint. Work they
 * already hold stays where it is; only new work routes by the specialty.
 */
export function AssignSpecialistDialog({
  product,
  available,
  onOpenChange,
  onAssigned,
}: {
  product: ProductStaffingRow | null;
  available: readonly ProductStaffPerson[];
  onOpenChange: (open: boolean) => void;
  onAssigned: () => void;
}) {
  const [role, setRole] = React.useState<SpecialistRole>("telecaller");
  const [personId, setPersonId] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const people = assignableFor(available, role);
  const person = people.find((candidate) => candidate.auth_user_uuid === personId) ?? null;

  React.useEffect(() => {
    if (!product) return;
    setRole(product.telecallers?.some((item) => item.status === "active") ? "employee" : "telecaller");
    setPersonId("");
    setError(null);
  }, [product]);

  async function assign() {
    if (!product || !person) return;
    setSaving(true);
    setError(null);
    const response = await setStaffLoanSpecialty(person.auth_user_uuid, { loan_specialty_id: product.product_id });
    setSaving(false);
    if (!response.ok) {
      setError(response.error);
      return;
    }
    toast.success(`${person.first_name} ${person.last_name} now specialises in ${product.label}`);
    onAssigned();
    onOpenChange(false);
  }

  return (
    <Dialog open={product !== null} onOpenChange={(open) => !saving && onOpenChange(open)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Assign a specialist</DialogTitle>
          <DialogDescription>
            {product ? `New ${product.label} work goes to its specialists first. Work they already hold stays where it is.` : null}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="assign-specialist-role">Role</Label>
            <Select value={role} onValueChange={(next) => { setRole(next as SpecialistRole); setPersonId(""); }} disabled={saving}>
              <SelectTrigger id="assign-specialist-role"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="telecaller">{ROLE_LABEL.telecaller}</SelectItem>
                <SelectItem value="employee">{ROLE_LABEL.employee}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {people.length === 0 ? (
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-text-secondary">
              No unspecialised Loans {ROLE_LABEL[role]}s are available.{" "}
              {product ? (
                <Link href={addSpecialistHref(role, product.product_id)} className="font-medium text-brand-link underline-offset-4 hover:underline">
                  Create a {ROLE_LABEL[role]} instead
                </Link>
              ) : null}
            </p>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="assign-specialist-person">{ROLE_LABEL[role]}</Label>
              <Select value={personId} onValueChange={setPersonId} disabled={saving}>
                <SelectTrigger id="assign-specialist-person"><SelectValue placeholder={`Choose a ${ROLE_LABEL[role]}`} /></SelectTrigger>
                <SelectContent>
                  {people.map((candidate) => (
                    <SelectItem key={candidate.auth_user_uuid} value={candidate.auth_user_uuid}>
                      {personLabel(candidate)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-text-secondary">Only active Loans or dual-line staff without a specialty are listed.</p>
            </div>
          )}
          {error ? <p role="alert" className="text-sm text-error">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button type="button" onClick={() => void assign()} disabled={saving || !person}>
            {saving ? "Assigning…" : "Assign specialist"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
