"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth/session-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DashboardHeader, DashboardPage, DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import {
  decideAttendanceRequest, exportAttendance, getAttendanceInbox, getAttendanceRoster,
  type AttendanceDecision, type AttendanceInbox, type AttendanceRequest, type AttendanceRoster,
} from "@/lib/attendance-api";
import { getMyTeams, listTeams } from "@/lib/staff-teams-api";
import { ATTENDANCE_STATUS, attendanceDate, attendanceTime, duration, istDay, leaveLabel, monthDays } from "./attendance-display";
import { AttendancePolicyPanel } from "./attendance-policy-panel";

type Mode = "daily" | "month" | "requests" | "policy";
type FilterOption = { id: string; name: string };
const PAGE_SIZE = 50;
const selectClass = "min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function AttendanceManagementView() {
  const { session } = useAuth();
  const role = session?.role;
  const admin = role === "admin";
  const [mode, setMode] = useState<Mode>("daily");
  const [date, setDate] = useState(() => istDay());
  const [month, setMonth] = useState(() => istDay().slice(0, 7));
  const [team, setTeam] = useState("");
  const [staff, setStaff] = useState("");
  const [status, setStatus] = useState("");
  const [requestStatus, setRequestStatus] = useState("pending");
  const [offset, setOffset] = useState(0);
  const [teams, setTeams] = useState<FilterOption[]>([]);
  const [roster, setRoster] = useState<AttendanceRoster | null>(null);
  const [inbox, setInbox] = useState<AttendanceInbox | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [teamsFailed, setTeamsFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const [review, setReview] = useState<AttendanceRequest | null>(null);
  const [revision, refresh] = useState(0);
  const dates = useMemo(() => mode === "month" ? monthDays(month) : [date], [mode, date, month]);
  const range = useMemo(() => {
    const query = new URLSearchParams({ start: dates[0], end: dates[dates.length - 1] });
    if (team) query.set("team_id", team);
    if (staff) query.set("staff_id", staff);
    if (status && mode !== "requests") query.set("status", status);
    return query;
  }, [dates, mode, staff, status, team]);

  useEffect(() => {
    if (!role) return;
    let current = true;
    const fetchTeams = admin ? listTeams() : getMyTeams();
    void fetchTeams.then((res) => {
      if (!current) return;
      setTeamsFailed(!res.ok);
      if (res.ok) setTeams(res.data.teams.map((entry) => ({ id: entry.id, name: entry.name })));
    });
    return () => { current = false; };
  }, [admin, revision, role]);

  useEffect(() => {
    if (!role || mode === "policy") return;
    let current = true;
    const query = new URLSearchParams(range);
    if (mode !== "requests") query.set("offset", String(offset));
    const requests = new URLSearchParams({ status: requestStatus, offset: String(offset) });
    if (team) requests.set("team_id", team);
    if (staff) requests.set("staff_id", staff);
    void Promise.all([
      getAttendanceRoster(query),
      mode === "requests" ? getAttendanceInbox(requests) : null,
    ]).then(([result, queued]) => {
      if (!current) return;
      if (!result.ok || (queued && !queued.ok)) {
        const failure = !result.ok ? result : queued;
        if (failure && !failure.ok) setError({ status: failure.status, message: failure.error });
        return;
      }
      setRoster(result.data);
      setInbox(queued?.ok ? queued.data : null);
      setError(null);
    });
    return () => { current = false; };
  }, [mode, offset, range, requestStatus, revision, role, staff, team]);

  const updateMode = (value: string) => {
    setMode(value as Mode);
    setOffset(0);
    setError(null);
    setInbox(null);
  };
  const members = new Map(roster?.members.map((member) => [member.staff_profile_id, member]));
  const total = mode === "requests" ? inbox?.total ?? 0 : roster?.total ?? 0;
  async function download() {
    setExporting(true);
    const result = await exportAttendance(range);
    setExporting(false);
    setNotice(result.ok ? (result.truncated ? "Export downloaded. It includes the first 500 staff records." : "Attendance export downloaded.") : result.error);
  }

  return (
    <DashboardPage>
      <DashboardHeader title="Staff attendance" description="Review work dates, leave requests and attendance corrections." />
      <Tabs value={mode} onValueChange={updateMode}>
        <TabsList className="h-auto flex-wrap justify-start" aria-label="Attendance views">
          <TabsTrigger value="daily">Daily roster</TabsTrigger>
          <TabsTrigger value="month">Monthly grid</TabsTrigger>
          <TabsTrigger value="requests">Requests</TabsTrigger>
          {admin ? <TabsTrigger value="policy">Policy & holidays</TabsTrigger> : null}
        </TabsList>
        <TabsContent value={mode} className="space-y-4">
      {mode === "policy" && admin ? <AttendancePolicyPanel /> : (
        <>
          <DashboardPanel title="Filters" action={admin && mode !== "requests" && roster?.configured ? (
            <Button variant="outline" disabled={exporting} onClick={() => void download()}>Export CSV</Button>
          ) : null}>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {mode === "month" ? <div><Label htmlFor="roster-month">Month</Label>
                <Input id="roster-month" type="month" value={month} min="2000-01" max="9998-12" onChange={(event) => {
                  if (event.target.value) { setMonth(event.target.value); setOffset(0); }
                }} /></div> : mode === "daily" ? <div><Label htmlFor="roster-day">Work date</Label>
                <Input id="roster-day" type="date" value={date} onChange={(event) => {
                  if (event.target.value) { setDate(event.target.value); setOffset(0); }
                }} /></div> : null}
              <div><Label htmlFor="roster-team">Team</Label>
                <select id="roster-team" className={selectClass} value={team} onChange={(event) => {
                  setTeam(event.target.value); setStaff(""); setOffset(0);
                }}>
                  <option value="">{admin ? "All teams and unassigned" : "My teams"}</option>
                  {teams.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
                </select>
              </div>
              <div><Label htmlFor="roster-staff">Staff member</Label>
                <select id="roster-staff" className={selectClass} value={staff} onChange={(event) => {
                  setStaff(event.target.value); setOffset(0);
                }}>
                  <option value="">All staff in scope</option>
                  {roster?.members.map((member) => <option key={member.staff_profile_id} value={member.staff_profile_id}>{member.name} ({member.staff_code})</option>)}
                </select>
              </div>
              <div><Label htmlFor="roster-status">{mode === "requests" ? "Request status" : "Attendance status"}</Label>
                {mode === "requests" ? (
                  <select id="roster-status" className={selectClass} value={requestStatus} onChange={(event) => {
                    setRequestStatus(event.target.value); setOffset(0);
                  }}>
                    {["pending", "approved", "rejected", "cancelled"].map((value) => <option key={value} value={value}>{leaveLabel(value)}</option>)}
                  </select>
                ) : <select id="roster-status" className={selectClass} value={status} onChange={(event) => {
                  setStatus(event.target.value); setOffset(0);
                }}>
                  <option value="">All statuses</option>
                  {Object.entries(ATTENDANCE_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>}
              </div>
            </div>
            {teamsFailed ? <p role="status" className="mt-2 text-sm text-text-secondary">Team choices could not load. <Button variant="link" onClick={() => refresh((value) => value + 1)}>Retry</Button></p> : null}
            {notice ? <p role="status" className="mt-2 text-sm text-text-secondary">{notice}</p> : null}
          </DashboardPanel>
          <DashboardPanel title={mode === "requests" ? "Review requests" : mode === "month" ? "Monthly attendance" : "Daily attendance"}>
            {error ? <FetchError status={error.status} message={error.message} onRetry={() => refresh((value) => value + 1)} />
              : !roster || (mode === "requests" && !inbox) ? <ListLoadingState rows={3} />
              : !roster.configured ? <p className="text-sm text-text-secondary">Admin setup is pending. Attendance will appear after the policy is configured.</p>
              : mode === "requests" && inbox ? (
                inbox.requests.length ? <ul className="divide-y divide-border">
                  {inbox.requests.map((entry) => (
                    <li key={entry.id} className="flex flex-wrap justify-between gap-3 py-3 text-sm">
                      <div className="min-w-0">
                        <p className="font-medium">{entry.kind === "leave" ? leaveLabel(entry.leave_type ?? "leave") : "Correction"} · {members.get(entry.staff_profile_id)?.name ?? "Staff member"}</p>
                        <p className="text-text-secondary">{attendanceDate(entry.start_day)}{entry.end_day !== entry.start_day ? ` – ${attendanceDate(entry.end_day)}` : ""} · {leaveLabel(entry.status)}</p>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => setReview(entry)}>{entry.status === "pending" ? "Review" : "Open request"}</Button>
                    </li>
                  ))}
                </ul> : <p className="text-sm text-text-secondary">No requests match these filters.</p>
              ) : <RosterTable roster={roster} dates={dates} daily={mode === "daily"} />}
            {total > PAGE_SIZE ? (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset((value) => value - PAGE_SIZE)}>Previous</Button>
                <span className="text-sm text-text-secondary">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
                <Button variant="outline" size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset((value) => value + PAGE_SIZE)}>Next</Button>
              </div>
            ) : null}
          </DashboardPanel>
        </>
      )}
        </TabsContent>
      </Tabs>
      {review ? <ReviewDialog entry={review} name={members.get(review.staff_profile_id)?.name}
        admin={admin} close={() => setReview(null)} saved={() => { setNotice("Attendance decision saved."); refresh((value) => value + 1); }} /> : null}
    </DashboardPage>
  );
}

function RosterTable({ roster, dates, daily }: { roster: AttendanceRoster; dates: string[]; daily: boolean }) {
  if (!roster.members.length) return <p className="text-sm text-text-secondary">No staff members match these filters.</p>;
  const byDay = new Map(roster.days.map((row) => [`${row.staff_profile_id}/${row.day}`, row]));
  return (
    <div className="overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={0} role="region" aria-label={daily ? "Daily roster table" : "Monthly attendance grid"}>
      <table className="w-full min-w-max text-left text-sm">
        <thead className="bg-muted text-text-secondary">
          <tr><th scope="col" className="p-2">Staff member</th>
            {daily ? ["Status", "Check-in (IST)", "Check-out (IST)", "Worked"].map((label) => <th scope="col" className="p-2" key={label}>{label}</th>)
              : dates.map((day) => <th scope="col" className="p-2" key={day}>{Number(day.slice(-2))}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {roster.members.map((member) => {
            const row = byDay.get(`${member.staff_profile_id}/${dates[0]}`);
            return <tr key={member.staff_profile_id}>
              <th scope="row" className="p-2 font-medium">{member.name}<span className="block text-xs text-text-secondary">{member.staff_code}</span></th>
              {daily ? <>
                <td className="p-2">{row ? ATTENDANCE_STATUS[row.status] : "Unrecorded"}{row?.late ? " · Late" : ""}</td>
                <td className="p-2">{attendanceTime(row?.check_in ?? null)}</td>
                <td className="p-2">{attendanceTime(row?.check_out ?? null)}</td>
                <td className="p-2">{row ? duration(row.worked_minutes) : "—"}</td>
              </> : dates.map((day) => {
                const entry = byDay.get(`${member.staff_profile_id}/${day}`);
                return <td key={day} className="p-2 text-xs">{entry ? ATTENDANCE_STATUS[entry.status] : "—"}{entry?.late ? " · Late" : ""}</td>;
              })}
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

function ReviewDialog({ entry, name, admin, close, saved }: {
  entry: AttendanceRequest; name?: string; admin: boolean; close: () => void; saved: () => void;
}) {
  const canDecide = admin || entry.status === "pending";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const status = values.get("status") as AttendanceDecision["status"];
    const note = String(values.get("note") ?? "").trim();
    if (note.length < 3) { setError("Enter a review note of at least three characters."); return; }
    setBusy(true);
    setError("");
    const response = await decideAttendanceRequest(entry.id, {
      note, status, expected_decisions: entry.decisions.length,
    });
    setBusy(false);
    if (!response.ok) { setError(response.error); return; }
    saved();
    close();
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}>
      <DialogContent preventOutsideClose className="max-h-[92dvh] overflow-y-auto">
        <DialogHeader><DialogTitle>{entry.kind === "leave" ? "Leave request" : "Correction request"}</DialogTitle>
          <DialogDescription>{name ?? "Staff member"} · {leaveLabel(entry.status)}</DialogDescription></DialogHeader>
        <div className="space-y-2 text-sm">
          <p>{attendanceDate(entry.start_day)}{entry.end_day !== entry.start_day ? ` – ${attendanceDate(entry.end_day)}` : ""}</p>
          {entry.kind === "leave" ? <p>{leaveLabel(entry.leave_type ?? "leave")}{entry.half_day ? " · Half day" : ""}</p>
            : <p>{attendanceTime(entry.requested_check_in)} – {attendanceTime(entry.requested_check_out)} IST</p>}
          <p className="[overflow-wrap:anywhere]">{entry.reason}</p>
          {entry.decisions.length ? <ol className="list-decimal space-y-1 pl-5" aria-label="Decision history">
            {entry.decisions.map((decision, index) => <li key={index} className="[overflow-wrap:anywhere]">
              {leaveLabel(decision.status)} · {leaveLabel(decision.actor_role)} · {attendanceDate(istDay(new Date(decision.at)))} · {decision.note}
            </li>)}
          </ol> : null}
        </div>
        {canDecide ? <form onSubmit={(event) => void submit(event)} className="space-y-3">
          <div><Label htmlFor="review-decision">Decision</Label>
            <select id="review-decision" name="status" className={selectClass} required defaultValue="">
              <option value="" disabled>Select decision</option>
              {entry.status !== "approved" ? <option value="approved">Approve</option> : null}
              {entry.status !== "rejected" && entry.status !== "cancelled" ? <option value="rejected">Reject</option> : null}
              {admin && entry.status !== "cancelled" ? <option value="cancelled">Cancel request</option> : null}
            </select></div>
          <div><Label htmlFor="review-note">Review note</Label><Textarea id="review-note" name="note" required maxLength={500} /></div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <DialogFooter><Button variant="outline" type="button" onClick={close} disabled={busy}>Close</Button>
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save decision"}</Button></DialogFooter>
        </form> : <DialogFooter><Button variant="outline" onClick={close}>Close</Button></DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}
