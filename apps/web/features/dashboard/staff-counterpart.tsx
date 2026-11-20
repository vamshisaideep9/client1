import * as React from "react";

export function StaffCounterpart({ label, name, code, fallback = "Not available" }: {
  label: string; name?: string | null; code?: string | null; fallback?: string;
}) {
  return <span className="block min-w-0 break-words text-xs leading-5 text-text-secondary">
    {label}: <span className="font-medium text-text-primary">{name || (code ? "" : fallback)}</span>
    {code && <span className="break-all font-mono">{` ${code}`}</span>}
  </span>;
}
