"use client";

import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { setStaffLoanSpecialty } from "@/lib/admin-users-api";
import type { RoleProfile } from "@/features/dashboard/role-badge";
import { LoanSpecialtySelect } from "./loan-specialty-select";

export function StaffSpecialtyEditor({ userId, profile, onSaved }: {
  userId: string; profile: RoleProfile; onSaved: (profiles: RoleProfile[]) => void;
}) {
  const [value, setValue] = React.useState(profile.loan_specialty_id ?? "");
  const [saved, setSaved] = React.useState(profile.loan_specialty_id ?? "");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  async function save() {
    setSaving(true); setError(null);
    const response = await setStaffLoanSpecialty(userId, { loan_specialty_id: value || null });
    setSaving(false);
    if (!response.ok) { setError(response.error); return; }
    const stored = response.data.find((item) => item.profile_uuid === profile.profile_uuid)?.loan_specialty_id ?? "";
    setValue(stored);
    setSaved(stored);
    onSaved(response.data);
    toast.success("Loan specialty saved");
  }
  return <section className="space-y-4 rounded-xl border border-border bg-card p-5" aria-label="Telecaller routing">
    <h2 className="font-semibold text-text-primary">Telecaller routing</h2>
    <LoanSpecialtySelect id="account-loan-specialty" value={value} onChange={setValue}
      currentLabel={profile.loan_specialty_label} disabled={saving} />
    {error && <p role="alert" className="text-sm text-error">{error}</p>}
    <Button type="button" onClick={() => void save()} disabled={saving || value === saved}>
      {saving ? "Saving specialty…" : "Save specialty"}
    </Button>
  </section>;
}
