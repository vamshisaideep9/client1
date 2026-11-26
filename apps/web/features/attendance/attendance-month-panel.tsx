"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import { changeAttendanceMonth, exportAttendanceMonth, getAttendanceMonth, type AttendanceMonth } from "@/lib/attendance-api";
import { attendanceDate, duration, istDay, previousMonth } from "./attendance-display";

const selectClass = "min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function AttendanceMonthPanel({ manageable = false }: { manageable?: boolean }) {
  const [month, setMonth] = useState(previousMonth);
  const [version, setVersion] = useState("");
  const [report, setReport] = useState<AttendanceMonth | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [action, setAction] = useState<"close" | "reopen" | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [revision, retry] = useState(0);
  const [exporting, setExporting] = useState(false);
  const actionButton = useRef<HTMLButtonElement>(null);
  const monthDay = month + "-01";

  useEffect(() => {
    let current = true;
    void getAttendanceMonth(monthDay).then((result) => {
      if (!current) return;
      if (!result.ok) { setError({ status: result.status, message: result.error }); return; }
      setReport(result.data);
      setError(null);
    });
    return () => { current = false; };
  }, [monthDay, revision]);

  const latest = report?.revisions[0];
  const closed = Boolean(latest && latest.reopened_at === null);
  const saved = report?.revisions.find((entry) => String(entry.version) === version);
  const rows = saved?.totals ?? report?.totals ?? [];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!action || !report) return;
    const note = String(new FormData(event.currentTarget).get("note") ?? "").trim();
    if (note.length < 3) { setActionError("Enter a reason of at least three characters."); return; }
    setBusy(true);
    setActionError("");
    const result = await changeAttendanceMonth(monthDay, action, { expected_version: latest?.version ?? 0, note });
    setBusy(false);
    if (!result.ok) { setActionError(result.error); return; }
    setReport(result.data);
    setVersion("");
    setAction(null);
    setNotice(action === "close" ? "Attendance month closed." : "Attendance month reopened.");
  }

  async function download() {
    setExporting(true);
    setNotice("");
    try {
      const result = await exportAttendanceMonth(monthDay, saved?.version);
      setNotice(result.ok ? "Attendance report downloaded." : result.error);
    } catch {
      setNotice("The download was interrupted. Try again.");
    } finally {
      setExporting(false);
    }
  }

  return <DashboardPanel title="Monthly attendance report" description="Review work, leave, and loss of pay by business line.">
    <div className="grid gap-3 sm:grid-cols-2 lg:max-w-2xl">
      <div><Label htmlFor="month-report-period">Attendance month (IST)</Label>
        <Input id="month-report-period" type="month" min="2000-01" max={istDay().slice(0, 7)} value={month} disabled={busy || exporting} onChange={(event) => {
          if (!event.target.value || event.target.value === month) return;
          setReport(null); setVersion(""); setNotice(""); setError(null); setMonth(event.target.value);
        }} /></div>
      {report?.revisions.length ? <div><Label htmlFor="month-report-revision">Report version</Label>
        <select id="month-report-revision" className={selectClass} value={version} onChange={(event) => { setVersion(event.target.value); setNotice(""); }}>
          <option value="">{closed ? "Current closed report" : "Live preview"}</option>
          {report.revisions.map((entry) => <option key={entry.version} value={entry.version}>Revision {entry.version} · {attendanceDate(istDay(new Date(entry.closed_at)))}</option>)}
        </select></div> : null}
    </div>
    {error ? <FetchError {...error} onRetry={() => { setError(null); retry((value) => value + 1); }} /> : !report ? <ListLoadingState rows={2} /> : <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={saved || closed ? "success" : "neutral"}>{saved ? "Closed revision " + saved.version : closed ? "Closed" : "Live preview"}</StatusBadge>
        {saved?.reopened_at ? <span className="text-sm text-text-secondary">Reopened {attendanceDate(istDay(new Date(saved.reopened_at)))}</span> : null}
      </div>
      {rows.length ? <div className="overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={0} role="region" aria-label="Monthly totals by business line">
        <table className="w-full min-w-max text-left text-sm">
          <thead className="bg-muted text-text-secondary"><tr>
            {["Business line", "Recorded days", "Worked", "Leave days", "Sandwich days", "LOP days", "Late days", "Absences"].map((label) => <th scope="col" className="p-2" key={label}>{label}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-border">{rows.map((row) => <tr key={row.business_line ?? "unassigned"}>
            <th scope="row" className="p-2 font-medium">{row.business_line === "loans" ? "Loans" : row.business_line === "real_estate" ? "Real estate" : "Unassigned"}</th>
            <td className="p-2">{row.recorded_days}</td><td className="p-2">{duration(row.worked_minutes)}</td>
            <td className="p-2">{row.leave_units / 2}</td><td className="p-2">{(row.sandwich_units ?? 0) / 2}</td><td className="p-2">{row.lop_units / 4}</td>
            <td className="p-2">{row.late_days}</td><td className="p-2">{row.absences}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p className="text-sm text-text-secondary">No attendance was recorded for this month.</p>}
      {manageable && !saved && report.close_blocker ? <p className="text-sm text-text-secondary">{report.close_blocker}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={exporting || !rows.length} onClick={() => void download()}>{exporting ? "Exporting…" : "Export monthly CSV"}</Button>
        {manageable && !saved && (closed || report.can_close) ? <Button ref={actionButton} type="button" onClick={() => { setActionError(""); setAction(closed ? "reopen" : "close"); }}>
          {closed ? "Reopen month" : "Close month"}
        </Button> : null}
      </div>
      {notice ? <p role="status" className="text-sm text-text-secondary">{notice}</p> : null}
    </div>}
    <Dialog open={action !== null} onOpenChange={(open) => { if (!open && !busy) setAction(null); }}>
      <DialogContent preventOutsideClose className="max-h-[92dvh] overflow-auto" onCloseAutoFocus={(event) => { event.preventDefault(); actionButton.current?.focus(); }}>
        <DialogHeader><DialogTitle>{action === "close" ? "Close attendance month" : "Reopen attendance month"}</DialogTitle>
          <DialogDescription>{action === "close" ? "Save a new revision and lock changes to these work dates." : "Allow changes to these work dates and keep the saved revision."}</DialogDescription></DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="space-y-3">
          <div><Label htmlFor="month-report-note">Reason</Label><Textarea id="month-report-note" name="note" required maxLength={500} /></div>
          {actionError ? <p role="alert" className="text-sm text-destructive">{actionError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setAction(null)}>Cancel</Button>
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : action === "close" ? "Close month" : "Reopen month"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </DashboardPanel>;
}
