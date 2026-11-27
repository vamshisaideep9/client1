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
import { useMe } from "@/features/dashboard/me-provider";
import {
  decideAttendanceRequest, exportAttendance, getAttendanceInbox, getAttendancePolicy, getAttendanceRoster,
  type AttendanceDecision, type AttendanceInbox, type AttendanceRequest, type AttendanceRoster,
} from "@/lib/attendance-api";
import { getMyTeams, listTeams } from "@/lib/staff-teams-api";
import { roleLabel } from "@/lib/role-label";
import { useProductCatalogue } from "@/features/dashboard/use-product-catalogue";
import {
  ATTENDANCE_STATUS, attendanceBadges, attendanceDate, attendanceLegend, attendanceTime, datesBetween,
  duration, istDay, leaveLabel, monthStart, rangeError, requestLabel,
} from "./attendance-display";
import { AttendancePolicyPanel } from "./attendance-policy-panel";
import { AttendanceEmploymentDialog } from "./attendance-employment-dialog";
import { AttendanceCertificateControl } from "./attendance-certificate-control";
import { AttendanceMonthPanel } from "./attendance-month-panel";

type Mode = "daily" | "month" | "requests" | "policy" | "close";
type FilterOption = { id: string; name: string };
type Member = AttendanceRoster["members"][number];
const PAGE_SIZE = 50;
const selectClass = "min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Roles with department-qualified labels; each sets role and department. */
const ROLE_OPTIONS = [
  { value: "telecaller:loans", label: "Loan Telecallers" },
  { value: "employee:loans", label: "Loan Officers" },
  { value: "telecaller:real_estate", label: "Real Estate Telecallers" },
  { value: "employee:real_estate", label: "Real Estate Officers" },
  { value: "sub_admin:", label: "Sub Admins" },
] as const;
/** Team-wise: a team, or a Sub Admin group. */
const GROUP_OPTIONS = [
  { value: "group:team_manager", label: "Team Managers" },
  { value: "group:account_manager", label: "Account Managers" },
  { value: "group:relationship_manager", label: "Relationship Managers" },
] as const;
const DEFAULT_LEAVE_TYPES = ["casual", "sick"];

export function AttendanceManagementView() {
  const { session } = useAuth();
  const { me } = useMe();
  const recommendationsOnly = Boolean(me?.subAdminAccess);
  const role = session?.role;
  const admin = role === "admin";
  const [mode, setMode] = useState<Mode>("daily");
  // One filter bar for both views: the roster opens on today, the grid on
  // the 1st of this month to today (31 days at most).
  const [dailyRange, setDailyRange] = useState(() => ({ start: istDay(), end: istDay() }));
  const [gridRange, setGridRange] = useState(() => ({ start: monthStart(), end: istDay() }));
  const [team, setTeam] = useState("");
  const [staff, setStaff] = useState("");
  const [status, setStatus] = useState("");
  const [department, setDepartment] = useState("");
  const [product, setProduct] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [leaveType, setLeaveType] = useState("");
  const [leaveTypes, setLeaveTypes] = useState<string[]>(DEFAULT_LEAVE_TYPES);
  const catalogue = useProductCatalogue(department !== "real_estate");
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
  const [assignment, setAssignment] = useState<{ member: AttendanceRoster["members"][number]; trigger: HTMLButtonElement } | null>(null);
  const [revision, refresh] = useState(0);
  const period = mode === "month" ? gridRange : dailyRange;
  const setPeriod = mode === "month" ? setGridRange : setDailyRange;
  const periodError = mode === "requests" ? null : rangeError(period.start, period.end);
  const dates = useMemo(
    () => (mode === "requests" ? [dailyRange.start] : datesBetween(period.start, period.end)),
    [dailyRange.start, mode, period.end, period.start],
  );
  const range = useMemo(() => {
    const query = new URLSearchParams({ start: dates[0] ?? istDay(), end: dates[dates.length - 1] ?? istDay() });
    if (team.startsWith("team:")) query.set("team_id", team.slice(5));
    if (team.startsWith("group:")) query.set("sub_admin_group", team.slice(6));
    if (staff) query.set("staff_id", staff);
    if (mode === "requests") return query;
    if (status) query.set("status", status);
    if (department) query.set("department", department);
    if (product) query.set("product_id", product);
    if (roleFilter) query.set("role", roleFilter.split(":")[0]);
    if (leaveType) query.set("leave_type", leaveType);
    return query;
  }, [dates, department, leaveType, mode, product, roleFilter, staff, status, team]);

  useEffect(() => {
    if (!admin) return;
    let current = true;
    void getAttendancePolicy().then((res) => {
      if (!current || !res.ok) return;
      const shown = res.data.scheduled ?? res.data.active;
      const keys = Object.keys(shown?.leave_quotas ?? {});
      if (keys.length) setLeaveTypes([...new Set([...DEFAULT_LEAVE_TYPES, ...keys])]);
    });
    return () => { current = false; };
  }, [admin]);

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
    if (!role || mode === "policy" || mode === "close" || periodError) return;
    let current = true;
    const query = new URLSearchParams(range);
    if (mode !== "requests") query.set("offset", String(offset));
    const requests = new URLSearchParams({ status: requestStatus, offset: String(offset) });
    if (team.startsWith("team:")) requests.set("team_id", team.slice(5));
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
  }, [mode, offset, periodError, range, requestStatus, revision, role, staff, team]);

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
          {admin ? <TabsTrigger value="close">Monthly close</TabsTrigger> : null}
        </TabsList>
        <TabsContent value={mode} className="space-y-4">
      {mode === "close" && admin ? <AttendanceMonthPanel manageable /> : mode === "policy" && admin ? <AttendancePolicyPanel /> : (
        <>
          <DashboardPanel title="Filters" action={admin && mode !== "requests" && roster?.configured ? (
            <Button variant="outline" disabled={exporting} onClick={() => void download()}>Export CSV</Button>
          ) : null}>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {mode !== "requests" ? <>
                <div><Label htmlFor="roster-from">From</Label>
                  <Input id="roster-from" type="date" value={period.start} max={period.end || undefined}
                    aria-describedby={periodError ? "roster-range-error" : undefined}
                    onChange={(event) => { if (event.target.value) { setPeriod((value) => ({ ...value, start: event.target.value })); setOffset(0); } }} /></div>
                <div><Label htmlFor="roster-to">To</Label>
                  <Input id="roster-to" type="date" value={period.end} min={period.start || undefined}
                    aria-describedby={periodError ? "roster-range-error" : undefined}
                    onChange={(event) => { if (event.target.value) { setPeriod((value) => ({ ...value, end: event.target.value })); setOffset(0); } }} /></div>
                <div><Label htmlFor="roster-department">Department</Label>
                  <select id="roster-department" className={selectClass} value={department} onChange={(event) => {
                    setDepartment(event.target.value); setOffset(0);
                    if (event.target.value === "real_estate") setProduct("");
                    if (roleFilter && !roleFilter.endsWith(`:${event.target.value}`) && !roleFilter.startsWith("sub_admin")) setRoleFilter("");
                  }}>
                    <option value="">All departments</option>
                    <option value="loans">Loans</option>
                    <option value="real_estate">Real Estate</option>
                  </select></div>
                <div><Label htmlFor="roster-product">Product</Label>
                  <select id="roster-product" className={selectClass} value={product} disabled={department === "real_estate"} onChange={(event) => {
                    setProduct(event.target.value); setOffset(0);
                  }}>
                    <option value="">All products</option>
                    {catalogue.products.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
                  </select></div>
                <div><Label htmlFor="roster-role">Role</Label>
                  <select id="roster-role" className={selectClass} value={roleFilter} onChange={(event) => {
                    const value = event.target.value;
                    setRoleFilter(value); setOffset(0);
                    const line = value.split(":")[1];
                    if (line) setDepartment(line);
                  }}>
                    <option value="">All roles</option>
                    {ROLE_OPTIONS.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
                  </select></div>
              </> : null}
              <div><Label htmlFor="roster-team">{mode === "requests" ? "Team" : "Team-wise"}</Label>
                <select id="roster-team" className={selectClass} value={team} onChange={(event) => {
                  setTeam(event.target.value); setStaff(""); setOffset(0);
                }}>
                  <option value="">{admin ? "All teams and unassigned" : "My teams"}</option>
                  {teams.length ? <optgroup label="Teams">
                    {teams.map((entry) => <option key={entry.id} value={`team:${entry.id}`}>{entry.name}</option>)}
                  </optgroup> : null}
                  {mode !== "requests" ? <optgroup label="Sub Admin groups">
                    {GROUP_OPTIONS.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
                  </optgroup> : null}
                </select>
              </div>
              {mode !== "requests" ? <div><Label htmlFor="roster-leave">Leave type</Label>
                <select id="roster-leave" className={selectClass} value={leaveType} onChange={(event) => {
                  setLeaveType(event.target.value); setOffset(0);
                }}>
                  <option value="">All leave types</option>
                  {leaveTypes.map((kind) => <option key={kind} value={kind}>{leaveLabel(kind)} leave</option>)}
                </select></div> : null}
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
            {periodError ? <p id="roster-range-error" role="alert" className="mt-2 text-sm text-destructive">{periodError}</p> : null}
            {teamsFailed ? <p role="status" className="mt-2 text-sm text-text-secondary">Team choices could not load. <Button variant="link" onClick={() => refresh((value) => value + 1)}>Retry</Button></p> : null}
            {notice ? <p role="status" className="mt-2 text-sm text-text-secondary">{notice}</p> : null}
          </DashboardPanel>
          <DashboardPanel title={mode === "requests" ? "Review requests" : mode === "month" ? "Monthly attendance" : "Daily attendance"}>
            {error ? <FetchError status={error.status} message={error.message} onRetry={() => refresh((value) => value + 1)} />
              : !roster || (mode === "requests" && !inbox) ? <ListLoadingState rows={3} />
              : !roster.configured && !(admin && mode === "daily") ? <p className="text-sm text-text-secondary">Admin setup is pending. Attendance will appear after the policy is configured.</p>
              : mode === "requests" && inbox ? (
                inbox.requests.length ? <ul className="divide-y divide-border">
                  {inbox.requests.map((entry) => (
                    <li key={entry.id} className="flex flex-wrap justify-between gap-3 py-3 text-sm">
                      <div className="min-w-0">
                        <p className="font-medium">{requestLabel(entry)} · {members.get(entry.staff_profile_id)?.name ?? "Staff member"}</p>
                        <p className="text-text-secondary">{attendanceDate(entry.start_day)}{entry.end_day !== entry.start_day ? ` – ${attendanceDate(entry.end_day)}` : ""} · {leaveLabel(entry.status)}</p>
                        <p className="text-text-secondary">Submitted {attendanceDate(istDay(new Date(entry.created_at)))} at {attendanceTime(entry.created_at)}</p>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => setReview(entry)}>{entry.status === "pending" ? "Review" : "Open request"}</Button>
                    </li>
                  ))}
                </ul> : <p className="text-sm text-text-secondary">No requests match these filters.</p>
              ) : <>
                {!roster.configured ? <p className="mb-3 text-sm text-text-secondary">Admin setup is pending. Attendance will appear after the policy is configured.</p> : null}
                <RosterTable roster={roster} dates={dates} daily={mode === "daily"} edit={admin && mode === "daily" ? (member, trigger) => setAssignment({ member, trigger }) : undefined} />
                {mode === "month" && roster.members.length ? <BadgeLegend roster={roster} /> : null}
              </>}
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
        admin={admin} recommendationsOnly={recommendationsOnly} close={() => setReview(null)}
        saved={() => { setNotice(recommendationsOnly ? "Attendance recommendation saved." : "Attendance decision saved."); refresh((value) => value + 1); }} /> : null}
      {assignment ? <AttendanceEmploymentDialog {...assignment} close={() => setAssignment(null)}
        saved={() => { setNotice("Attendance assignment saved."); refresh((value) => value + 1); }} /> : null}
    </DashboardPage>
  );
}

type DayRow = AttendanceRoster["days"][number];

const logoutTime = (row: DayRow | undefined) =>
  `${attendanceTime(row?.check_out ?? row?.system_check_out ?? null)}${row?.system_check_out && (!row.check_out || row.system_check_out === row.check_out) ? " (system)" : ""}`;

function memberHeader(member: Member, edit?: (member: Member, trigger: HTMLButtonElement) => void) {
  return <>
    {member.name}<span className="block text-xs text-text-secondary">{member.staff_code} · {roleLabel(member.role)}</span>
    {edit ? <Button variant="link" size="sm" className="h-9 px-0" aria-label={`Edit attendance assignment for ${member.name}`} onClick={(event) => edit(member, event.currentTarget)}>Edit assignment</Button> : null}
  </>;
}

function RosterTable({ roster, dates, daily, edit }: {
  roster: AttendanceRoster; dates: string[]; daily: boolean;
  edit?: (member: Member, trigger: HTMLButtonElement) => void;
}) {
  if (!roster.members.length) return <p className="text-sm text-text-secondary">No staff members match these filters.</p>;
  const byDay = new Map(roster.days.map((row) => [`${row.staff_profile_id}/${row.day}`, row]));
  const multiDay = dates.length > 1;
  return (
    <div className="overflow-x-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={0} role="region" aria-label={daily ? "Daily roster table" : "Monthly attendance grid"}>
      <table className="w-full min-w-max text-left text-sm">
        <thead className="bg-muted text-text-secondary">
          <tr><th scope="col" className="p-2">Staff member</th>
            {daily ? [...(multiDay ? ["Date"] : []), "Status", "Login (IST)", "Logout (IST)", "Worked", "LOP days"].map((label) => <th scope="col" className="p-2" key={label}>{label}</th>)
              : <>{dates.map((day) => <th scope="col" className="p-2" key={day} title={attendanceDate(day)}>{Number(day.slice(-2))}</th>)}<th scope="col" className="p-2">LOP days</th></>}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {roster.members.map((member) => {
            const totalLop = dates.reduce((sum, day) => sum + (byDay.get(`${member.staff_profile_id}/${day}`)?.lop_units ?? 0), 0);
            if (daily) {
              return dates.map((day, index) => {
                const row = byDay.get(`${member.staff_profile_id}/${day}`);
                return <tr key={`${member.staff_profile_id}/${day}`}>
                  {index === 0 ? <th scope="row" rowSpan={dates.length} className="p-2 align-top font-medium">{memberHeader(member, edit)}</th> : null}
                  {multiDay ? <td className="whitespace-nowrap p-2">{attendanceDate(day)}</td> : null}
                  <td className="p-2">{row ? ATTENDANCE_STATUS[row.status] : "Unrecorded"}{row?.late ? " · Late" : ""}</td>
                  <td className="p-2">{attendanceTime(row?.check_in ?? null)}</td>
                  <td className="p-2">{logoutTime(row)}</td>
                  <td className="p-2">{row ? duration(row.worked_minutes) : "—"}</td>
                  <td className="p-2">{(row?.lop_units ?? 0) / 4}</td>
                </tr>;
              });
            }
            return <tr key={member.staff_profile_id}>
              <th scope="row" className="p-2 font-medium">{memberHeader(member, edit)}</th>
              {dates.map((day) => {
                const entry = byDay.get(`${member.staff_profile_id}/${day}`);
                const badges = entry ? attendanceBadges(entry) : [];
                const times = entry?.check_in ? ` · Login ${attendanceTime(entry.check_in)} · Logout ${logoutTime(entry)}` : "";
                return <td key={day} className="p-2 text-xs" title={entry ? `${attendanceDate(day)}: ${badges.map((badge) => badge.label).join(", ") || ATTENDANCE_STATUS[entry.status]}${times}` : undefined}>{badges.length
                  ? <div className="flex gap-0.5">{badges.map(({ code, label, tone }) => <span key={code} className={`rounded px-1 ${tone}`} title={`${label}${times}`}>
                    <span aria-hidden="true">{code}</span><span className="sr-only">{label}{times}</span>
                  </span>)}</div>
                  : entry ? ATTENDANCE_STATUS[entry.status] : "—"}</td>;
              })}
              <td className="p-2">{totalLop / 4}</td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

/** What every grid code means, including other leave types in view. */
function BadgeLegend({ roster }: { roster: AttendanceRoster }) {
  const legend = attendanceLegend(roster.days);
  return <section aria-labelledby="attendance-legend-title" className="mt-4">
    <h3 id="attendance-legend-title" className="mb-2 text-sm font-semibold text-text-primary">Legend</h3>
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-xs" aria-label="Attendance codes">
      {legend.map(({ code, label, tone }) => <li key={code} className="flex items-center gap-1.5">
        <span className={`rounded px-1 font-medium ${tone}`} aria-hidden="true">{code}</span><span>{label}</span>
        <span className="sr-only">({code})</span>
      </li>)}
    </ul>
  </section>;
}

function ReviewDialog({ entry, name, admin, recommendationsOnly, close, saved }: {
  entry: AttendanceRequest; name?: string; admin: boolean; recommendationsOnly: boolean;
  close: () => void; saved: () => void;
}) {
  const last = entry.decisions.at(-1);
  const stage = entry.two_stage && (!admin || last?.stage !== "recommendation")
    ? "recommendation"
    : "decision";
  const reversing = entry.two_stage && entry.status === "approved";
  const canDecide = entry.two_stage
    ? entry.status === "pending" || reversing
    : admin || (!recommendationsOnly && entry.status === "pending");
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
      note, status, expected_decisions: entry.decisions.length, stage,
    });
    setBusy(false);
    if (!response.ok) { setError(response.error); return; }
    saved();
    close();
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}>
      <DialogContent preventOutsideClose className="max-h-[92dvh] overflow-y-auto">
        <DialogHeader><DialogTitle>{entry.kind === "leave" ? "Leave request" : requestLabel(entry)}</DialogTitle>
          <DialogDescription>{name ?? "Staff member"} · {leaveLabel(entry.status)}</DialogDescription></DialogHeader>
        <div className="space-y-2 text-sm">
          <p>{attendanceDate(entry.start_day)}{entry.end_day !== entry.start_day ? ` – ${attendanceDate(entry.end_day)}` : ""}</p>
          {entry.kind === "leave" ? <p>{leaveLabel(entry.leave_type ?? "leave")}{entry.leave_session ? ` · ${leaveLabel(entry.leave_session)} half day` : entry.half_day ? " · Half day" : ""}</p>
            : entry.kind === "correction" ? <p>{attendanceTime(entry.requested_check_in)} – {attendanceTime(entry.requested_check_out)} IST</p> : null}
          <p>Submitted {attendanceDate(istDay(new Date(entry.created_at)))} at {attendanceTime(entry.created_at)}</p>
          <p className="[overflow-wrap:anywhere]">{entry.reason}</p>
          {admin && entry.certificate_required ? <AttendanceCertificateControl requestId={entry.id} /> : null}
          {entry.decisions.length ? <ol className="list-decimal space-y-1 pl-5" aria-label="Decision history">
            {entry.decisions.map((decision, index) => <li key={index} className="[overflow-wrap:anywhere]">
              {decision.stage === "recommendation" ? "Recommended " : ""}{leaveLabel(decision.status)} · {roleLabel(decision.actor_role)} · {attendanceDate(istDay(new Date(decision.at)))} at {attendanceTime(decision.at)} · {decision.note}
            </li>)}
          </ol> : null}
        </div>
        {canDecide ? <form onSubmit={(event) => void submit(event)} className="space-y-3">
          <div><Label htmlFor="review-decision">{stage === "recommendation" ? "Recommendation" : "Decision"}</Label>
            <select id="review-decision" name="status" className={selectClass} required defaultValue="">
              <option value="" disabled>Select decision</option>
              {!reversing && entry.status !== "approved" ? <option value="approved">Approve</option> : null}
              {!reversing && entry.status !== "rejected" && entry.status !== "cancelled" ? <option value="rejected">Reject</option> : null}
              {reversing || (!entry.two_stage && admin && entry.status !== "cancelled") ? <option value="cancelled">Cancel request</option> : null}
            </select></div>
          <div><Label htmlFor="review-note">Review note</Label><Textarea id="review-note" name="note" required maxLength={500} /></div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <DialogFooter><Button variant="outline" type="button" onClick={close} disabled={busy}>Close</Button>
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : stage === "recommendation" ? "Save recommendation" : "Save decision"}</Button></DialogFooter>
        </form> : <DialogFooter><Button variant="outline" onClick={close}>Close</Button></DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}
