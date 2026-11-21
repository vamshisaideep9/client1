"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FetchError } from "@/features/dashboard/fetch-error";
import { ListLoadingState } from "@/features/dashboard/list-states";
import {
  getAttendanceEmployment, getAttendanceReviewers, saveAttendanceEmployment,
  type AttendanceEmployment, type AttendanceLine, type AttendanceRoster,
} from "@/lib/attendance-api";

const selectClass = "min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
type Member = AttendanceRoster["members"][number];

export function AttendanceEmploymentDialog({ member, trigger, close, saved }: {
  member: Member;
  trigger: HTMLButtonElement;
  close: () => void;
  saved: () => void;
}) {
  const [assignment, setAssignment] = useState<AttendanceEmployment | null>();
  const [line, setLine] = useState<AttendanceLine | "">("");
  const [reviewer, setReviewer] = useState("");
  const [reviewers, setReviewers] = useState<Member[] | null>(null);
  const [failure, setFailure] = useState<{ status: number; message: string } | null>(null);
  const [reviewerError, setReviewerError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, retry] = useState(0);
  const [reviewerRevision, retryReviewers] = useState(0);
  const loaded = assignment !== undefined;

  useEffect(() => {
    let live = true;
    void getAttendanceEmployment(member.staff_profile_id).then((result) => {
      if (!live) return;
      if (!result.ok) { setFailure({ status: result.status, message: result.error }); return; }
      setLine(result.data?.business_line ?? "");
      setReviewer(result.data?.reviewer_id ?? "");
      setFailure(null);
      setAssignment(result.data);
    });
    return () => { live = false; };
  }, [member.staff_profile_id, revision]);

  useEffect(() => {
    if (!loaded || !line) return;
    let live = true;
    void getAttendanceReviewers(line).then((result) => {
      if (!live) return;
      if (!result.ok) { setReviewerError(result.error); return; }
      setReviewers(result.data.filter((choice) => choice.staff_profile_id !== member.staff_profile_id));
      setReviewerError("");
    });
    return () => { live = false; };
  }, [line, loaded, member.staff_profile_id, reviewerRevision]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!line) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    const result = await saveAttendanceEmployment(member.staff_profile_id, {
      start_day: String(form.get("start")),
      end_day: String(form.get("end") ?? "") || null,
      business_line: line,
      reviewer_id: reviewer || null,
      expected_version: assignment?.version ?? 0,
    });
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    saved();
    close();
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}>
      <DialogContent preventOutsideClose className="max-h-[92dvh] overflow-y-auto" onCloseAutoFocus={(event) => {
        event.preventDefault();
        trigger.focus();
      }}>
        <DialogHeader>
          <DialogTitle>Attendance assignment</DialogTitle>
          <DialogDescription>{member.name} · {member.staff_code}</DialogDescription>
        </DialogHeader>
        {failure ? <FetchError {...failure} onRetry={() => retry((value) => value + 1)} />
          : !loaded ? <ListLoadingState rows={2} /> : (
            <form className="space-y-3" onSubmit={(event) => void submit(event)}>
              <div className="grid gap-3 sm:grid-cols-2">
                <div><Label htmlFor="employment-start">Employment start</Label>
                  <Input id="employment-start" name="start" type="date" min="2000-01-01" max="9998-12-31" required defaultValue={assignment?.start_day} /></div>
                <div><Label htmlFor="employment-end">Employment end (optional)</Label>
                  <Input id="employment-end" name="end" type="date" min="2000-01-01" max="9998-12-31" defaultValue={assignment?.end_day ?? ""} /></div>
              </div>
              <div><Label htmlFor="employment-line">Calendar</Label>
                <select id="employment-line" className={selectClass} value={line} disabled={busy} required onChange={(event) => {
                  setReviewers(null); setReviewer(""); setReviewerError(""); setLine(event.target.value as AttendanceLine | "");
                }}>
                  <option value="" disabled>Choose a calendar</option><option value="loans">Loans</option><option value="real_estate">Real estate</option>
                </select></div>
              <div><Label htmlFor="employment-reviewer">Direct attendance reviewer (optional)</Label>
                <select id="employment-reviewer" className={selectClass} value={reviewer} disabled={busy || !reviewers} onChange={(event) => setReviewer(event.target.value)} aria-describedby="employment-reviewer-help">
                  <option value="">Use existing review routing</option>
                  {reviewer && !reviewers?.some((choice) => choice.staff_profile_id === reviewer) ? <option value={reviewer}>Current reviewer unavailable</option> : null}
                  {reviewers?.map((choice) => <option key={choice.staff_profile_id} value={choice.staff_profile_id}>{choice.name} ({choice.staff_code})</option>)}
                </select>
                <p id="employment-reviewer-help" className="text-sm text-text-secondary">The reviewer can access attendance in this line.</p>
                {reviewerError ? <p role="status" className="text-sm text-destructive">{reviewerError} <Button type="button" variant="link" onClick={() => { setReviewerError(""); retryReviewers((value) => value + 1); }}>Retry</Button></p>
                  : line && !reviewers ? <p role="status" className="text-sm text-text-secondary">Loading reviewers…</p> : null}
              </div>
              {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
              <DialogFooter>
                <Button type="button" variant="outline" disabled={busy} onClick={close}>Cancel</Button>
                <Button type="submit" disabled={busy || !reviewers}>{busy ? "Saving…" : "Save assignment"}</Button>
              </DialogFooter>
            </form>
          )}
      </DialogContent>
    </Dialog>
  );
}
