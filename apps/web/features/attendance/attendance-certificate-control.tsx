"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { downloadAttendanceCertificate, uploadAttendanceCertificate } from "@/lib/attendance-api";

export function AttendanceCertificateControl({ requestId, editable }: { requestId: string; editable?: boolean }) {
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function upload() {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { setMessage("Choose a file up to 5 MB."); return; }
    setBusy(true);
    setMessage("");
    try {
      const result = await uploadAttendanceCertificate(requestId, file);
      setMessage(result.ok ? "Certificate uploaded." : result.error);
      if (result.ok) {
        if (fileInput.current) fileInput.current.value = "";
        setFile(null);
      }
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setMessage("");
    try {
      const result = await downloadAttendanceCertificate(requestId);
      setMessage(result.ok ? "Certificate downloaded." : result.error);
    } catch {
      setMessage("The download was interrupted. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="space-y-2">
    {editable ? <div className="space-y-1">
      <Label htmlFor={id}>Medical certificate (PDF, JPEG or PNG, up to 5 MB)</Label>
      <Input id={id} ref={fileInput} type="file" accept="application/pdf,image/jpeg,image/png" disabled={busy}
        onChange={(event) => { setFile(event.target.files?.[0] ?? null); setMessage(""); }} />
    </div> : null}
    <div className="flex flex-wrap gap-2">
      {editable ? <Button type="button" variant="outline" size="sm" disabled={busy || !file} onClick={() => void upload()}>Upload certificate</Button> : null}
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void download()}>Download certificate</Button>
    </div>
    {busy || message ? <p role="status" className="text-sm text-text-secondary">{busy ? "Working…" : message}</p> : null}
  </div>;
}
