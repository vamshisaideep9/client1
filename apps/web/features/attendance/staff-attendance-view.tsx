"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  DashboardHeader, DashboardPage, DashboardPanel, DashboardTextLink,
} from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import { StatusBadge } from "@/features/dashboard/status-badge";
import {
  cancelAttendanceRequest, getMyAttendance, requestAttendanceAdjustment, requestAttendanceCorrection,
  requestAttendanceLeave, setAttendanceClock, type AttendanceAdjustment, type AttendanceLeave, type AttendanceMine,
} from "@/lib/attendance-api";
import { ADJUSTMENT_LABELS, ATTENDANCE_STATUS, attendanceCode, attendanceDate, attendanceTime, duration, istDay, leaveLabel, monthDays, previousMonth, requestLabel } from "./attendance-display";

type RequestKind = "leave" | "correction" | AttendanceAdjustment["adjustment_type"];

function useAttendance(month?: string) {
  const [payload, setPayload] = useState<AttendanceMine | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const refresh = useCallback(() => setRetry((value) => value + 1), []);
  useEffect(() => {
    let current = true;
    void getMyAttendance(month).then((response) => {
      if (!current) return;
      if (response.ok) {
        setPayload(response.data);
        setError(null);
      } else {
        setError({ status: response.status, message: response.error });
      }
    });
    return () => { current = false; };
  }, [month, retry]);
  return { payload, error, refresh };
}

function AttendanceClock({ payload, refresh }: { payload: AttendanceMine; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const row = payload.today;
  const running = row?.status === "checked_in";
  useEffect(() => {
    if (!running || !row.check_in) return;
    const serverMinutes = Math.max(0, (Date.parse(payload.server_time) - Date.parse(row.check_in)) / 60_000);
    const viewedAt = performance.now();
    const update = () => setElapsed(Math.floor(serverMinutes + (performance.now() - viewedAt) / 60_000));
    update();
    const timer = window.setInterval(update, 15_000);
    return () => window.clearInterval(timer);
  }, [payload.server_time, row, running]);
  async function punch() {
    setBusy(true);
    setMessage("");
    const response = await setAttendanceClock(!running);
    setBusy(false);
    if (response.ok) {
      setMessage(running ? "Checked out." : "Checked in.");
      refresh();
    } else {
      setMessage(response.error);
    }
  }

  if (!payload.policy) return <p className="text-sm text-text-secondary">Admin setup is pending. Attendance will open after the policy is configured.</p>;
  const clockAvailable = running || (!row?.check_in && row?.leave_units !== 2);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{attendanceDate(payload.work_day)}</span>
        {row ? <StatusBadge tone={running ? "info" : row.status === "present" ? "success" : "neutral"}>{ATTENDANCE_STATUS[row.status]}</StatusBadge> : null}
        {row?.late ? <StatusBadge tone="warning">Late</StatusBadge> : null}
      </div>
      <dl className="grid gap-2 text-sm sm:grid-cols-3">
        <div><dt className="text-text-secondary">Check-in (IST)</dt><dd>{attendanceTime(row?.check_in ?? null)}</dd></div>
        <div><dt className="text-text-secondary">{row?.system_check_out && !row.original_check_out && row.system_check_out === row.check_out ? "System logout (IST)" : "Check-out (IST)"}</dt><dd>{attendanceTime(row?.check_out ?? null)}</dd></div>
        <div><dt className="text-text-secondary">{running ? "Elapsed (estimate)" : "Worked"}</dt><dd>{duration(running ? elapsed : row?.worked_minutes ?? 0)}</dd></div>
      </dl>
      {clockAvailable ? <Button disabled={busy} onClick={() => void punch()}>{running ? "Check out" : "Check in"}</Button> : null}
      {message ? <p role="status" className="text-sm text-text-secondary">{message}</p> : null}
    </div>
  );
}

export function AttendanceTodayCard() {
  const { payload, error, refresh } = useAttendance();
  return (
    <DashboardPanel title="Attendance today" action={<DashboardTextLink href="/dashboard/attendance">View attendance</DashboardTextLink>}>
      {error ? <FetchError status={error.status} message={error.message} onRetry={refresh} />
        : payload ? <AttendanceClock payload={payload} refresh={refresh} />
          : <ListLoadingState rows={1} />}
    </DashboardPanel>
  );
}

export function StaffAttendanceView() {
  const [month, setMonth] = useState(previousMonth);
  const { payload, error, refresh } = useAttendance(month);
  const [request, setRequest] = useState<RequestKind | null>(null);
  const [message, setMessage] = useState("");
  const [cancelling, setCancelling] = useState<string | null>(null);
  const { confirm, confirmDialog } = useConfirm();
  const calendar = monthDays(month);
  const dates = new Map(payload?.days.map((day) => [day.day, day]));
  const holidayDates = new Map(payload?.holidays.map((holiday) => [holiday.day, holiday.name]));
  const firstWeekday = new Date(`${calendar[0]}T12:00:00Z`).getUTCDay();
  async function cancel(id: string) {
    if (cancelling || !await confirm({ title: "Cancel this request?", confirmLabel: "Cancel request" })) return;
    setCancelling(id);
    const response = await cancelAttendanceRequest(id);
    setCancelling(null);
    setMessage(response.ok ? "Request cancelled." : response.error);
    if (response.ok) refresh();
  }
  return (
    <DashboardPage>
      <DashboardHeader title="Attendance" description="Record your work day, check your hours and manage leave or corrections." />
      {error ? <FetchError status={error.status} message={error.message} onRetry={refresh} /> : !payload
        ? <ListLoadingState rows={3} />
        : <>
            <DashboardPanel title="Today"><AttendanceClock payload={payload} refresh={refresh} /></DashboardPanel>
            <DashboardPanel title="Monthly attendance" description="Work dates and recorded times use IST.">
              <div className="mb-4 w-full max-w-xs space-y-1.5">
                <Label htmlFor="attendance-month">Month</Label>
                <Input id="attendance-month" type="month" value={month} min="2000-01" max="9998-12"
                  onChange={(event) => { if (event.target.value) setMonth(event.target.value); }} />
              </div>
              <p className="mb-3 text-sm text-text-secondary">
                {duration(payload.days.reduce((total, day) => total + day.worked_minutes, 0))} worked ·{" "}
                {payload.days.filter((day) => day.late).length} late ·{" "}
                {payload.days.reduce((total, day) => total + day.leave_units, 0) / 2} leave days
                {payload.days.some((day) => day.lop_units != null)
                  ? ` · ${payload.days.reduce((total, day) => total + (day.lop_units ?? 0), 0) / 4} LOP days`
                  : ""}
              </p>
              <div className="grid grid-cols-7 gap-1 text-xs" role="group" aria-label="Attendance calendar">
                {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
                  <span key={day} className="text-center text-text-secondary">{day}</span>
                ))}
                {Array.from({ length: firstWeekday }, (_, index) => <span key={index} aria-hidden />)}
                {calendar.map((date) => {
                  const entry = dates.get(date);
                  const status = entry ? ATTENDANCE_STATUS[entry.status] : holidayDates.get(date) ?? "—";
                  const badge = entry ? attendanceCode(entry) : null;
                  const sunday = new Date(`${date}T12:00:00Z`).getUTCDay() === 0;
                  return <div key={date} className="min-w-0 rounded-lg border border-border p-1 text-center sm:p-2">
                    <time dateTime={date} className="block font-medium">{Number(date.slice(-2))}</time>
                    {sunday && badge?.code !== "SUN" ? <span className="mr-1 rounded bg-slate-200 px-1 font-medium text-slate-900">SUN</span> : null}
                    {badge ? <span className={`rounded px-1 font-medium ${badge.tone}`}>{badge.code}</span> : null}
                    <span className="block text-text-secondary [overflow-wrap:anywhere]">{status}</span>
                  </div>;
                })}
              </div>
              {payload.days.length ? (
                <ul aria-label="Daily attendance history" className="mt-4 divide-y divide-border">
                  {payload.days.map((day) => (
                    <li key={day.day} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                      <span>{attendanceDate(day.day)} · {ATTENDANCE_STATUS[day.status]}{day.lop_units ? ` · ${day.lop_units / 4} day LOP` : ""}</span>
                      <span className="text-text-secondary">{attendanceTime(day.check_in)} – {attendanceTime(day.check_out)} · {duration(day.worked_minutes)}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-3 text-sm text-text-secondary">No attendance recorded this month.</p>}
            </DashboardPanel>
            <DashboardPanel title="Leave and corrections">
              {payload.policy ? (
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => setRequest("leave")} disabled={!Object.keys(payload.policy.leave_quotas).length}>Request leave</Button>
                  <Button variant="outline" onClick={() => setRequest("correction")}>Request correction</Button>
                  {payload.policy.session_clock ? <Button variant="outline" onClick={() => setRequest("late_waiver")}>Request regularization</Button> : null}
                </div>
              ) : <p className="text-sm text-text-secondary">Leave and corrections open after Admin setup.</p>}
              {payload.balances.length ? (
                <ul className="mt-4 space-y-1 text-sm" aria-label={`Leave balance for ${payload.balance_year}`}>
                  {payload.balances.map((balance) => <li key={balance.leave_type}>
                    {leaveLabel(balance.leave_type)} · {Math.max(0, balance.allocated_units - balance.used_units) / 2} days left of {balance.allocated_units / 2} ({payload.balance_year})
                  </li>)}
                </ul>
              ) : null}
              {message ? <p role="status" className="mt-3 text-sm">{message}</p> : null}
              {payload.requests.length ? (
                <ul className="mt-4 divide-y divide-border">
                  {payload.requests.map((row) => (
                    <li key={row.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
                      <div className="min-w-0">
                        <p className="font-medium">{requestLabel(row)} · {attendanceDate(row.start_day)}{row.end_day !== row.start_day ? ` – ${attendanceDate(row.end_day)}` : ""}</p>
                        <p className="text-text-secondary [overflow-wrap:anywhere]">{leaveLabel(row.status)} · Submitted {attendanceDate(istDay(new Date(row.created_at)))} at {attendanceTime(row.created_at)}{row.decisions.at(-1)?.note ? ` · ${row.decisions.at(-1)?.note}` : ""}</p>
                      </div>
                      {row.status === "pending" || (!row.two_stage && row.status === "approved" && row.kind === "leave" && row.start_day > istDay(new Date(payload.server_time))) ? (
                        <Button variant="outline" size="sm" disabled={cancelling !== null} onClick={() => void cancel(row.id)}>Cancel request</Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-3 text-sm text-text-secondary">No requests for this month.</p>}
            </DashboardPanel>
            {request ? <AttendanceRequestDialog kind={request} payload={payload} close={() => setRequest(null)} saved={(day) => { setMonth(day.slice(0, 7)); setMessage("Request submitted."); refresh(); }} /> : null}
          </>}
      {confirmDialog}
    </DashboardPage>
  );
}

function AttendanceRequestDialog({ kind, payload, close, saved }: {
  kind: RequestKind;
  payload: AttendanceMine;
  close: () => void;
  saved: (day: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const leave = kind === "leave";
  const adjustment = kind !== "leave" && kind !== "correction";
  const [adjustmentType, setAdjustmentType] = useState<AttendanceAdjustment["adjustment_type"]>(
    adjustment ? kind : "late_waiver",
  );
  const today = istDay(new Date(payload.server_time));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? "");
    const reason = field("reason").trim();
    const leaveSession = field("leave_session") as NonNullable<AttendanceLeave["leave_session"]> | "";
    if (reason.length < 3) { setError("Enter a reason of at least three characters."); return; }
    setBusy(true);
    setError("");
    const response = leave ? await requestAttendanceLeave({
      start_day: field("start"), end_day: field("end"), half_day: form.has("half") || Boolean(leaveSession),
      leave_type: field("type"), reason, leave_session: leaveSession || null,
    }) : adjustment ? await requestAttendanceAdjustment({
      day: field("day"), adjustment_type: adjustmentType, reason,
    }) : await requestAttendanceCorrection({
      day: field("day"), check_in: `${field("check_in")}:00+05:30`,
      check_out: `${field("check_out")}:00+05:30`, reason,
    });
    setBusy(false);
    if (!response.ok) { setError(response.error); return; }
    saved(response.data.start_day);
    close();
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}>
      <DialogContent preventOutsideClose className="max-h-[92dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>{leave ? "Request leave" : adjustment ? "Request regularization" : "Request an attendance correction"}</DialogTitle>
          <DialogDescription>{leave ? "Choose the days and leave type to send for review." : adjustment ? "Select the recorded work date and the exception you want reviewed." : "Enter the original work date and the correct times in IST."}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          {leave ? <>
            <div><Label htmlFor="leave-type">Leave type</Label>
              <select id="leave-type" name="type" required className="mt-1 w-full rounded-md border border-input bg-background p-2">
                {Object.keys(payload.policy?.leave_quotas ?? {}).map((type) => <option key={type} value={type}>{leaveLabel(type)}</option>)}
              </select></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label htmlFor="leave-start">First day</Label><Input id="leave-start" name="start" type="date" required min={today} defaultValue={today} /></div>
              <div><Label htmlFor="leave-end">Last day</Label><Input id="leave-end" name="end" type="date" required min={today} defaultValue={today} /></div>
            </div>
            {payload.policy?.session_clock ? (
              <div><Label htmlFor="leave-session">Leave duration</Label>
                <select id="leave-session" name="leave_session" className="min-h-10 w-full rounded-md border border-input bg-background p-2">
                  <option value="">Full day</option>
                  <option value="morning">Morning half day</option>
                  <option value="afternoon">Afternoon half day</option>
                </select></div>
            ) : <div className="flex items-center gap-2"><input id="leave-half" name="half" type="checkbox" /><Label htmlFor="leave-half">Half day on one date</Label></div>}
          </> : adjustment ? <>
            <div><Label htmlFor="regularization-type">Exception</Label>
              <select id="regularization-type" className="min-h-10 w-full rounded-md border border-input bg-background p-2"
                value={adjustmentType} onChange={(event) => setAdjustmentType(event.target.value as AttendanceAdjustment["adjustment_type"])}>
                {Object.entries(ADJUSTMENT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select></div>
            <div><Label htmlFor="regularization-day">Work date</Label><Input id="regularization-day" name="day" type="date" required max={adjustmentType === "on_duty" ? undefined : today} defaultValue={payload.work_day} /></div>
          </> : <>
            <div><Label htmlFor="correction-day">Work date</Label><Input id="correction-day" name="day" type="date" required max={today} defaultValue={payload.work_day} /></div>
            <div><Label htmlFor="correction-in">Correct check-in (IST)</Label><Input id="correction-in" name="check_in" type="datetime-local" required /></div>
            <div><Label htmlFor="correction-out">Correct check-out (IST)</Label><Input id="correction-out" name="check_out" type="datetime-local" required /></div>
          </>}
          <div><Label htmlFor="attendance-reason">Reason</Label><Textarea id="attendance-reason" name="reason" maxLength={500} required /></div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <DialogFooter>
            <Button variant="outline" disabled={busy} type="button" onClick={close}>Cancel</Button>
            <Button disabled={busy} type="submit">{busy ? "Submitting…" : "Submit request"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
