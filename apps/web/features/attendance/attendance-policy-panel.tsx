"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DashboardPanel } from "@/features/dashboard/dashboard-ui";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import {
  getAttendanceHolidays, getAttendancePolicy, saveAttendancePolicy, setAttendanceHoliday,
  type AttendanceHoliday, type AttendancePolicyState,
} from "@/lib/attendance-api";
import { attendanceDate, istDay, monthDays } from "./attendance-display";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const NUMBERS = [
  ["shift_minutes", "Shift duration (minutes)", 1],
  ["grace_minutes", "Grace period (minutes)", 0],
  ["half_day_minutes", "Half-day minimum (minutes)", 1],
  ["full_day_minutes", "Full-day minimum (minutes)", 1],
] as const;

function asTime(minutes: number) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function parseQuotas(text: string) {
  const quotas: Record<string, number> = {};
  for (const line of text.split("\n").map((value) => value.trim()).filter(Boolean)) {
    const match = /^([a-z][a-z0-9_]{0,31})\s*=\s*(\d+(?:\.5|\.0)?)$/.exec(line);
    if (!match || Number(match[2]) > 366 || Object.hasOwn(quotas, match[1])) return null;
    quotas[match[1]] = Number(match[2]) * 2;
  }
  return Object.keys(quotas).length <= 12 ? quotas : null;
}

export function AttendancePolicyPanel() {
  const [policy, setPolicy] = useState<AttendancePolicyState | null>(null);
  const [holidays, setHolidays] = useState<AttendanceHoliday[]>([]);
  const [month, setMonth] = useState(() => istDay().slice(0, 7));
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  const [message, setMessage] = useState("");
  const [holidayMessage, setHolidayMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [holidayBusy, setHolidayBusy] = useState(false);
  const [revision, refresh] = useState(0);
  const { confirm, confirmDialog } = useConfirm();
  const today = istDay();

  useEffect(() => {
    let current = true;
    const days = monthDays(month);
    void Promise.all([getAttendancePolicy(), getAttendanceHolidays(days[0], days[days.length - 1])])
      .then(([state, calendar]) => {
        if (!current) return;
        if (!state.ok || !calendar.ok) {
          const failure = !state.ok ? state : calendar;
          if (!failure.ok) setError({ status: failure.status, message: failure.error });
          return;
        }
        setPolicy(state.data);
        setHolidays(calendar.data);
        setError(null);
      });
    return () => { current = false; };
  }, [month, revision]);

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const [hours, minutes] = String(form.get("start")).split(":").map(Number);
    const sessionClock = form.has("session_clock");
    const quotas = parseQuotas(String(form.get("quotas") ?? ""));
    if (!quotas) {
      setMessage("Enter each leave type once, in the format annual=12.5. Use up to 12 types.");
      return;
    }
    setBusy(true);
    setMessage("");
    const response = await saveAttendancePolicy({
      shift_start_minute: sessionClock ? 570 : hours * 60 + minutes,
      shift_minutes: sessionClock ? 540 : Number(form.get("shift_minutes")),
      grace_minutes: sessionClock ? 15 : Number(form.get("grace_minutes")),
      half_day_minutes: sessionClock ? 240 : Number(form.get("half_day_minutes")),
      full_day_minutes: sessionClock ? 480 : Number(form.get("full_day_minutes")),
      weekly_off: sessionClock ? [6] : form.getAll("weekly").map(Number),
      leave_quotas: quotas,
      session_clock: sessionClock,
    });
    setBusy(false);
    if (!response.ok) { setMessage(response.error); return; }
    setPolicy(response.data);
    setMessage(response.data.scheduled
      ? `Policy revision applies from ${attendanceDate(response.data.scheduled.effective_from)}.`
      : "Attendance is now open.");
  }

  async function saveHoliday(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const day = String(form.get("day"));
    await changeHoliday(day, String(form.get("name")).trim());
  }

  async function changeHoliday(day: string, name: string | null) {
    setHolidayBusy(true);
    setHolidayMessage("");
    const result = await setAttendanceHoliday(day, name);
    setHolidayBusy(false);
    setHolidayMessage(result.ok ? (name === null ? "Holiday removed." : "Holiday saved.") : result.error);
    if (result.ok) {
      setMonth(day.slice(0, 7));
      refresh((value) => value + 1);
    }
  }

  if (error) return <FetchError status={error.status} message={error.message} onRetry={() => refresh((value) => value + 1)} />;
  if (!policy) return <ListLoadingState rows={3} />;
  const shown = policy.scheduled ?? policy.active;
  return (
    <>
      <DashboardPanel title="Attendance policy"
        description={policy.active ? `Active from ${attendanceDate(policy.active.effective_from)}. Revisions apply to future work dates.`
          : "Set your shift, day thresholds, weekly offs and annual leave allowances to open attendance."}>
        <form key={shown?.version ?? "new"} onSubmit={(event) => void savePolicy(event)} className="space-y-4">
          <div className="space-y-1">
            <label className="flex min-h-10 items-center gap-2 text-sm font-medium">
              <input type="checkbox" name="session_clock" defaultChecked={shown?.session_clock} />
              Use the session clock
            </label>
            <p className="text-sm text-text-secondary">Applies the 9:30 a.m.–6:30 p.m. IST shift, a 1:30–2:30 p.m. lunch break, and Sundays off. The first change starts next month.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div><Label htmlFor="policy-start">Shift start (IST)</Label><Input id="policy-start" type="time" name="start" required defaultValue={shown ? asTime(shown.shift_start_minute) : "09:30"} /></div>
            {NUMBERS.map(([key, label, min]) => <div key={key}>
              <Label htmlFor={`policy-${key}`}>{label}</Label>
              <Input id={`policy-${key}`} name={key} type="number" min={min} max={1440} required defaultValue={shown?.[key] ?? {shift_minutes: 540, grace_minutes: 15, half_day_minutes: 240, full_day_minutes: 480}[key]} />
            </div>)}
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Weekly days off</legend>
            <div className="flex flex-wrap gap-3">
              {WEEKDAYS.map((day, index) => <label key={day} className="flex min-h-10 items-center gap-2 text-sm">
                <input type="checkbox" name="weekly" value={index} defaultChecked={shown?.weekly_off.includes(index) ?? index === 6} />{day}
              </label>)}
            </div>
          </fieldset>
          <div className="max-w-md space-y-2"><Label htmlFor="policy-quotas">Annual leave days by type</Label>
            <Textarea id="policy-quotas" name="quotas" rows={3} aria-describedby="policy-quotas-help"
              defaultValue={Object.entries(shown?.leave_quotas ?? {}).map(([key, units]) => `${key}=${units / 2}`).join("\n")} />
            <p id="policy-quotas-help" className="text-xs text-text-secondary">Enter one type per line, such as annual=12.5. Leave this blank when staff should have no leave allowance.</p>
          </div>
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save policy"}</Button>
          {message ? <p role="status" className="text-sm text-text-secondary">{message}</p> : null}
        </form>
      </DashboardPanel>
      <DashboardPanel title="Holidays" description="Changes apply to today or future work dates.">
        <form onSubmit={(event) => void saveHoliday(event)} className="flex flex-wrap items-end gap-3">
          <div><Label htmlFor="holiday-day">Holiday date</Label><Input id="holiday-day" name="day" type="date" min={today} required /></div>
          <div className="min-w-0 flex-1"><Label htmlFor="holiday-name">Holiday name</Label><Input id="holiday-name" name="name" required maxLength={120} /></div>
          <Button type="submit" disabled={holidayBusy || !policy.active}>Save holiday</Button>
        </form>
        <div className="mt-4 max-w-xs"><Label htmlFor="holiday-month">Show holidays for</Label>
          <Input id="holiday-month" type="month" value={month} onChange={(event) => { if (event.target.value) setMonth(event.target.value); }} /></div>
        {holidayMessage ? <p role="status" className="mt-2 text-sm">{holidayMessage}</p> : null}
        <ul className="mt-2 divide-y divide-border">
          {holidays.map((holiday) => <li key={holiday.day} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span className="min-w-0 [overflow-wrap:anywhere]">{attendanceDate(holiday.day)} · {holiday.name}</span>
            {holiday.day >= today ? <Button variant="outline" size="sm" disabled={holidayBusy} onClick={async () => {
              if (await confirm({ title: "Remove this holiday?", confirmLabel: "Remove", destructive: true })) {
                await changeHoliday(holiday.day, null);
              }
            }}>Remove</Button> : null}
          </li>)}
        </ul>
        {!holidays.length ? <p className="mt-2 text-sm text-text-secondary">No holidays in this month.</p> : null}
      </DashboardPanel>
      {confirmDialog}
    </>
  );
}
