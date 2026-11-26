"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import type { components } from "@contracts/generated/schema";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DashboardHeader, DashboardPage } from "@/features/dashboard/dashboard-ui";
import { apiRequest } from "@/lib/api/client";
import { PROPERTY_SUBTYPE_GROUPS, propertySubtypeOption } from "@/lib/property-taxonomy";

type Schema = components["schemas"];
type CatalogType = Schema["PropertyCatalogTypeRead"];
const endpoint = "/api/v1/admin/property-types";

export function PropertyTypeEditor() {
  const [items, setItems] = useState<CatalogType[]>();
  const [label, setLabel] = useState("");
  const [subtype, setSubtype] = useState<Schema["PropertySubtype"] | "">("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void apiRequest<CatalogType[]>(endpoint).then((result) => {
      if (!active) return;
      if (result.ok) setItems(result.data);
      else setError(result.error);
    });
    return () => { active = false; };
  }, []);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!subtype) return;
    setBusy(true);
    setError("");
    setMessage("");
    const body: Schema["PropertyCatalogTypeWrite"] = { label: label.trim(), form_subtype: subtype };
    const result = await apiRequest<CatalogType>(endpoint, { method: "POST", body });
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setItems((previous) => [...(previous ?? []), result.data]);
    setLabel("");
    setSubtype("");
    setMessage("Property type added.");
  }

  async function update(item: CatalogType, label: string, active: boolean) {
    setBusy(true);
    setError("");
    setMessage("");
    const body: Schema["PropertyCatalogTypeUpdate"] = { label: label.trim(), active };
    const result = await apiRequest<CatalogType>(`${endpoint}/${item.code}`, { method: "PATCH", body });
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setItems((previous) => previous?.map((entry) => entry.code === item.code ? result.data : entry));
    setMessage(active ? "Property type saved." : "Property type retired.");
  }

  return (
    <DashboardPage>
      <DashboardHeader title="Property types" description="Choose an existing property form for each type. Retiring a type keeps existing listings and removes it from new submissions." />
      {error ? <p className="text-destructive" role="alert">{error}</p> : null}
      {message ? <p role="status">{message}</p> : null}
      {!items && !error ? <p role="status">Loading property types…</p> : null}
      {items ? <>
        <form onSubmit={(event) => void add(event)} className="grid items-end gap-4 rounded-xl border border-border p-4 sm:grid-cols-[1fr_1fr_auto]">
          <label className="space-y-2"><span className="text-sm font-medium">New property type</span>
            <Input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={40} required />
          </label>
          <label className="space-y-2"><span className="text-sm font-medium">Listing form</span>
            <select value={subtype} onChange={(event) => {
              setSubtype(propertySubtypeOption(event.target.value)?.value ?? "");
            }} required className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm">
              <option value="">Choose a form</option>
              {PROPERTY_SUBTYPE_GROUPS.map((group) => (
                <optgroup label={group.heading} key={group.heading}>
                  {group.items.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={busy}>Add type</Button>
        </form>
        <section className="space-y-4" aria-label="Existing property types">
          {items.map((item) => (
            <form key={item.code} className="flex flex-wrap items-end gap-3 rounded-xl border border-border p-4"
              onSubmit={(event) => {
                event.preventDefault();
                void update(item, String(new FormData(event.currentTarget).get("label")), item.active);
              }}>
              <label className="min-w-0 flex-1 space-y-2">
                <span className="block text-sm font-medium">{item.active ? "Active" : "Retired"} · {propertySubtypeOption(item.form_subtype)?.label}</span>
                <Input key={item.label} name="label" defaultValue={item.label} maxLength={40} required />
              </label>
              <Button disabled={busy} type="submit" variant="outline">Save name</Button>
              <Button disabled={busy} type="button" variant="outline" onClick={() => void update(item, item.label, !item.active)}>
                {item.active ? "Retire" : "Restore"}
              </Button>
              <Button asChild variant="ghost"><Link href={`/dashboard/website-content?key=property-type/${item.code.replaceAll("_", "-")}`}>Edit FAQs</Link></Button>
            </form>
          ))}
        </section>
      </> : null}
    </DashboardPage>
  );
}
