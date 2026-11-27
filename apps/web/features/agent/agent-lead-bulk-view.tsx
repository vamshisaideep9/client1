"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/session-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DashboardBackLink, DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { AgentBulkProductsPanel } from "@/features/agent/agent-bulk-products-panel";
import { submitAgentLeadRows, type AgentLeadBulkRow, type AgentLeadBulkResult } from "@/lib/agent-api";
import { LEAD_SHEET_HEADERS, downloadLeadSheet, leadSheetCsv, leadSheetTemplate, readLeadSheet } from "@/lib/agent-lead-sheet";

type ResultRow = AgentLeadBulkResult["rows"][number];
const OUTCOMES: Record<ResultRow["outcome"], string> = {
  ready: "Ready", created: "Introduced", already_introduced: "Already yours",
  duplicate: "Duplicate", not_eligible: "Not eligible", duplicate_in_file: "Repeated in file",
  invalid: "Needs correction", unavailable: "Temporarily unavailable",
};
function details(row: ResultRow) {
  return (row.errors ?? []).map((error) => `${error.field}: ${error.message}`).join("; ") || row.reason_label || "";
}

export function AgentLeadBulkView() {
  const { session } = useAuth();
  const [rows, setRows] = React.useState<AgentLeadBulkRow[]>([]);
  const [results, setResults] = React.useState<ResultRow[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [submitted, setSubmitted] = React.useState(false);
  const ready = results.filter((row) => row.outcome === "ready");

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(null); setRows([]); setResults([]); setSubmitted(false);
    try {
      const parsed = await readLeadSheet(file);
      const response = await submitAgentLeadRows(parsed, true);
      if (!response.ok) throw new Error(response.error);
      setRows(parsed); setResults(response.data.rows);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not read the file. Use the template and try again.");
    } finally { setBusy(false); }
  }
  async function submit() {
    if (busy || !ready.length || submitted) return;
    setBusy(true); setError(null);
    const response = await submitAgentLeadRows(ready.map((row) => rows[row.row_index]), false);
    if (!response.ok) setError(response.error);
    else {
      const updates = new Map(response.data.rows.map((row) => [ready[row.row_index].row_index, row]));
      setResults((current) => current.map((row) => {
        const update = updates.get(row.row_index);
        return update ? { ...update, row_index: row.row_index } : row;
      }));
      setSubmitted(true);
    }
    setBusy(false);
  }
  function downloadResults() {
    const body = results.map((result) => {
      const row = rows[result.row_index];
      return [row.sno, row.name, row.mobile, row.email, row.requirement, row.description, OUTCOMES[result.outcome], details(result)];
    });
    downloadLeadSheet(leadSheetCsv([[...LEAD_SHEET_HEADERS, "Outcome", "Details"], ...body]), "dhanadhara-lead-results.csv", "text/csv;charset=utf-8");
  }
  async function templateXlsx() {
    setBusy(true); setError(null);
    try { downloadLeadSheet(await leadSheetTemplate(), "dhanadhara-lead-template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); }
    catch { setError("Could not create the Excel template. Download the CSV template instead."); }
    finally { setBusy(false); }
  }
  return (
    <DashboardPage>
      <DashboardBackLink href="/dashboard/leads">Back to leads</DashboardBackLink>
      <DashboardHeader title="Bulk upload leads" description="Preview up to 200 leads before introducing them." />
      <DashboardPanel title="1. Prepare your file" description="Use the template headers. Files are read in your browser; only the lead rows are sent.">
        <p className="mb-3 text-sm text-text-secondary">Requirement: {session?.businessLine === "real_estate" ? "a property type, such as Villa or Plot." : "the name or code of an active product listed below."} Email, requirement and description are optional. Use plain values, without formulas.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => downloadLeadSheet(leadSheetCsv([LEAD_SHEET_HEADERS]), "dhanadhara-lead-template.csv", "text/csv;charset=utf-8")}>Download CSV template</Button>
          <Button variant="outline" disabled={busy} onClick={() => void templateXlsx()}>Download Excel template</Button>
        </div>
        <div className="mt-5 grid max-w-lg gap-2">
          <Label htmlFor="lead-sheet">Choose CSV or Excel file (up to 5 MB)</Label>
          <Input id="lead-sheet" type="file" accept=".csv,.xlsx" disabled={busy}
            onChange={(event) => { void chooseFile(event.target.files?.[0]); event.target.value = ""; }} />
        </div>
      </DashboardPanel>
      <AgentBulkProductsPanel />
      {error ? <p role="alert" className="rounded-xl border border-destructive p-4 text-sm text-destructive">{error}</p> : null}
      {busy ? <p role="status" className="text-sm">Processing your rows…</p> : null}
      {results.length ? (
        <DashboardPanel title={submitted ? "Upload results" : "2. Review your rows"}
          description={submitted ? "Each row has its own result. Download the results before leaving this page." : `${ready.length} of ${rows.length} rows ready. Rows with errors will not be submitted.`}>
          <div className="mb-4 flex flex-wrap gap-2">
            {!submitted ? <Button disabled={busy || !ready.length} onClick={() => void submit()}>Submit {ready.length} valid {ready.length === 1 ? "row" : "rows"}</Button> : null}
            <Button variant="outline" disabled={busy} onClick={downloadResults}>Download results</Button>
          </div>
          <ul aria-label="Lead upload rows" className="grid gap-3 sm:hidden">
            {results.map((result) => {
              const row = rows[result.row_index];
              return <li key={result.row_index} className="min-w-0 space-y-1 rounded-xl border border-border p-3 text-sm">
                <p className="break-words font-medium">{row.sno ?? result.row_index + 1}. {row.name || "Missing name"}</p>
                <p className="break-all text-text-secondary">{row.mobile}{row.email ? ` · ${row.email}` : ""}</p>
                {result.requirement_label || row.requirement ? <p className="break-words text-text-secondary">{result.requirement_label ?? row.requirement}</p> : null}
                <p className="font-medium">{OUTCOMES[result.outcome]}</p>
                {details(result) ? <p className="break-words text-xs text-text-secondary">{details(result)}</p> : null}
              </li>;
            })}
          </ul>
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Lead upload preview and row outcomes</caption>
              <thead><tr>
                <th scope="col" className="border-b p-3">Row</th>
                <th scope="col" className="border-b p-3">Name</th>
                <th scope="col" className="hidden border-b p-3 sm:table-cell">Mobile</th>
                <th scope="col" className="hidden border-b p-3 md:table-cell">Requirement</th>
                <th scope="col" className="border-b p-3">Result</th>
              </tr></thead>
              <tbody>{results.map((result) => (
                <tr key={result.row_index} className="border-b last:border-0">
                  <td className="p-3">{rows[result.row_index].sno ?? result.row_index + 1}</td>
                  <td className="p-3"><span className="break-words">{rows[result.row_index].name || "Missing name"}</span>
                    <p className="text-xs text-text-secondary sm:hidden">{rows[result.row_index].mobile}</p>
                    <p className="max-w-60 break-all text-xs text-text-secondary">{rows[result.row_index].email}</p></td>
                  <td className="hidden whitespace-nowrap p-3 sm:table-cell">{rows[result.row_index].mobile}</td>
                  <td className="hidden p-3 md:table-cell">{result.requirement_label ?? rows[result.row_index].requirement}</td>
                  <td className="min-w-40 p-3 sm:min-w-48"><span className="font-medium">{OUTCOMES[result.outcome]}</span><p className="mt-1 text-xs text-text-secondary">{details(result)}</p></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </DashboardPanel>
      ) : null}
    </DashboardPage>
  );
}
