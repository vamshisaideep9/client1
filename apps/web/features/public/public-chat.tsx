"use client";

import Link from "next/link";
import {
  ArrowLeft, ArrowUpRight, Building2, Check, ChevronRight, Landmark, Loader2,
  MessageCircle, RotateCcw,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { components } from "@contracts/generated/schema";

import { MobileInput } from "@/components/auth/mobile-input";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiRequest } from "@/lib/api/client";
import { isValidMobile, toE164 } from "@/lib/phone";
import { cn } from "@/lib/utils";

type Schemas = components["schemas"];
type Flow = Schemas["ChatFlow"];
type Section = Flow["section"];
type Action = Schemas["ChatAction"];
type Draft = { name: string; location: string; mobile: string; company: string };
type Screen = "welcome" | "financial" | "services" | "questions" | "review" | "contact" | "receipt";

const EMPTY_DRAFT: Draft = { name: "", location: "", mobile: "", company: "" };
const SECTIONS = {
  loans: "Loans", credit_cards: "Credit Cards", insurance: "Insurance", real_estate: "Real Estate",
} satisfies Record<Section, string>;

const PROPERTY_BUDGET: Record<string, [string, string]> = {
  "Under ₹60 lakh": ["", "6000000"],
  "₹60 lakh to ₹1.5 crore": ["6000000", "15000000"],
  "Above ₹1.5 crore": ["15000000", ""],
  "Under ₹50 lakh": ["", "5000000"],
  "₹50 lakh to under ₹2 crore": ["5000000", "20000000"],
  "₹2 crore to ₹10 crore": ["20000000", "100000000"],
  "Above ₹10 crore": ["100000000", ""],
  "Under ₹30 lakh": ["", "3000000"],
  "₹30 lakh to ₹1 crore": ["3000000", "10000000"],
  "Above ₹1 crore": ["10000000", ""],
};

function browseHref(flow: Flow, answers: string[]) {
  if (flow.section !== "real_estate") return flow.browse_href;
  const params = new URLSearchParams();
  const renting = answers[0] === "Rent / Lease" || answers[0] === "Lease / Rent space";
  if (renting) params.set("mode", "rent");
  if (answers[0]?.startsWith("Buy ") || flow.id === "plots") params.set("mode", "sale");
  if (answers[1] === "Independent villa") params.set("property_type", "villa");
  if (answers[0] === "Residential open plot") params.set("property_type", "plot");
  const budget = renting ? undefined : PROPERTY_BUDGET[answers[2]];
  if (budget?.[0]) params.set("budget_min", budget[0]);
  if (budget?.[1]) params.set("budget_max", budget[1]);
  return `/real-estate${params.size ? `?${params}` : ""}#property-results`;
}

function Reply({ children, onClick, icon, description }: {
  children: ReactNode; onClick: () => void; icon?: ReactNode; description?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-11 w-full items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 text-left text-sm font-medium text-brand-navy transition-colors hover:border-brand-navy/35 hover:bg-card/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      {icon && <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-sky">{icon}</span>}
      <span className="min-w-0 flex-1">
        {children}
        {description && <span className="mt-0.5 block text-xs font-normal text-text-secondary">{description}</span>}
      </span>
      <ChevronRight className="size-4 shrink-0 opacity-70" aria-hidden />
    </button>
  );
}

export function PublicChat({ whatsappHref }: { whatsappHref: string }) {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [screen, setScreen] = useState<Screen>("welcome");
  const [flows, setFlows] = useState<Flow[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [section, setSection] = useState<Section>("loans");
  const [flow, setFlow] = useState<Flow | null>(null);
  const [answers, setAnswers] = useState<string[]>([]);
  const [action, setAction] = useState<Action | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [receipt, setReceipt] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Draft, string>>>({});
  const submission = useRef<{ key: string; draft: string } | null>(null);
  const sending = useRef(false);
  const loading = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);

  async function loadFlows() {
    if (loading.current) return;
    loading.current = true;
    setLoadFailed(false);
    const response = await apiRequest<Flow[]>("/api/v1/leads/chat-inquiries/flows");
    loading.current = false;
    if (response.ok) setFlows(response.data);
    else setLoadFailed(true);
  }

  function changeOpen(next: boolean) {
    setOpen(next);
    if (next && !flows && !loadFailed) void loadFlows();
  }

  useEffect(() => setReady(true), []);

  useEffect(() => {
    if (open) heading.current?.focus();
  }, [open, screen, answers.length, flow?.id, section]);

  function reset() {
    setScreen("welcome");
    setSection("loans");
    setFlow(null);
    setAnswers([]);
    setAction(null);
    setDraft(EMPTY_DRAFT);
    setReceipt(null);
    setError("");
    setFieldErrors({});
    submission.current = null;
  }

  function chooseFlow(next: Flow) {
    setSection(next.section);
    setFlow(next);
    setAnswers([]);
    setScreen("questions");
  }

  function chooseSection(next: Section) {
    setSection(next);
    const options = flows?.filter((item) => item.section === next) ?? [];
    if (next === "credit_cards" && options[0]) chooseFlow(options[0]);
    else setScreen("services");
  }

  function editAnswers(index: number) {
    setAnswers(answers.slice(0, index));
    setScreen("questions");
  }

  function goBack() {
    setError("");
    switch (screen) {
      case "financial":
        setScreen("welcome");
        break;
      case "services":
        setScreen(section === "real_estate" ? "welcome" : "financial");
        break;
      case "questions":
        if (answers.length) editAnswers(answers.length - 1);
        else setScreen(section === "credit_cards" ? "financial" : "services");
        break;
      case "review":
        editAnswers(answers.length - 1);
        break;
      case "contact":
        setScreen("review");
        break;
    }
  }

  function updateDraft(field: keyof Draft, value: string) {
    setDraft({ ...draft, [field]: value });
    setFieldErrors({ ...fieldErrors, [field]: undefined });
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current || !flow || !action) return;
    const errors: typeof fieldErrors = {};
    if (!draft.name.trim()) errors.name = "Enter your full name.";
    if (!draft.location.trim()) errors.location = "Enter your preferred city or area.";
    if (!isValidMobile(draft.mobile)) errors.mobile = "Enter a valid 10-digit mobile number.";
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      requestAnimationFrame(() => form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
      return;
    }
    sending.current = true;
    setPending(true);
    setError("");
    const details = {
      flow: flow.id, action: action.id, answers,
      name: draft.name.trim(), location: draft.location.trim(), mobile: toE164(draft.mobile),
      company: draft.company || undefined,
    };
    const snapshot = JSON.stringify(details);
    if (submission.current?.draft !== snapshot) {
      submission.current = { key: crypto.randomUUID(), draft: snapshot };
    }
    const payload: Schemas["ChatInquiryCreate"] = { ...details, idempotency_key: submission.current.key };
    const response = await apiRequest<Schemas["ChatInquiryReceipt"]>("/api/v1/leads/chat-inquiries", {
      method: "POST", body: payload,
    });
    sending.current = false;
    setPending(false);
    if (response.ok) {
      setReceipt(response.data.reference);
      setDraft(EMPTY_DRAFT);
      submission.current = null;
      setScreen("receipt");
    } else {
      setError(response.error);
      if (response.status === 422) void loadFlows();
    }
  }

  if (!ready) return null;

  const available = (value: Section) => flows?.some((item) => item.section === value);
  const question = flow?.questions[answers.length];
  let title: string;
  let content: ReactNode;
  if (!flows && screen === "welcome") {
    title = "How can we help?";
    content = loadFailed ? (
      <>
        <p role="alert" className="text-sm text-text-secondary">Chat is temporarily unavailable.</p>
        <Button type="button" onClick={() => void loadFlows()}>Try again</Button>
        <Link className="block text-sm text-brand-link underline" href="/contact" onClick={() => setOpen(false)}>Contact our team</Link>
      </>
    ) : <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />Loading chat options</p>;
  } else if (screen === "welcome") {
    title = "How can we help?";
    content = <>
      <Reply icon={<Landmark className="size-5" aria-hidden />} description="Loans, cards and available insurance" onClick={() => setScreen("financial")}>Financial Services</Reply>
      <Reply icon={<Building2 className="size-5" aria-hidden />} description="Homes, commercial spaces and land" onClick={() => chooseSection("real_estate")}>Real Estate Services</Reply>
    </>;
  } else if (screen === "financial") {
    title = "Which financial service do you need?";
    const sections = (["loans", "credit_cards", "insurance"] as const).filter(available);
    content = sections.length ? sections.map((item) =>
      <Reply key={item} onClick={() => chooseSection(item)}>{SECTIONS[item]}</Reply>,
    ) : <Link href="/contact?line=loans" className="text-sm text-brand-link underline" onClick={() => setOpen(false)}>Contact the financial services team</Link>;
  } else if (screen === "services") {
    title = section === "real_estate" ? "What kind of property are you looking for?" : `Choose a service in ${SECTIONS[section]}`;
    content = flows?.filter((item) => item.section === section).map((item) =>
      <Reply key={item.id} onClick={() => chooseFlow(item)}>{item.label}</Reply>,
    );
  } else if (screen === "questions" && flow && question) {
    title = question.prompt;
    content = question.options.map((option) =>
      <Reply key={option} onClick={() => {
        const next = [...answers, option];
        setAnswers(next);
        if (next.length === flow.questions.length) setScreen("review");
      }}>{option}</Reply>,
    );
  } else if (screen === "review" && flow) {
    title = "Review your preferences";
    const href = browseHref(flow, answers);
    content = <>
      <ul className="grid gap-2 rounded-xl border border-border bg-card p-3 text-sm">
        {flow.questions.map((item, index) => (
          <li key={item.prompt} className="flex items-center justify-between gap-2">
            <div><p className="text-xs text-text-secondary">{item.prompt}</p><p className="font-medium">{answers[index]}</p></div>
            <Button type="button" size="sm" variant="ghost" className="min-h-11 text-brand-link" aria-label={`Edit answer for ${item.prompt}`} onClick={() => editAnswers(index)}>Edit</Button>
          </li>
        ))}
      </ul>
      {flow.actions.map((item) => <Reply key={item.id} onClick={() => { setAction(item); setScreen("contact"); }}>{item.label}</Reply>)}
      {href && <Button asChild variant="outline" className="min-h-11">
        <Link href={href} onClick={() => setOpen(false)}>
          {flow.section === "credit_cards" ? "Browse credit cards" : flow.section === "real_estate" ? "Browse properties" : "View service details"} <ArrowUpRight aria-hidden />
        </Link>
      </Button>}
    </>;
  } else if (screen === "contact") {
    title = "Where should we reach you?";
    content = (
      <form ref={form} className="grid gap-3" onSubmit={submit} noValidate>
        <div className="sr-only" aria-hidden>
          <label htmlFor="site-chat-company">Company</label>
          <input id="site-chat-company" tabIndex={-1} autoComplete="off" value={draft.company} onChange={(event) => updateDraft("company", event.target.value)} />
        </div>
        {(["name", "location", "mobile"] as const).map((field) => {
          const id = `site-chat-${field}`;
          const label = { name: "Full name", location: "Preferred city or area", mobile: "Mobile number" }[field];
          const shared = {
            id, value: draft[field], disabled: pending, required: true,
            "aria-invalid": Boolean(fieldErrors[field]),
            "aria-describedby": fieldErrors[field] ? `${id}-error` : undefined,
          };
          return <div key={field} className="grid gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            {field === "mobile" ? <MobileInput {...shared} autoComplete="tel-national" onChange={(event) => updateDraft(field, event.target.value)} /> :
              <Input {...shared} autoComplete={field === "name" ? "name" : "address-level2"} maxLength={field === "name" ? 100 : 120} className="h-11 bg-card text-base" onChange={(event) => updateDraft(field, event.target.value)} />}
            {fieldErrors[field] && <p id={`${id}-error`} className="text-sm text-destructive">{fieldErrors[field]}</p>}
          </div>;
        })}
        <p className="text-xs leading-relaxed text-text-secondary">
          We’ll use these details and your answers to follow up about this inquiry.{" "}
          <Link href="/privacy" className="text-brand-link underline" target="_blank" rel="noopener noreferrer">Privacy notice</Link>
        </p>
        {error && <p role="alert" className="rounded-md border border-destructive/30 bg-card p-3 text-sm text-destructive">{error}</p>}
        <Button type="submit" className="min-h-11" disabled={pending}>{pending && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}{pending ? "Sending…" : "Send inquiry"}</Button>
      </form>
    );
  } else {
    title = "Inquiry received";
    content = <>
      <div className="rounded-xl border border-border bg-card p-4">
        <Check className="mb-2 size-5 text-success" aria-hidden />
        <p className="text-sm">Your inquiry reference is <strong className="break-all">{receipt}</strong>. Our team will follow up.</p>
      </div>
      {flow?.section === "real_estate" && available("loans") && <Reply onClick={() => {
        reset();
        const home = flows?.find((item) => item.id === "home-loan");
        if (home) chooseFlow(home);
        else chooseSection("loans");
      }}>Need a home or plot loan?</Reply>}
    </>;
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          aria-label="Open Dhanadhara chat"
          className="fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 size-14 rounded-full bg-brand-navy p-0 text-white shadow-lg ring-2 ring-white hover:bg-primary/90 focus-visible:ring-offset-4 sm:right-6 lg:bottom-6"
          data-public-chat-launcher
        >
          <MessageCircle className="size-6" aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent
        preventOutsideClose
        showCloseButton={false}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          heading.current?.focus();
        }}
        data-public-chat-panel
        className={cn(
          "top-0 right-0 bottom-0 left-auto flex h-dvh max-h-none w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-0 bg-surface-sky p-0",
          "sm:top-auto sm:right-6 sm:bottom-6 sm:h-[min(42rem,calc(100dvh-3rem))] sm:max-w-[25rem] sm:rounded-2xl sm:border sm:border-white sm:p-0",
        )}
      >
        <header className="flex shrink-0 items-center gap-3 bg-brand-navy px-4 pt-[max(0.75rem,env(safe-area-inset-top))] pb-3 text-white">
          <span className="grid size-9 place-items-center rounded-xl bg-white/15"><MessageCircle className="size-5" aria-hidden /></span>
          <div className="min-w-0 flex-1">
            <DialogTitle className="font-heading text-base font-semibold">Dhanadhara Assistant</DialogTitle>
            <DialogDescription className="text-xs text-white/85">Financial and real estate enquiries</DialogDescription>
          </div>
          <Button type="button" variant="ghost" className="min-h-11 px-2 text-white hover:bg-white/15 hover:text-white focus-visible:ring-white" onClick={() => setOpen(false)}>Close</Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4">
          {screen !== "welcome" && <div className="mb-3 flex items-center justify-between gap-2">
            {screen !== "receipt" && <Button type="button" variant="ghost" className="min-h-11 px-2 text-brand-link" disabled={pending} onClick={goBack}><ArrowLeft aria-hidden />Back</Button>}
            <Button type="button" variant="ghost" className="ml-auto min-h-11 px-2 text-brand-link" disabled={pending} onClick={reset}><RotateCcw aria-hidden />Start over</Button>
          </div>}
          {screen === "questions" && flow && <div className="mb-3 space-y-1.5">
            <p className="text-xs font-semibold text-brand-navy">{flow.label} · Question {answers.length + 1} of {flow.questions.length}</p>
            <progress className="block h-1.5 w-full accent-brand-navy" aria-label="Questions answered" value={answers.length} max={flow.questions.length} />
          </div>}
          <h2 ref={heading} tabIndex={-1} className="mb-4 font-heading text-xl leading-snug font-semibold text-brand-heading outline-none">{title}</h2>
          <div className="grid gap-2.5">{content}</div>
        </div>
        <footer className="shrink-0 border-t border-border bg-card px-4 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
          <Button asChild variant="ghost" className="min-h-11 text-brand-link">
            <a href={whatsappHref} target="_blank" rel="noopener noreferrer">Message our team on WhatsApp <ArrowUpRight aria-hidden /></a>
          </Button>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
