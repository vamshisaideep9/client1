"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { components } from "@contracts/generated/schema";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { WebsiteBody } from "@/components/website-content";
import { DashboardHeader, DashboardPage } from "@/features/dashboard/dashboard-ui";
import { apiRequest } from "@/lib/api/client";
import { WEBSITE_PAGES, websiteKeyPath, type WebsiteContent } from "@/lib/website-content";

type Schema = components["schemas"];
type DocumentRead = Schema["WebsiteDocumentRead"];
type Entry = Schema["WebsiteEntry"];
type Faq = Schema["WebsiteFAQ"];
const base = "/api/v1/website-content";
const selectClass = "min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm";
const contactFields = {
  heading: "Form heading", name: "Name label", mobile: "Phone label",
  email: "Email label", message: "Message label", topic: "Enquiry label",
  submit: "Submit button", help: "Form help", product: "Product label",
} as const;

export function WebsiteContentEditor({ initialKey = "page/home", destinations }: {
  initialKey?: string;
  destinations: Record<string, string>;
}) {
  const [access, setAccess] = useState<Schema["WebsiteAccess"]>();
  const [editors, setEditors] = useState<Schema["WebsiteEditor"][]>([]);
  const [keys, setKeys] = useState<string[]>([]);
  const [key, setKey] = useState(initialKey);
  const [newKey, setNewKey] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void apiRequest<Schema["WebsiteAccess"]>(`${base}/access`).then(async (result) => {
      if (!active) return;
      if (!result.ok) { setError(result.error); return; }
      setAccess(result.data);
      if (!result.data.can_edit) return;
      const documents = await apiRequest<string[]>(`${base}/documents`);
      if (active && documents.ok) setKeys(documents.data);
      if (!result.data.can_publish) return;
      const eligible = await apiRequest<Schema["WebsiteEditor"][]>(`${base}/editors`);
      if (active && eligible.ok) setEditors(eligible.data);
      if (active && !eligible.ok) setError(eligible.error);
    });
    return () => { active = false; };
  }, []);

  async function toggleAccess(editor: Schema["WebsiteEditor"]) {
    setError("");
    const body: Schema["WebsiteGrantWrite"] = { enabled: !editor.enabled };
    const result = await apiRequest(`${base}/editors/${editor.profile_id}`, { method: "PUT", body });
    if (!result.ok) { setError(result.error); return; }
    setEditors((previous) => previous.map((item) =>
      item.profile_id === editor.profile_id ? { ...item, enabled: body.enabled } : item,
    ));
  }

  const labels: Record<string, string> = { ...WEBSITE_PAGES, ...destinations };
  const choices = [...new Set([...Object.keys(labels), ...keys, key])];
  return (
    <DashboardPage>
      <DashboardHeader title="Website Content" description="Edit public pages, FAQs and knowledge articles." />
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {!access && !error ? <p role="status">Checking website access…</p> : null}
      {access && !access.can_edit ? <p>Main Admin can grant you access to edit website drafts.</p> : null}
      {access?.can_edit ? (
        <div className="space-y-6">
          {access.can_publish ? (
            <div className="flex flex-wrap gap-3">
              <Button asChild variant="outline"><Link href="/dashboard/loan-config">Banks and financial products</Link></Button>
              <Button asChild variant="outline"><Link href="/dashboard/property-review">Property submissions</Link></Button>
              <Button asChild variant="outline"><Link href="/dashboard/property-review/types">Property types</Link></Button>
              <Button asChild variant="outline"><Link href="/dashboard/campaign-approvals">Campaign approvals</Link></Button>
            </div>
          ) : null}
          <section className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-6">
            <label className="block space-y-2">
              <span className="text-sm font-medium">Page or article</span>
              <select className={selectClass} value={key} onChange={(event) => setKey(event.target.value)}>
                {choices.map((item) => <option key={item} value={item}>
                  {labels[item] ?? item}
                </option>)}
              </select>
            </label>
            <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
              event.preventDefault();
              setKey(`article/${newKey.trim()}`);
              setNewKey("");
            }}>
              <label className="min-w-0 flex-1 space-y-2">
                <span className="text-sm font-medium">New knowledge article</span>
                <Input value={newKey} onChange={(event) => setNewKey(event.target.value)}
                  placeholder="home-loan-guide" maxLength={152}
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*" required />
              </label>
              <Button type="submit" variant="outline">Open article</Button>
            </form>
          </section>
          <DocumentEditor key={key} documentKey={key} title={labels[key] ?? key} canPublish={access.can_publish}
            onSave={() => setKeys((previous) => previous.includes(key) ? previous : [...previous, key])} />
          {access.can_publish ? (
            <section className="space-y-3 rounded-xl border border-border bg-surface p-4 sm:p-6">
              <h2 className="font-heading text-xl font-semibold">Draft access</h2>
              {editors.length === 0 ? <p>No eligible staff profiles found.</p> : null}
              {editors.map((editor) => (
                <div key={editor.profile_id} className="flex items-center justify-between gap-3 border-t border-border pt-3">
                  <p>{editor.staff_code} <span className="text-sm text-text-secondary">{editor.role === "admin" ? "Admin" : "Sub Admin"}</span></p>
                  <Button variant="outline" onClick={() => void toggleAccess(editor)}>
                    {editor.enabled ? "Revoke draft access" : "Grant draft access"}
                  </Button>
                </div>
              ))}
            </section>
          ) : null}
        </div>
      ) : null}
    </DashboardPage>
  );
}

function DocumentEditor({ documentKey, title, canPublish, onSave }: {
  documentKey: string;
  title: string;
  canPublish: boolean;
  onSave: () => void;
}) {
  const { confirm, confirmDialog } = useConfirm();
  const [document, setDocument] = useState<DocumentRead>();
  const [content, setContent] = useState<WebsiteContent>({ title: "", summary: "", body: "" });
  const [history, setHistory] = useState<Schema["WebsiteRevisionRead"][]>([]);
  const [restoreRevision, setRestoreRevision] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const path = websiteKeyPath(documentKey);
  const endpoint = `${base}/documents/${path}`;

  useEffect(() => {
    let active = true;
    void apiRequest<DocumentRead>(endpoint).then(async (result) => {
      if (!active) return;
      if (result.ok) {
        setDocument(result.data);
        setContent(result.data.draft);
        const revisions = await apiRequest<Schema["WebsiteRevisionRead"][]>(`${base}/revisions/${path}`);
        if (active && revisions.ok) setHistory(revisions.data);
      } else if (result.status !== 404) {
        setError(result.error);
        return;
      }
      if (active) setLoaded(true);
    });
    return () => { active = false; };
  }, [endpoint, path]);

  function change(next: Partial<WebsiteContent>) {
    setContent((previous) => ({ ...previous, ...next }));
    setDirty(true);
    setNotice("");
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const body: Schema["WebsiteDraftWrite"] = { expected_version: document?.version ?? 0, content };
    const result = await apiRequest<DocumentRead>(endpoint, { method: "PUT", body });
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setDocument(result.data);
    setContent(result.data.draft);
    setDirty(false);
    onSave();
    setNotice("Draft saved.");
  }

  async function publish(revision?: number) {
    if (!document || !(await confirm({
      title: revision ? "Restore this revision?" : "Publish this draft?",
      description: "This changes what visitors can see on the public website.",
      confirmLabel: revision ? "Restore revision" : "Publish",
    }))) return;
    setBusy(true);
    setError("");
    const body: Schema["WebsitePublishWrite"] = { expected_version: document.version, restore_revision: revision };
    const result = await apiRequest<DocumentRead>(`${base}/publish/${path}`, { method: "POST", body });
    const revisions = result.ok
      ? await apiRequest<Schema["WebsiteRevisionRead"][]>(`${base}/revisions/${path}`)
      : null;
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setDocument(result.data);
    if (revisions?.ok) setHistory(revisions.data);
    setRestoreRevision("");
    setNotice(revision ? "Revision restored." : "Published. Public pages can take up to a minute to refresh.");
  }

  const faq = content.faq ?? [];
  const sections = content.sections ?? [];
  return (
    <section className="space-y-5 rounded-xl border border-border bg-surface p-4 sm:p-6">
      {confirmDialog}
      <h2 className="font-heading text-xl font-semibold">{title}</h2>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {!loaded && !error ? <p role="status">Loading draft…</p> : null}
      {loaded ? (
        <>
          <form id="website-content-form" onSubmit={(event) => void save(event)} className="space-y-5">
            <fieldset disabled={busy} className="space-y-5">
              {!documentKey.startsWith("property") ? (
                <>
                  <TextField label="Title" value={content.title ?? ""} onChange={(title) => change({ title })} />
                  <TextField label="Summary" value={content.summary ?? ""} onChange={(summary) => change({ summary })} />
                  <TextField label="Body" value={content.body ?? ""} onChange={(body) => change({ body })} multiline maxLength={40000} />
                  <EntryFields title="Sections" first="Heading" second="Text" values={sections}
                    onChange={(next) => change({ sections: next })} />
                </>
              ) : null}
              <EntryFields title="FAQs" first="Question" second="Answer"
                values={faq.map(({ question, answer }) => ({ title: question, body: answer }))}
                onChange={(next) => change({ faq: next.map(({ title, body }): Faq => ({ question: title, answer: body })) })} />
              {content.faq != null ? <Button type="button" variant="ghost" onClick={() => change({ faq: null })}>Use existing FAQs</Button> : null}
              {documentKey === "page/contact" || documentKey === "page/apply-as-agent" ? (
                <fieldset className="space-y-3 border-t border-border pt-3">
                  <legend className="font-medium">Form copy</legend>
                  {Object.entries(contactFields).filter(([name]) =>
                    documentKey === "page/contact" || ["heading", "mobile", "email", "submit", "help"].includes(name)
                  ).map(([name, label]) => (
                    <TextField key={name} label={label} value={content.form_copy?.[name] ?? ""}
                      onChange={(value) => change({ form_copy: { ...content.form_copy, [name]: value } })} />
                  ))}
                </fieldset>
              ) : null}
              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={!dirty}>Save draft</Button>
                <Button type="button" variant="outline" aria-expanded={preview}
                  onClick={() => setPreview((value) => !value)}>{preview ? "Close preview" : "Preview draft"}</Button>
                {canPublish ? <Button type="button" variant="outline" disabled={!document || dirty} onClick={() => void publish()}>Publish</Button> : null}
              </div>
            </fieldset>
          </form>
          {preview ? (
            <section className="rounded-xl border border-border p-4" aria-label="Private draft preview">
              <WebsiteBody content={content} />
              <dl className="space-y-3">
                {faq.map((item, index) => <div key={index}><dt className="font-medium">{item.question}</dt><dd>{item.answer}</dd></div>)}
              </dl>
            </section>
          ) : null}
          {history.length ? (
            <div className="flex flex-wrap items-end gap-3">
              <label className="min-w-0 flex-1 space-y-2">
                <span className="text-sm font-medium">Published revisions</span>
                <select value={restoreRevision} className={selectClass} onChange={(event) => setRestoreRevision(event.target.value)}>
                  <option value="">Select a revision</option>
                  {history.map((item) => <option value={item.revision} key={item.revision}>Revision {item.revision} · {new Date(item.published_at).toLocaleString()}</option>)}
                </select>
              </label>
              {canPublish ? <Button type="button" variant="outline" disabled={busy || !restoreRevision || dirty}
                onClick={() => void publish(Number(restoreRevision))}>Restore revision</Button> : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function TextField({ label, value, onChange, multiline, maxLength, required }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  maxLength?: number;
  required?: boolean;
}) {
  const Field = multiline ? Textarea : Input;
  return <label className="block space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <Field value={value} maxLength={maxLength ?? 180} required={required}
      onChange={(event) => onChange(event.target.value)} />
  </label>;
}

function EntryFields({ title, first, second, values, onChange }: {
  title: string; first: string; second: string; values: Entry[];
  onChange: (items: Entry[]) => void;
}) {
  return (
    <fieldset className="space-y-3 border-t border-border pt-3">
      <legend className="font-medium">{title}</legend>
      {values.map((item, index) => (
        <div key={index} className="space-y-3 rounded-lg border border-border p-3">
          <TextField label={first} value={item.title} required
            onChange={(value) => onChange(values.map((entry, i) => i === index ? { ...entry, title: value } : entry))} />
          <TextField label={second} value={item.body} multiline maxLength={first === "Question" ? 3000 : 6000} required
            onChange={(value) => onChange(values.map((entry, i) => i === index ? { ...entry, body: value } : entry))} />
          <Button type="button" variant="ghost" onClick={() => onChange(values.filter((_, i) => i !== index))}>Remove {first.toLowerCase()}</Button>
        </div>
      ))}
      <Button type="button" variant="outline" disabled={values.length >= 30}
        onClick={() => onChange([...values, { title: "", body: "" }])}>Add {first.toLowerCase()}</Button>
    </fieldset>
  );
}
