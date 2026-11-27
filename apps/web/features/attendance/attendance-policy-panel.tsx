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
  getAttendanceHolidays, getAttendanceHolidayYear, getAttendancePolicy, saveAttendancePolicy, setAttendanceHoliday,
  stopRecurringAttendanceHoliday,
  type AttendanceHoliday, type AttendanceLine, type AttendancePolicy, type AttendancePolicyState,
} from "@/lib/attendance-api";
import { attendanceDate, duration, istDay, leaveLabel, monthDays } from "./attendance-display";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
/** Durations entered as hours and minutes and saved in minutes. */
const DURATIONS = [
  ["shift_minutes", "Shift duration", 540],
  ["half_day_minutes", "Half-day minimum", 240],
  ["full_day_minutes", "Full-day minimum", 480],
] as const;
type DurationKey = (typeof DURATIONS)[number][0];

function durationMinutes(form: FormData, key: DurationKey) {
  return Number(form.get(`${key}-hours`)) * 60 + Number(form.get(`${key}-mins`));
}

function DurationField({ name, label, initial }: { name: DurationKey; label: string; initial: number }) {
  const [total, setTotal] = useState(initial);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return <fieldset className="min-w-0" aria-describedby={`policy-${name}-total`}>
    <legend className="text-sm font-medium">{label}</legend>
    <div className="mt-1 flex items-center gap-2">
      <Label htmlFor={`policy-${name}-hours`} className="sr-only">{label} hours</Label>
      <Input id={`policy-${name}-hours`} name={`${name}-hours`} type="number" min={0} max={24} required className="w-20"
        defaultValue={hours} onChange={(event) => setTotal(Number(event.target.value) * 60 + minutes)} />
      <span className="text-sm text-text-secondary">h</span>
      <Label htmlFor={`policy-${name}-mins`} className="sr-only">{label} minutes</Label>
      <Input id={`policy-${name}-mins`} name={`${name}-mins`} type="number" min={0} max={59} required className="w-20"
        defaultValue={minutes} onChange={(event) => setTotal(hours * 60 + Number(event.target.value))} />
      <span className="text-sm text-text-secondary">m</span>
    </div>
    <p id={`policy-${name}-total`} className="mt-1 text-xs text-text-secondary">{duration(total)}</p>
  </fieldset>;
}

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
  const [line, setLine] = useState<AttendanceLine | "">("");
  const [quotaDraft, setQuotaDraft] = useState<string | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(true);
  const [month, setMonth] = useState(() => istDay().slice(0, 7));
  const [view, setView] = useState<"month" | "year">("month");
  const [year, setYear] = useState(() => Number(istDay().slice(0, 4)));
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
    const calendarRequest = view === "year"
      ? getAttendanceHolidayYear(year, line || undefined)
      : getAttendanceHolidays(days[0], days[days.length - 1], line || undefined);
    void Promise.all([getAttendancePolicy(), calendarRequest])
      .then(([state, calendar]) => {
        if (!current) return;
        if (!state.ok || !calendar.ok) {
          const failure = !state.ok ? state : calendar;
          if (!failure.ok) setError({ status: failure.status, message: failure.error });
          setCalendarLoading(false);
          return;
        }
        setPolicy(state.data);
        setHolidays(calendar.data);
        setCalendarLoading(false);
        setError(null);
      });
    return () => { current = false; };
  }, [line, month, revision, view, year]);

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
    const monthlyRules: NonNullable<AttendancePolicy["monthly_leave_rules"]> = {};
    const retention = String(form.get("certificate-retention") ?? "");
    for (const kind of Object.keys(quotas)) {
      if (!form.has(`monthly-${kind}`)) continue;
      const accrual = Number(form.get(`accrual-${kind}`)) * 2;
      const threshold = String(form.get(`certificate-${kind}`) ?? "");
      if (accrual <= 0) { setMessage(`Enter monthly accrual for ${leaveLabel(kind)}.`); return; }
      monthlyRules[kind] = {
        accrual_units: accrual,
        carry_units: Number(form.get(`carry-${kind}`)) * 2,
        sandwich: form.has(`sandwich-${kind}`),
        certificate_after_days: threshold ? Number(threshold) : null,
      };
    }
    setBusy(true);
    setMessage("");
    const response = await saveAttendancePolicy({
      shift_start_minute: sessionClock ? 570 : hours * 60 + minutes,
      shift_minutes: sessionClock ? 540 : durationMinutes(form, "shift_minutes"),
      grace_minutes: sessionClock ? 15 : Number(form.get("grace_minutes")),
      half_day_minutes: sessionClock ? 240 : durationMinutes(form, "half_day_minutes"),
      full_day_minutes: sessionClock ? 480 : durationMinutes(form, "full_day_minutes"),
      weekly_off: sessionClock ? [6] : form.getAll("weekly").map(Number),
      leave_quotas: quotas,
      session_clock: sessionClock,
      ...(policy?.can_configure_leave_rules ? {
        monthly_leave_rules: monthlyRules,
        certificate_retention_days: retention ? Number(retention) : null,
      } : {}),
    });
    setBusy(false);
    if (!response.ok) { setMessage(response.error); return; }
    setPolicy(response.data);
    setQuotaDraft(null);
    setMessage(response.data.scheduled
      ? `Policy revision applies from ${attendanceDate(response.data.scheduled.effective_from)}.`
      : "Attendance is now open.");
  }

  async function saveHoliday(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const day = String(form.get("day"));
    const repeat = form.has("repeat_yearly");
    if (await changeHoliday(day, String(form.get("name")).trim(), repeat)) formElement.reset();
  }

  async function changeHoliday(day: string, name: string | null, repeatYearly = false) {
    setHolidayBusy(true);
    setHolidayMessage("");
    const result = await setAttendanceHoliday(day, name, line || undefined, repeatYearly);
    setHolidayBusy(false);
    setHolidayMessage(result.ok
      ? (name === null ? "Holiday removed." : repeatYearly ? "Holiday saved. It repeats every year." : "Holiday saved.")
      : result.error);
    if (result.ok) {
      setCalendarLoading(true);
      setMonth(day.slice(0, 7));
      setYear(Number(day.slice(0, 4)));
      refresh((value) => value + 1);
    }
    return result.ok;
  }

  async function stopRepeating(holiday: AttendanceHoliday) {
    if (!holiday.recurring_id) return;
    const stop = await confirm({
      title: "Stop repeating this holiday?",
      description: "Earlier dates stay as they were. It will not repeat after today.",
      confirmLabel: "Stop repeating",
      destructive: true,
    });
    if (!stop) return;
    setHolidayBusy(true);
    setHolidayMessage("");
    const result = await stopRecurringAttendanceHoliday(holiday.recurring_id);
    setHolidayBusy(false);
    setHolidayMessage(result.ok ? "The holiday no longer repeats after today." : result.error);
    if (result.ok) {
      setCalendarLoading(true);
      refresh((value) => value + 1);
    }
  }

  if (error) return <FetchError status={error.status} message={error.message} onRetry={() => refresh((value) => value + 1)} />;
  if (!policy) return <ListLoadingState rows={3} />;
  const shown = policy.scheduled ?? policy.active;
  const quotaText = Object.entries(shown?.leave_quotas ?? {}).map(([key, units]) => `${key}=${units / 2}`).join("\n");
  const leaveTypes = Object.keys(parseQuotas(quotaDraft ?? quotaText) ?? {});
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
            {DURATIONS.map(([key, label, fallback]) => <DurationField key={key} name={key} label={label} initial={shown?.[key] ?? fallback} />)}
            <div><Label htmlFor="policy-grace_minutes">Grace period (minutes)</Label>
              <Input id="policy-grace_minutes" name="grace_minutes" type="number" min={0} max={1440} required defaultValue={shown?.grace_minutes ?? 15} /></div>
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
              value={quotaDraft ?? quotaText} onChange={(event) => setQuotaDraft(event.target.value)} />
            <p id="policy-quotas-help" className="text-xs text-text-secondary">Enter one type per line, such as annual=12.5. Leave this blank when staff should have no leave allowance.</p>
          </div>
          {policy.can_configure_leave_rules ? <details className="rounded-md border border-border p-4">
            <summary className="cursor-pointer text-sm font-medium">Monthly leave rules</summary>
            <div className="mt-3 space-y-4">
              <p className="text-sm text-text-secondary">Types with monthly rules earn leave in the session clock. Revisions begin on the first of a month.</p>
              {leaveTypes.length ? leaveTypes.map((kind) => {
                const rule = shown?.monthly_leave_rules?.[kind];
                return <fieldset key={kind} className="space-y-2 rounded-md border border-border p-3">
                  <legend className="px-1 text-sm font-medium">{leaveLabel(kind)}</legend>
                  <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" name={`monthly-${kind}`} defaultChecked={Boolean(rule)} />Use monthly accrual</label>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div><Label htmlFor={`accrual-${kind}`}>Days earned each month</Label><Input id={`accrual-${kind}`} name={`accrual-${kind}`} type="number" step="0.5" min="0.5" max="31" defaultValue={rule ? rule.accrual_units / 2 : undefined} /></div>
                    <div><Label htmlFor={`carry-${kind}`}>Maximum days carried</Label><Input id={`carry-${kind}`} name={`carry-${kind}`} type="number" step="0.5" min="0" max="366" defaultValue={(rule?.carry_units ?? 0) / 2} /></div>
                    <div><Label htmlFor={`certificate-${kind}`}>Require certificate after (calendar days)</Label><Input id={`certificate-${kind}`} name={`certificate-${kind}`} type="number" min="0" max="30" defaultValue={rule?.certificate_after_days ?? undefined} /></div>
                  </div>
                  <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" name={`sandwich-${kind}`} defaultChecked={rule?.sandwich} />Charge days off between working days in the same leave request</label>
                </fieldset>;
              }) : <p className="text-sm text-text-secondary">Add a leave type above to configure monthly accrual.</p>}
              <div className="max-w-xs"><Label htmlFor="certificate-retention">Certificate retention (days from upload)</Label>
                <Input id="certificate-retention" name="certificate-retention" type="number" min="1" max="3660" defaultValue={shown?.certificate_retention_days ?? undefined} /></div>
            </div>
          </details> : null}
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save policy"}</Button>
          {message ? <p role="status" className="text-sm text-text-secondary">{message}</p> : null}
        </form>
      </DashboardPanel>
      <DashboardPanel title="Holidays" description="All-staff holidays also apply to both department calendars. Changes apply to today or future work dates.">
        <div className="mb-3 max-w-xs"><Label htmlFor="holiday-calendar">Calendar</Label>
          <select id="holiday-calendar" className="min-h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={line} disabled={holidayBusy} onChange={(event) => {
            setCalendarLoading(true); setHolidayMessage(""); setLine(event.target.value as AttendanceLine | "");
          }}>
            <option value="">All staff</option><option value="loans">Loans</option><option value="real_estate">Real estate</option>
          </select>
        </div>
        <form onSubmit={(event) => void saveHoliday(event)} className="flex flex-wrap items-end gap-3">
          <div><Label htmlFor="holiday-day">Holiday date</Label><Input id="holiday-day" name="day" type="date" min={today} required /></div>
          <div className="min-w-0 flex-1"><Label htmlFor="holiday-name">Holiday name</Label><Input id="holiday-name" name="name" required maxLength={120} /></div>
          <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" name="repeat_yearly" />Repeat every year</label>
          <Button type="submit" disabled={holidayBusy || !policy.active}>Save holiday</Button>
        </form>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <fieldset>
            <legend className="mb-1 text-sm font-medium">View</legend>
            <div className="inline-flex rounded-md border border-border p-0.5" role="group" aria-label="Holiday view">
              {(["month", "year"] as const).map((value) => <Button key={value} type="button" size="sm" variant={view === value ? "default" : "ghost"}
                aria-pressed={view === value} onClick={() => { if (view !== value) { setCalendarLoading(true); setView(value); } }}>
                {value === "month" ? "Month" : "Year"}
              </Button>)}
            </div>
          </fieldset>
          {view === "month" ? <div className="max-w-xs"><Label htmlFor="holiday-month">Show holidays for</Label>
            <Input id="holiday-month" type="month" value={month} onChange={(event) => { if (event.target.value) { setCalendarLoading(true); setMonth(event.target.value); } }} /></div>
            : <div className="max-w-[10rem]"><Label htmlFor="holiday-year">Year</Label>
              <Input id="holiday-year" type="number" min={2000} max={9998} value={year} onChange={(event) => {
                const next = Number(event.target.value);
                if (Number.isInteger(next) && next >= 2000 && next <= 9998) { setCalendarLoading(true); setYear(next); }
              }} /></div>}
        </div>
        {holidayMessage ? <p role="status" className="mt-2 text-sm">{holidayMessage}</p> : null}
        {calendarLoading ? <ListLoadingState rows={1} /> : <ul className="mt-2 divide-y divide-border">
          {holidays.map((holiday) => <li key={`${holiday.day}-${holiday.recurring_id ?? "once"}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {attendanceDate(holiday.day)} · {holiday.name}
              {holiday.repeats_yearly ? <span className="ml-2 rounded bg-violet-100 px-1.5 py-0.5 text-xs font-medium text-violet-950">Yearly</span> : null}
            </span>
            {holiday.repeats_yearly ? (
              !holiday.ends_on || holiday.ends_on > today ? <Button variant="outline" size="sm" disabled={holidayBusy}
                aria-label={`Stop repeating ${holiday.name}`} onClick={() => void stopRepeating(holiday)}>Stop repeating</Button> : null
            ) : holiday.day >= today ? <Button variant="outline" size="sm" disabled={holidayBusy} onClick={async () => {
              if (await confirm({ title: "Remove this holiday?", confirmLabel: "Remove", destructive: true })) {
                await changeHoliday(holiday.day, null);
              }
            }}>Remove</Button> : null}
          </li>)}
        </ul>}
        {!calendarLoading && !holidays.length ? <p className="mt-2 text-sm text-text-secondary">No holidays in this calendar for the {view}.</p> : null}
      </DashboardPanel>
      {confirmDialog}
    </>
  );
}
