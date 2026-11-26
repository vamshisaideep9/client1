import Link from "next/link";

import type { components } from "@contracts/generated/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const modes = [{ value: "", label: "All properties" }, { value: "sale", label: "For sale" },
  { value: "resale", label: "Resale" }, { value: "rent", label: "Rent / Lease" }];
const rangeFields = [
  ["budget_min", "Minimum budget", 0], ["budget_max", "Maximum budget", 0],
  ["area_min", "Minimum area (sq ft)", 1], ["area_max", "Maximum area (sq ft)", 1],
] as const;
const fields = [
  "mode", "location", "property_type", "bhk",
  ...rangeFields.map(([key]) => key), "page",
] as const;
const selectClass = "h-11 w-full rounded-md border border-input bg-background px-3 text-sm";

export function propertySearchParams(raw: Record<string, string | string[] | undefined>) {
  const params = new URLSearchParams();
  for (const field of fields) {
    const entry = raw[field];
    const value = (Array.isArray(entry) ? entry[0] : entry)?.trim();
    if (value) params.set(field, value);
  }
  return params;
}

function searchHref(params: URLSearchParams, edit: (next: URLSearchParams) => void) {
  const next = new URLSearchParams(params);
  edit(next);
  return `/real-estate${next.size ? `?${next}` : ""}#property-results`;
}

export function PublicPropertySearch({ params, types }: {
  params: URLSearchParams;
  types: components["schemas"]["PropertyCatalogTypeRead"][];
}) {
  const mode = params.get("mode") ?? "";
  const propertyType = params.get("property_type") ?? "";
  return (
    <section aria-labelledby="property-search-heading" className="mx-auto w-full max-w-7xl space-y-4 px-4 sm:px-6 lg:px-8">
      <h2 id="property-search-heading" className="font-heading text-2xl font-semibold">Find a property</h2>
      <nav aria-label="Property listing purpose" className="flex flex-wrap gap-2">
        {modes.map(({ value, label }) => (
          <Button key={value} asChild variant={mode === value ? "default" : "outline"}>
            <Link aria-current={mode === value ? "page" : undefined} href={searchHref(params, (next) => {
              next.delete("page");
              next.delete("budget_min");
              next.delete("budget_max");
              if (value) next.set("mode", value);
              else next.delete("mode");
            })}>{label}</Link>
          </Button>
        ))}
      </nav>
      <form action="/real-estate#property-results" method="get" className="grid gap-4 rounded-xl border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
        {mode ? <input type="hidden" name="mode" value={mode} /> : null}
        <label className="space-y-1.5"><span className="block text-sm font-medium">Locality or city</span>
          <Input name="location" defaultValue={params.get("location") ?? ""} maxLength={120} placeholder="Search by location" />
        </label>
        <label className="space-y-1.5"><span className="block text-sm font-medium">Property type</span>
          <select name="property_type" className={selectClass} defaultValue={propertyType}>
            <option value="">All types</option>
            {propertyType && !types.some(({ code }) => code === propertyType) ? <option value={propertyType}>Selected type</option> : null}
            {types.map(({ code, label }) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        <label className="space-y-1.5"><span className="block text-sm font-medium">Bedrooms</span>
          <select name="bhk" className={selectClass} defaultValue={params.get("bhk") ?? ""}>
            <option value="">Any BHK</option>
            {["1", "2", "2.5", "3", "3.5", "4", "5+"].map((bhk) => <option key={bhk} value={bhk}>{bhk} BHK</option>)}
          </select>
        </label>
        {rangeFields.filter(([field]) => mode || !field.startsWith("budget")).map(([field, label, min]) => (
          <label key={field} className="space-y-1.5">
            <span className="block text-sm font-medium">{label}{field.startsWith("budget") ? mode === "rent" ? " (₹ per month)" : " (₹ total)" : ""}</span>
            <Input name={field} type="number" min={min} defaultValue={params.get(field) ?? ""} />
          </label>
        ))}
        {!mode ? <p className="self-end text-sm text-text-secondary">Choose sale, resale, or rent / lease to filter by budget.</p> : null}
        <div className="flex flex-wrap items-end gap-2">
          <Button type="submit">Search properties</Button>
          {params.size ? <Button asChild variant="ghost"><Link href="/real-estate#property-results">Clear</Link></Button> : null}
        </div>
      </form>
    </section>
  );
}

export function PropertySearchPagination({ params, page, total, pageSize }: {
  params: URLSearchParams; page: number; total: number; pageSize: number;
}) {
  if (total <= pageSize && page === 1) return null;
  const pageHref = (number: number) => searchHref(params, (next) => {
    if (number > 1) next.set("page", String(number));
    else next.delete("page");
  });
  return (
    <nav aria-label="Property results pages" className="mx-auto flex w-fit flex-wrap items-center gap-3 px-4">
      {page > 1 ? <Button asChild variant="outline"><Link href={pageHref(page - 1)}>Previous</Link></Button> : null}
      <p className="text-sm text-text-secondary">Page {page} of {Math.max(1, Math.ceil(total / pageSize))}</p>
      {page * pageSize < total ? <Button asChild variant="outline"><Link href={pageHref(page + 1)}>Next</Link></Button> : null}
    </nav>
  );
}
